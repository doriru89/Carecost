"""Stage 3+4: staged leaves -> ``rate_row`` for the target codes. Never collapses rows.

Each staged leaf that carries a target code (code type CPT / HCPCS / blank) becomes one
RateRow per target code on the line, except placeholder amounts ($0, $0.01, $1), which are
dropped and counted. Rows are typed against ``contracts.RateRow`` as they are written.

Natural key = entity x code_type x code x modifiers x billing_class x setting x component x
rev_code x payer_raw x plan_raw x methodology x cdm_code x description; ``nk_ordinal`` numbers
rows sharing a key in file order. If such rows disagree on the amount the source itself is
ambiguous and every one of them is flagged ``ambiguous_multi_rate``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
import typing
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.etl.config import CodeList, SourceSpec, load_codes
from app.etl.contracts import RateRow
from app.etl.payers import PayerResolver
from app.etl.stage import StageResult

PLACEHOLDERS = (0.0, 0.01, 1.0)
_SETTINGS = {"inpatient", "outpatient", "both"}
_METHODOLOGY = {
    "fee schedule": "fee_schedule",
    "percent of total billed charges": "percent_of_total_billed_charges",
    "per diem": "per_diem",
    "case rate": "case_rate",
    "other": "other",
}


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def is_placeholder(amount: float) -> bool:
    return any(abs(amount - p) < 1e-9 for p in PLACEHOLDERS)


def canonical_setting(s: str) -> str:
    v = (s or "").strip().lower()
    return v if v in _SETTINGS else "unknown"


def canonical_billing_class(s: str) -> str:
    v = (s or "").strip().lower()
    if v in ("facility", "facillity", "institutional"):
        return "facility"
    if v == "professional":
        return "professional"
    return "unknown"


def canonical_methodology(s: str) -> str:
    v = (s or "").strip().lower()
    if not v:
        return "unknown"
    return _METHODOLOGY.get(v, "other")


def component_for(
    codes: list[dict[str, str]], billing_class: str, code_list: CodeList
) -> tuple[str, str]:
    rcs = [c["code"] for c in codes if c["type"] == "RC"]
    if rcs:
        return code_list.component_for_rc(rcs[0]), "rev_code"
    bc = canonical_billing_class(billing_class)
    if bc != "unknown":
        return bc, "billing_class"
    return "unknown", "none"


def resolve_amount(leaf: dict[str, Any], gross: float | None) -> tuple[float | None, str, str]:
    """-> (amount, amount_method, dollar_basis). A % is turned into dollars only with a gross."""
    dollar = _num(leaf.get("negotiated_dollar"))
    pct = _num(leaf.get("negotiated_percentage"))
    alg = (leaf.get("negotiated_algorithm") or "").strip()
    meth = canonical_methodology(leaf.get("methodology", ""))
    if pct is not None or meth == "percent_of_total_billed_charges":
        basis = "pct_of_charges"
    elif dollar is not None:
        basis = "dollar"
    elif alg:
        basis = "algorithm"
    else:
        basis = "none"
    if dollar is not None:
        return dollar, "stated", basis
    if pct is not None and gross is not None:
        return round(pct / 100.0 * gross, 2), "derived_pct_x_gross", basis
    return None, "none", basis


@dataclass
class NormalizeResult:
    source_id: str
    source_sha256: str
    target_leaves: int = 0
    rate_rows: int = 0
    payer_rate_rows: int = 0
    chargemaster_rows: int = 0
    placeholders_dropped: dict[str, int] = field(default_factory=dict)
    excluded: dict[str, int] = field(default_factory=dict)
    payer_ids: dict[str, int] = field(default_factory=dict)
    amount_method: dict[str, int] = field(default_factory=dict)
    dollar_basis: dict[str, int] = field(default_factory=dict)
    ambiguous_rows: int = 0
    above_gross_rows: int = 0
    payer_plan_mismatch_rows: int = 0
    seconds: float = 0.0


def _arrow_type(ann: Any) -> pa.DataType:
    args = [a for a in typing.get_args(ann) if a is not type(None)] or [ann]
    a = args[0]
    if a is bool:
        return pa.bool_()
    if a is int:
        return pa.int64()
    if a is float:
        return pa.float64()
    if a is datetime.date:
        return pa.date32()
    return pa.string()


def rate_row_schema() -> pa.Schema:
    return pa.schema(
        [pa.field(n, _arrow_type(f.annotation)) for n, f in RateRow.model_fields.items()]
    )


RATE_ROW_SCHEMA = rate_row_schema()


def _target_regex(codes: set[str]) -> str:
    return r"\|(" + "|".join(sorted(re.escape(c) for c in codes)) + r")\|"


def _iter_target_leaves(staged: Path, codes: set[str]) -> Iterator[dict[str, Any]]:
    rx = _target_regex(codes)
    pf = pq.ParquetFile(staged, pre_buffer=False)
    for batch in pf.iter_batches(batch_size=20_000, use_threads=False):
        mask = pc.match_substring_regex(batch.column("code_values"), rx)
        sub = batch.filter(mask)
        if sub.num_rows:
            yield from sub.to_pylist()


def normalize_file(
    spec: SourceSpec,
    staged: Path,
    stage_res: StageResult | dict[str, Any],
    out: Path,
    code_list: CodeList | None = None,
    resolver: PayerResolver | None = None,
) -> NormalizeResult:
    t0 = time.time()
    code_list = code_list or load_codes()
    resolver = resolver or PayerResolver.load()
    meta = stage_res.meta.to_json() if isinstance(stage_res, StageResult) else stage_res["meta"]
    raw_file = stage_res.raw_file if isinstance(stage_res, StageResult) else stage_res["raw_file"]
    sha = (
        stage_res.source_sha256
        if isinstance(stage_res, StageResult)
        else stage_res["source_sha256"]
    )
    source_date = meta.get("last_updated_on")
    npis = "|".join(meta.get("type_2_npis") or [])
    targets = code_list.codes
    types = set(code_list.code_types)

    leaves = list(_iter_target_leaves(staged, targets))

    # chargemaster gross index for payer lines that carry no gross (JSON two-record shape)
    gross_idx: dict[tuple[str, str], set[float]] = defaultdict(set)
    for lf in leaves:
        g = _num(lf["gross"])
        if g is None or lf["payer_name"]:
            continue
        for c in lf["codes"]:
            if c["code"] in targets and c["type"] in types:
                gross_idx[(c["code"], canonical_setting(lf["setting"]))].add(g)

    res = NormalizeResult(source_id=spec.source_id, source_sha256=sha)
    rows: list[dict[str, Any]] = []
    nk_count: Counter[str] = Counter()
    nk_amounts: dict[str, set[float | None]] = defaultdict(set)
    placeholders: Counter[str] = Counter()

    for lf in leaves:
        line_codes: list[tuple[str, str]] = []
        for c in lf["codes"]:
            if (
                c["code"] in targets
                and c["type"] in types
                and c["code"] not in [x[0] for x in line_codes]
            ):
                line_codes.append((c["code"], c["type"]))
        if not line_codes:
            continue  # target code only present as an RC/CDM token
        rc = next((c["code"] for c in lf["codes"] if c["type"] == "RC"), "")
        cdm = next((c["code"] for c in lf["codes"] if c["type"] == "CDM"), "")
        component, comp_rule = component_for(lf["codes"], lf["billing_class"], code_list)
        setting = canonical_setting(lf["setting"])
        payer_raw = (lf["payer_name"] or "").strip()
        plan_raw = (lf["plan_name"] or "").strip()
        row_kind = "payer_rate" if payer_raw else "chargemaster"
        pres = resolver.resolve(payer_raw, plan_raw) if payer_raw else None
        mods = "|".join(
            sorted(m.strip() for m in re.split(r"[|,]", lf["modifiers"] or "") if m.strip())
        )
        meth = canonical_methodology(lf["methodology"])
        for code, ctype in line_codes:
            res.target_leaves += 1
            gross = _num(lf["gross"])
            gross_rule = "same_row" if gross is not None else "none"
            if gross is None and row_kind == "payer_rate":
                cands = gross_idx.get((code, setting), set()) | gross_idx.get((code, "both"), set())
                if len(cands) == 1:
                    gross, gross_rule = next(iter(cands)), "joined_code_setting"
                elif len(cands) > 1:
                    gross_rule = "ambiguous"
            if row_kind == "payer_rate":
                amount, amount_method, basis = resolve_amount(lf, gross)
                if amount is not None and is_placeholder(amount):
                    placeholders[f"{amount:.2f}"] += 1
                    continue
            else:
                amount, amount_method, basis = None, "none", "none"
            nk_parts = [
                spec.hospital_entity, ctype, code, mods, canonical_billing_class(lf["billing_class"]), setting,
                component, rc, payer_raw, plan_raw, meth, cdm, (lf["description"] or "").strip(),
            ]  # fmt: skip
            nk = hashlib.sha1("\x1f".join(nk_parts).encode()).hexdigest()[:16]
            ordinal = nk_count[nk]
            nk_count[nk] += 1
            nk_amounts[nk].add(amount)
            stage_row = int(lf["stage_row"])
            row = {
                "row_id": f"{nk}:{ordinal}",
                "nk_hash": nk,
                "nk_ordinal": ordinal,
                "source_id": spec.source_id,
                "source_kind": spec.kind.value,
                "entity_id": spec.hospital_entity,
                "row_kind": row_kind,
                "billing_npis": npis,
                "code_type": ctype,
                "code": code,
                "modifiers": mods,
                "rev_code": rc,
                "cdm_code": cdm,
                "description": (lf["description"] or "").strip(),
                "setting": setting,
                "billing_class": canonical_billing_class(lf["billing_class"]),
                "component": component,
                "component_rule": comp_rule,
                "payer_raw": payer_raw,
                "plan_raw": plan_raw,
                "payer_id": pres.payer_id if pres else None,
                "line_of_business": pres.line_of_business if pres else "unknown",
                "product": pres.product if pres else "",
                "methodology": meth,
                "methodology_raw": (lf["methodology"] or "").strip(),
                "dollar_basis": basis,
                "negotiated_dollar": _num(lf["negotiated_dollar"]),
                "negotiated_pct": _num(lf["negotiated_percentage"]),
                "negotiated_algorithm": (lf["negotiated_algorithm"] or "").strip(),
                "amount": amount,
                "amount_method": amount_method,
                "gross": gross,
                "gross_rule": gross_rule,
                "discounted_cash": _num(lf["discounted_cash"]),
                "min_negotiated": _num(lf["min"]),
                "max_negotiated": _num(lf["max"]),
                "median_amount": _num(lf["median_amount"]),
                "p10_amount": _num(lf["p10"]),
                "p90_amount": _num(lf["p90"]),
                "allowed_count": (lf["count"] or "").strip(),
                "above_gross": bool(
                    amount is not None and gross is not None and amount > gross + 0.005
                ),
                "ambiguous_multi_rate": False,
                "payer_plan_mismatch": bool(pres and pres.payer_plan_mismatch),
                "excluded": bool(pres and pres.excluded),
                "exclude_reason": pres.exclude_reason if pres else "",
                "additional_generic_notes": (lf["additional_generic_notes"] or "").strip(),
                "additional_payer_notes": (lf["additional_payer_notes"] or "").strip(),
                "source_file": raw_file,
                "source_sha256": sha,
                "source_date": source_date,
                "stage_row": stage_row,
                "row_ref": f"{spec.source_id}:{sha[:12]}:{stage_row}",
            }
            rows.append(row)

    ambiguous = {nk for nk, amts in nk_amounts.items() if len(amts) > 1}
    validated: list[dict[str, Any]] = []
    for row in rows:
        row["ambiguous_multi_rate"] = row["nk_hash"] in ambiguous
        validated.append(RateRow(**row).model_dump(mode="python"))

    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(_arrowable(validated), RATE_ROW_SCHEMA)
    pq.write_table(table, out.with_suffix(".parquet.partial"), compression="zstd")
    out.with_suffix(".parquet.partial").replace(out)

    res.rate_rows = len(validated)
    res.payer_rate_rows = sum(1 for r in validated if r["row_kind"] == "payer_rate")
    res.chargemaster_rows = res.rate_rows - res.payer_rate_rows
    res.placeholders_dropped = dict(placeholders)
    res.excluded = dict(Counter(r["exclude_reason"] for r in validated if r["excluded"]))
    res.payer_ids = dict(
        Counter(r["payer_id"] or "(none)" for r in validated if r["row_kind"] == "payer_rate")
    )
    res.amount_method = dict(Counter(str(r["amount_method"]) for r in validated))
    res.dollar_basis = dict(Counter(str(r["dollar_basis"]) for r in validated))
    res.ambiguous_rows = sum(1 for r in validated if r["ambiguous_multi_rate"])
    res.above_gross_rows = sum(1 for r in validated if r["above_gross"])
    res.payer_plan_mismatch_rows = sum(1 for r in validated if r["payer_plan_mismatch"])
    res.seconds = round(time.time() - t0, 2)
    if res.target_leaves != res.rate_rows + sum(placeholders.values()):
        raise RuntimeError(f"{spec.source_id}: normalize row conservation failed")
    out.with_suffix(".stats.json").write_text(json.dumps(asdict(res), indent=1, sort_keys=True))
    return res


def _arrowable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append({k: (v.value if hasattr(v, "value") else v) for k, v in r.items()})
    return out
