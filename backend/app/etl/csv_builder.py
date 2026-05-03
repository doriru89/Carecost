"""Write ETL output to CSV files.

Produces 3 normalized CSVs + 1 legacy wide CSV for backward compatibility.
All monetary values rounded to 2 decimal places. None → empty string.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import Any

from app.etl.types import MergeResult

PROCEDURE_COLUMNS = (
    "hospital_id",
    "cpt",
    "cpt_desc",
    "gross_charge",
    "discounted_cash",
    "de_identified_min",
    "de_identified_max",
    "billing_class",
    "setting",
    "rate_methodology",
    "data_completeness",
    "compliance_score",
    "price_granularity",
    "null_reason",
    "source_type",
    "rate_quality",
)

PAYER_RATE_COLUMNS = (
    "hospital_id",
    "cpt",
    "payer_id",
    "negotiated_rate",
    "plan_name",
    "source",
    "source_origin",
    "billing_class",
    "price_source",
    "setting",
    "source_file",
    "rate_methodology",
)

BENCHMARK_COLUMNS = (
    "hospital_id",
    "cpt",
    "benchmark_source",
    "component",
    "price",
    "quality_rating",
)

_MONETARY_FIELDS = {
    "gross_charge",
    "discounted_cash",
    "de_identified_min",
    "de_identified_max",
    "negotiated_rate",
    "price",
    "quality_rating",
}


def _fmt(val: str | float | None, col: str) -> str:
    if val is None:
        return ""
    if col in _MONETARY_FIELDS and isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


def _write_csv(path: Path, columns: tuple[str, ...], records: list[Any], sort_key: Any) -> int:
    sorted_recs = sorted(records, key=sort_key)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(list(columns))
        for rec in sorted_recs:
            d = dataclasses.asdict(rec)
            writer.writerow([_fmt(d.get(c), c) for c in columns])
    return len(sorted_recs)


def build_csvs(result: MergeResult, output_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["hospital_procedures.csv"] = _write_csv(
        output_dir / "hospital_procedures.csv",
        PROCEDURE_COLUMNS,
        result.procedures,
        lambda r: (r.hospital_id, r.cpt),
    )
    counts["hospital_payer_rates.csv"] = _write_csv(
        output_dir / "hospital_payer_rates.csv",
        PAYER_RATE_COLUMNS,
        result.payer_rates,
        lambda r: (r.hospital_id, r.cpt, r.payer_id),
    )
    counts["hospital_benchmarks.csv"] = _write_csv(
        output_dir / "hospital_benchmarks.csv",
        BENCHMARK_COLUMNS,
        result.benchmarks,
        lambda r: (r.hospital_id, r.cpt, r.benchmark_source),
    )
    return counts
