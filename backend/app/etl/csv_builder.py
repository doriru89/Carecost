"""Write ETL output to CSV files.

Produces 3 normalized CSVs + 1 legacy wide CSV for backward compatibility.
All monetary values rounded to 2 decimal places. None → empty string.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import Any

from app.etl.column_map import FH_COMPONENT_MAP, PAYER_RATE_MAP
from app.etl.types import MergeResult

PROCEDURE_COLUMNS = (
    "hospital_id", "cpt", "cpt_desc", "gross_charge", "discounted_cash",
    "de_identified_min", "de_identified_max", "billing_class", "setting",
    "rate_methodology", "data_completeness", "compliance_score",
    "price_granularity", "null_reason", "source_type", "rate_quality",
)

PAYER_RATE_COLUMNS = (
    "hospital_id", "cpt", "payer_id", "negotiated_rate", "plan_name",
    "source", "source_origin", "billing_class", "price_source",
    "setting", "source_file", "rate_methodology",
)

BENCHMARK_COLUMNS = (
    "hospital_id", "cpt", "benchmark_source", "component", "price",
    "quality_rating",
)

LEGACY_WIDE_COLUMNS = (
    "hospital_id", "hospital_name", "neighborhood", "system",
    "data_completeness", "cpt", "cpt_desc", "gross_charge",
    "discounted_cash", "de_identified_min", "de_identified_max",
    "bcbs_price", "bcbs_source", "bcbs_plan", "aetna_price",
    "aetna_source", "harvard_pilgrim_price", "hp_plan_name",
    "hp_source", "uhc_price", "uhc_source", "bcbs_tic_rate",
    "bcbs_tic_billing_class", "billing_class", "setting",
    "rate_methodology", "turquoise_bundled_price",
    "turquoise_quality_rating", "masscomparecare_total_paid",
    "fh_physician_in_network", "fh_physician_oon",
    "fh_anesthesia_in_network", "fh_facility_hosp_in_network",
    "fh_facility_asc_in_network", "fh_pathology_in_network",
)

_MONETARY_FIELDS = {
    "gross_charge", "discounted_cash", "de_identified_min", "de_identified_max",
    "negotiated_rate", "price", "quality_rating",
    "bcbs_price", "aetna_price", "harvard_pilgrim_price", "uhc_price",
    "bcbs_tic_rate", "turquoise_bundled_price", "turquoise_quality_rating",
    "masscomparecare_total_paid", "fh_physician_in_network", "fh_physician_oon",
    "fh_anesthesia_in_network", "fh_facility_hosp_in_network",
    "fh_facility_asc_in_network", "fh_pathology_in_network",
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
        PROCEDURE_COLUMNS, result.procedures,
        lambda r: (r.hospital_id, r.cpt),
    )
    counts["hospital_payer_rates.csv"] = _write_csv(
        output_dir / "hospital_payer_rates.csv",
        PAYER_RATE_COLUMNS, result.payer_rates,
        lambda r: (r.hospital_id, r.cpt, r.payer_id),
    )
    counts["hospital_benchmarks.csv"] = _write_csv(
        output_dir / "hospital_benchmarks.csv",
        BENCHMARK_COLUMNS, result.benchmarks,
        lambda r: (r.hospital_id, r.cpt, r.benchmark_source),
    )
    return counts


def build_legacy_wide_csv(result: MergeResult, output_path: Path) -> int:
    from app.registries import get_hospital

    proc_map: dict[tuple[str, str], dict[str, str | float | None]] = {}
    for proc in result.procedures:
        key = (proc.hospital_id, proc.cpt)
        try:
            h = get_hospital(proc.hospital_id)
            hosp_name, neighborhood, system = h.name, h.neighborhood, h.system
        except KeyError:
            hosp_name, neighborhood, system = "", "", ""
        row: dict[str, str | float | None] = {c: "" for c in LEGACY_WIDE_COLUMNS}
        row.update({
            "hospital_id": proc.hospital_id,
            "hospital_name": hosp_name,
            "neighborhood": neighborhood,
            "system": system,
            "data_completeness": proc.data_completeness,
            "cpt": proc.cpt,
            "cpt_desc": proc.cpt_desc,
            "gross_charge": proc.gross_charge,
            "discounted_cash": proc.discounted_cash,
            "de_identified_min": proc.de_identified_min,
            "de_identified_max": proc.de_identified_max,
            "billing_class": proc.billing_class,
            "setting": proc.setting,
            "rate_methodology": proc.rate_methodology,
        })
        proc_map[key] = row

    for pr in result.payer_rates:
        key = (pr.hospital_id, pr.cpt)
        pr_row = proc_map.get(key)
        if not pr_row:
            continue
        mapping = PAYER_RATE_MAP.get(pr.payer_id)
        if not mapping:
            continue
        price_col, source_col, plan_col = mapping
        if pr.source_origin == "tic" and pr.payer_id == "BCBS_MA":
            pr_row["bcbs_tic_rate"] = pr.negotiated_rate
            pr_row["bcbs_tic_billing_class"] = pr.billing_class
        else:
            pr_row[price_col] = pr.negotiated_rate
            pr_row[source_col] = pr.source
            pr_row[plan_col] = pr.plan_name

    for bm in result.benchmarks:
        key = (bm.hospital_id, bm.cpt)
        bm_row = proc_map.get(key)
        if not bm_row:
            continue
        if bm.benchmark_source == "turquoise":
            bm_row["turquoise_bundled_price"] = bm.price
            bm_row["turquoise_quality_rating"] = bm.quality_rating
        elif bm.benchmark_source == "masscomparecare":
            bm_row["masscomparecare_total_paid"] = bm.price
        elif bm.benchmark_source == "fair_health":
            col = FH_COMPONENT_MAP.get(bm.component)
            if col:
                bm_row[col] = bm.price

    sorted_rows = sorted(proc_map.values(), key=lambda r: (r["hospital_id"], r["cpt"]))
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(list(LEGACY_WIDE_COLUMNS))
        for row in sorted_rows:
            writer.writerow([_fmt(row.get(c), c) for c in LEGACY_WIDE_COLUMNS])
    return len(sorted_rows)
