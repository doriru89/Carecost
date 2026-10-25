"""Staged TiC prices x matched provider groups -> ``rate_row`` (+ ``tic_*`` columns).

One output row = one negotiated price x one provider group (TIN + its NPI list) that the price's
``provider_references`` point to and that matches the target list (:mod:`targets`). Never
collapsed: identical keys get ``nk_ordinal`` 0, 1, ...; if they disagree on the amount they are
all flagged ``ambiguous_multi_rate``. Placeholder dollar amounts ($0, $0.01, $1) are dropped and
counted, as in the hospital pipeline.

Columns: every ``contracts.RateRow`` field (each row is validated against the model) followed by
TiC fields the contract has no slot for yet (``tic_*``: TIN type/value, business name,
provider_group_id, NPI count, negotiated_type, negotiation_arrangement, expiration_date,
service codes, network, fetched_at, ...). ``billing_npis`` is '' for TiC rows: a UHC group can
list 2,000+ NPIs, so NPIs stay in ``groups.parquet`` and join on
(``source_sha256``, ``tic_provider_group_id``, ``tic_group_ordinal``). See the A2 report for the
proposed contract change.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl.contracts import RateRow
from app.etl.normalize import RATE_ROW_SCHEMA, is_placeholder
from app.etl.tic.index import atomic_write_table, atomic_write_text
from app.etl.tic.networks import TicNetwork
from app.etl.tic.targets import Targets

_NEG_TYPE = {
    "fee schedule": "fee_schedule",
    "per diem": "per_diem",
    "percentage": "percent_of_total_billed_charges",
    "negotiated": "other",
    "derived": "other",
}
_SETTING = {"inpatient", "outpatient", "both"}

S = pa.string()
TIC_FIELDS = [
    ("tic_tin_type", S), ("tic_tin_value", S), ("tic_business_name", S),
    ("tic_provider_group_id", pa.int64()), ("tic_group_ordinal", pa.int64()),
    ("tic_npi_count", pa.int64()), ("tic_match", S), ("tic_site_ids", S),
    ("tic_negotiated_type", S), ("tic_negotiation_arrangement", S), ("tic_expiration_date", S),
    ("tic_service_codes", S), ("tic_billing_code_type_version", S), ("tic_item_name", S),
    ("tic_network_label", S), ("tic_product", S), ("tic_reporting_entity", S),
    ("tic_fetched_at", S), ("tic_item_ordinal", pa.int64()), ("tic_rate_group_ordinal", pa.int64()),
    ("tic_price_ordinal", pa.int64()),
]  # fmt: skip
TIC_RATE_ROW_SCHEMA = pa.schema(list(RATE_ROW_SCHEMA) + [pa.field(n, t) for n, t in TIC_FIELDS])
CORE = [f.name for f in RATE_ROW_SCHEMA]


@dataclass
class NormalizeStats:
    source_id: str
    source_sha256: str
    price_rows: int = 0
    price_rows_with_target: int = 0
    expected_rows: int = 0
    rate_rows: int = 0
    placeholders_dropped: dict[str, int] = field(default_factory=dict)
    unresolved_ref_ids: int = 0
    matched_groups: int = 0
    matched_by: dict[str, int] = field(default_factory=dict)
    matched_tins: int = 0
    codes: dict[str, int] = field(default_factory=dict)
    negotiated_type: dict[str, int] = field(default_factory=dict)
    billing_class: dict[str, int] = field(default_factory=dict)
    ambiguous_rows: int = 0
    seconds: float = 0.0


def _num(s: str) -> float | None:
    try:
        return float(s) if s not in ("", None) else None
    except ValueError:
        return None


def entity_for(tin_type: str, digits: str, value: str) -> str:
    t = (tin_type or "").lower()
    if t == "npi":
        return f"npi:{digits}"
    return f"tin:{digits}" if digits else f"tin_raw:{value}"


def normalize_network(
    d: Path,
    net: TicNetwork,
    run: dict[str, Any],
    targets: Targets,
    out: Path | None = None,
) -> NormalizeStats:
    """Read ``d/{prices,items,groups}.parquet`` + run meta, write ``d/rate_row.parquet``."""
    t0 = time.time()
    sha = run["source_sha256"]
    st = NormalizeStats(net.source_id, sha)
    # 1. matched provider groups
    gcols = ["provider_group_id", "group_ordinal", "tin_type", "tin_value", "tin_digits",
             "business_name", "npis", "n_npi"]  # fmt: skip
    matched: dict[int, list[dict[str, Any]]] = defaultdict(list)
    known_refs: set[int] = set()
    tins: set[str] = set()
    by: Counter[str] = Counter()
    for batch in pq.ParquetFile(d / "groups.parquet").iter_batches(
        columns=gcols, batch_size=50_000
    ):
        for g in batch.to_pylist():
            known_refs.add(g["provider_group_id"])
            how = targets.match(g["tin_digits"], g["npis"])
            if how:
                g["match"] = how
                g["sites"] = ";".join(sorted(targets.sites_for(g["tin_digits"], g["npis"])))
                del g["npis"]
                matched[g["provider_group_id"]].append(g)
                tins.add(g["tin_digits"])
                by[how] += 1
    st.matched_groups = sum(len(v) for v in matched.values())
    st.matched_by = dict(by)
    st.matched_tins = len(tins)
    items = {
        r["item_ordinal"]: r
        for r in pq.read_table(
            d / "items.parquet",
            columns=["item_ordinal", "name", "description", "billing_code_type_version"],
        ).to_pylist()
    }
    # 2. explode prices x matched groups
    rows: list[dict[str, Any]] = []
    placeholders: Counter[str] = Counter()
    unresolved: set[int] = set()
    nk_count: Counter[str] = Counter()
    nk_amounts: dict[str, set[float | None]] = defaultdict(set)
    try:
        src_date = datetime.date.fromisoformat(str(run.get("last_updated_on"))[:10])
    except ValueError:
        src_date = None
    for batch in pq.ParquetFile(d / "prices.parquet").iter_batches(batch_size=50_000):
        for p in batch.to_pylist():
            st.price_rows += 1
            refs = p["provider_references"] or []
            unresolved.update(r for r in refs if r not in known_refs)
            hits = [g for r in refs for g in matched.get(r, ())]
            if not hits or p["price_ordinal"] < 0:
                continue
            st.price_rows_with_target += 1
            st.expected_rows += len(hits)
            ntype = p["negotiated_type"].strip().lower()
            rate = _num(p["negotiated_rate"])
            is_pct = ntype == "percentage"
            if rate is not None and not is_pct and is_placeholder(rate):
                placeholders[f"{rate:.2f}"] += len(hits)
                continue
            it = items.get(p["item_ordinal"], {})
            mods = "|".join(sorted(m.strip() for m in p["billing_code_modifier"] if m.strip()))
            pos = "|".join(sorted(p["service_code"]))
            bc = p["billing_class"].strip().lower()
            billing_class = (
                "professional"
                if bc == "professional"
                else "facility"
                if bc == "institutional"
                else "unknown"
            )
            setting = p["setting"].strip().lower()
            setting = setting if setting in _SETTING else "unknown"
            for g in hits:
                entity = entity_for(g["tin_type"], g["tin_digits"], g["tin_value"])
                nk_parts = [
                    net.source_id, entity, p["billing_code_type"], p["billing_code"], mods,
                    billing_class, setting, pos, ntype, p["expiration_date"],
                    str(g["provider_group_id"]), str(g["group_ordinal"]),
                ]  # fmt: skip
                nk = hashlib.sha1("\x1f".join(nk_parts).encode()).hexdigest()[:16]
                ordinal = nk_count[nk]
                nk_count[nk] += 1
                amount = None if is_pct else rate
                nk_amounts[nk].add(rate)
                rows.append(
                    {
                        "row_id": f"{nk}:{ordinal}", "nk_hash": nk, "nk_ordinal": ordinal,
                        "source_id": net.source_id, "source_kind": "insurer_tic",
                        "entity_id": entity, "row_kind": "payer_rate", "billing_npis": "",
                        "code_type": p["billing_code_type"], "code": p["billing_code"],
                        "modifiers": mods, "rev_code": "", "cdm_code": "",
                        "description": it.get("description") or it.get("name") or "",
                        "setting": setting, "billing_class": billing_class,
                        "component": billing_class,
                        "component_rule": "billing_class" if billing_class != "unknown" else "none",
                        "payer_raw": run.get("reporting_entity_name") or "",
                        "plan_raw": net.label, "payer_id": net.payer_id,
                        "line_of_business": net.lob, "product": net.product,
                        "methodology": _NEG_TYPE.get(ntype, "unknown" if not ntype else "other"),
                        "methodology_raw": p["negotiated_type"],
                        "dollar_basis": "pct_of_charges" if is_pct else ("dollar" if rate is not None else "none"),
                        "negotiated_dollar": None if is_pct else rate,
                        "negotiated_pct": rate if is_pct else None,
                        "negotiated_algorithm": "",
                        "amount": amount, "amount_method": "stated" if amount is not None else "none",
                        "gross": None, "gross_rule": "none", "discounted_cash": None,
                        "min_negotiated": None, "max_negotiated": None, "median_amount": None,
                        "p10_amount": None, "p90_amount": None, "allowed_count": "",
                        "above_gross": False, "ambiguous_multi_rate": False,
                        "payer_plan_mismatch": False, "excluded": False, "exclude_reason": "",
                        "additional_generic_notes": "",
                        "additional_payer_notes": p["additional_information"],
                        "source_file": run["source_file"], "source_sha256": sha,
                        "source_date": src_date, "stage_row": p["stage_row"],
                        "row_ref": f"{net.source_id}:{sha[:12]}:{p['stage_row']}",
                        "tic_tin_type": g["tin_type"], "tic_tin_value": g["tin_value"],
                        "tic_business_name": g["business_name"],
                        "tic_provider_group_id": g["provider_group_id"],
                        "tic_group_ordinal": g["group_ordinal"], "tic_npi_count": g["n_npi"],
                        "tic_match": g["match"], "tic_site_ids": g["sites"],
                        "tic_negotiated_type": p["negotiated_type"],
                        "tic_negotiation_arrangement": "",
                        "tic_expiration_date": p["expiration_date"], "tic_service_codes": pos,
                        "tic_billing_code_type_version": it.get("billing_code_type_version") or "",
                        "tic_item_name": it.get("name") or "", "tic_network_label": net.label,
                        "tic_product": net.product,
                        "tic_reporting_entity": run.get("reporting_entity_name") or "",
                        "tic_fetched_at": (run.get("fetch") or {}).get("fetched_at") or "",
                        "tic_item_ordinal": p["item_ordinal"],
                        "tic_rate_group_ordinal": p["rate_group_ordinal"],
                        "tic_price_ordinal": p["price_ordinal"],
                    }
                )  # fmt: skip
    arr = {
        r["item_ordinal"]: r["negotiation_arrangement"]
        for r in pq.read_table(
            d / "items.parquet", columns=["item_ordinal", "negotiation_arrangement"]
        ).to_pylist()
    }
    ambiguous = {nk for nk, a in nk_amounts.items() if len(a) > 1}
    for r in rows:
        r["ambiguous_multi_rate"] = r["nk_hash"] in ambiguous
        r["tic_negotiation_arrangement"] = arr.get(r["tic_item_ordinal"], "")
        RateRow(**{k: r[k] for k in CORE})  # every row typed against the contract
    st.rate_rows = len(rows)
    st.placeholders_dropped = dict(placeholders)
    st.unresolved_ref_ids = len(unresolved)
    st.codes = dict(Counter(r["code"] for r in rows))
    st.negotiated_type = dict(Counter(r["tic_negotiated_type"] for r in rows))
    st.billing_class = dict(Counter(r["billing_class"] for r in rows))
    st.ambiguous_rows = sum(1 for r in rows if r["ambiguous_multi_rate"])
    if st.rate_rows + sum(placeholders.values()) != st.expected_rows:
        raise RuntimeError(f"{net.source_id}: normalize row conservation failed")
    out = out or d / "rate_row.parquet"
    atomic_write_table(pa.Table.from_pylist(rows, TIC_RATE_ROW_SCHEMA), out)
    st.seconds = round(time.time() - t0, 1)
    atomic_write_text(
        out.with_suffix(".stats.json"), json.dumps(asdict(st), indent=1, sort_keys=True)
    )
    return st
