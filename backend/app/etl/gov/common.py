"""Shared pieces of the government fee-schedule readers.

Every reader turns one published file into ``RateRow`` rows (the existing contract, hospital
columns only), so the quote engine reads Medicare / MassHealth numbers exactly like hospital
rows. How the contract fields are used for a fee schedule:

=====================  =====================================================================
``entity_id``          the price area: ``medicare_ma_01`` (Metropolitan Boston locality),
                       ``medicare_ma_99`` (rest of MA), ``medicare_national`` (OPPS / ASC
                       national unadjusted), ``masshealth`` (statewide)
``row_kind``           ``payer_rate`` (a government payer's own rate)
``payer_raw/_id``      the schedule name / ``MEDICARE`` or ``MASSHEALTH``
``plan_raw``           the published column the amount was read from: ``non_facility``,
                       ``facility``, ``global``, ``professional`` (-26), ``technical`` (-TC),
                       ``opps``, ``asc``, ``anesthesia_base`` (kept for row_ref and audit; the
                       engine never reads it)
``place_of_service``   ``non_facility`` (office, POS 11) / ``facility`` (hospital / ASC, POS
                       19/22/24) for a rate split by place of service, else None (stream C2)
``methodology``        ``fee_schedule``; ``dollar_basis`` ``dollar``
``amount``             the dollar amount; ``negotiated_algorithm`` holds the formula with the
                       inputs it used (PFS: RVUs x GPCIs x CF), so a number is re-derivable
``row_ref``            ``<source_id>:<sha12>:<line>:<variant>`` (line = 1-based line or row of
                       the published table), unique within the source
=====================  =====================================================================

``RateRow.provenance()`` / ``to_cell()`` (``app/etl/contracts.py``) know fee schedules (stream
C2): basis ``fee_schedule``, method ``computed_fee_schedule`` for the Medicare PFS, ``stated`` for
a number copied from the table (OPPS / ASC / MassHealth), and no ``payer_id`` (``Money`` rejects a
fee-schedule number that carries one). ``fee_schedule_money`` below renders the same Money.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl.contracts import Method, Money, PriceBasis, Provenance, RateRow, SourceKind
from app.etl.normalize import RATE_ROW_SCHEMA, _arrowable

COMPUTED_VARIANTS = {"non_facility", "facility", "anesthesia_base"}
"""PFS variants we compute (RVU x GPCI x CF, base units x CF). Everything else is stated."""


class GovReadError(RuntimeError):
    """The published file does not look like the format we read: fail loudly, never guess."""


@dataclass
class ReadResult:
    rows: list[dict[str, Any]]
    effective_date: date
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def money_str(s: str) -> float | None:
    """'$1,644.87 ' -> 1644.87; '-' / '' / 'IC' / 'I.C.' -> None."""
    t = (s or "").strip().replace("$", "").replace(",", "").strip()
    if t in ("", "-", ".", "IC", "I.C.", "N/A"):
        return None
    try:
        return float(t)
    except ValueError as e:
        raise GovReadError(f"not a dollar amount: {s!r}") from e


def make_row(
    *,
    source_id: str,
    kind: SourceKind,
    sha: str,
    source_file: str,
    source_date: date,
    entity_id: str,
    payer_id: str,
    payer_raw: str,
    line: int,
    variant: str,
    code: str,
    modifiers: str,
    description: str,
    amount: float,
    algorithm: str = "",
    code_type: str = "HCPCS",
    lob: str = "medicare",
    notes: str = "",
) -> dict[str, Any]:
    """One RateRow dict (validated by ``finish``). The natural key includes the variant, so a
    code's office and facility prices are two rows, never collapsed."""
    nk_parts = [entity_id, code_type, code, modifiers, variant, payer_raw]
    nk = hashlib.sha1("\x1f".join(nk_parts).encode()).hexdigest()[:16]
    return {
        "row_id": f"{nk}:0",
        "nk_hash": nk,
        "nk_ordinal": 0,
        "source_id": source_id,
        "source_kind": kind.value,
        "entity_id": entity_id,
        "row_kind": "payer_rate",
        "billing_npis": "",
        "code_type": code_type,
        "code": code,
        "modifiers": modifiers,
        "rev_code": "",
        "cdm_code": "",
        "description": description,
        "setting": "outpatient",
        "billing_class": "facility" if variant in ("opps", "asc") else "professional",
        "component": "facility" if variant in ("opps", "asc") else "professional",
        "component_rule": "none",
        "payer_raw": payer_raw,
        "plan_raw": variant,
        "place_of_service": variant if variant in ("non_facility", "facility") else None,
        "payer_id": payer_id,
        "line_of_business": lob,
        "product": "",
        "methodology": "fee_schedule",
        "methodology_raw": "fee schedule",
        "dollar_basis": "dollar",
        "negotiated_dollar": amount,
        "negotiated_pct": None,
        "negotiated_algorithm": algorithm,
        "amount": amount,
        "amount_method": "stated",
        "gross": None,
        "gross_rule": "none",
        "discounted_cash": None,
        "min_negotiated": None,
        "max_negotiated": None,
        "median_amount": None,
        "p10_amount": None,
        "p90_amount": None,
        "allowed_count": "",
        "above_gross": False,
        "ambiguous_multi_rate": False,
        "payer_plan_mismatch": False,
        "excluded": False,
        "exclude_reason": "",
        "additional_generic_notes": notes,
        "additional_payer_notes": "",
        "source_file": source_file,
        "source_sha256": sha,
        "source_date": source_date,
        "stage_row": line,
        "row_ref": f"{source_id}:{sha[:12]}:{line}:{variant}",
    }


def finish(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give same-key rows ordinals (never merge them) and validate every row against RateRow."""
    seen: dict[str, int] = {}
    refs: set[str] = set()
    out = []
    for r in rows:
        n = seen.get(r["nk_hash"], 0)
        seen[r["nk_hash"]] = n + 1
        r["nk_ordinal"] = n
        r["row_id"] = f"{r['nk_hash']}:{n}"
        if r["row_ref"] in refs:
            raise GovReadError(f"duplicate row_ref {r['row_ref']}")
        refs.add(r["row_ref"])
        out.append(RateRow(**r).model_dump(mode="python"))
    dup = {k for k, v in seen.items() if v > 1}
    for r in out:
        r["ambiguous_multi_rate"] = r["nk_hash"] in dup
    return out


def write_parquet(rows: list[dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(_arrowable(rows), RATE_ROW_SCHEMA)
    tmp = out.with_suffix(".parquet.partial")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(out)


def write_json(obj: Any, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".partial")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")
    tmp.replace(out)


def fee_schedule_money(row: RateRow | dict[str, Any]) -> Money:
    """The Money a fee-schedule RateRow renders as (until RateRow.to_cell knows fee schedules)."""
    r = row if isinstance(row, dict) else row.model_dump(mode="python")
    if r.get("amount") is None:
        raise ValueError(f"{r['row_ref']}: no amount")
    computed = r["source_kind"] == "medicare_pfs" and r["plan_raw"] in COMPUTED_VARIANTS
    prov = Provenance(
        source_id=r["source_id"],
        source_kind=SourceKind(r["source_kind"]),
        source_file=r["source_file"],
        source_sha256=r["source_sha256"],
        source_date=r["source_date"],
        method=Method.computed_fee_schedule if computed else Method.stated,
        row_ref=r["row_ref"],
        payer_id=None,
    )
    return Money.point(round(float(r["amount"]), 2), basis=PriceBasis.fee_schedule, prov=prov)
