"""Pivot wide HospitalRate rows into 3 normalized tables.

One-time migration: reads the legacy wide table and populates
HospitalProcedure, HospitalPayerRate, and HospitalBenchmark.
Idempotent via ON CONFLICT DO UPDATE.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.tables import HospitalBenchmark, HospitalPayerRate, HospitalProcedure, HospitalRate
from app.etl.column_map import FH_COMPONENT_MAP, PAYER_RATE_MAP


def migrate_wide_to_normalized(db: Session) -> dict[str, int]:
    wide_rows = db.query(HospitalRate).all()
    if not wide_rows:
        return {"procedures": 0, "payer_rates": 0, "benchmarks": 0}

    procedures: list[dict] = []
    payer_rates: list[dict] = []
    benchmarks: list[dict] = []

    for row in wide_rows:
        procedures.append({
            "id": f"{row.hospital_id}:{row.cpt}",
            "hospital_id": row.hospital_id,
            "cpt": row.cpt,
            "cpt_desc": row.cpt_desc,
            "gross_charge": row.gross_charge,
            "discounted_cash": row.discounted_cash,
            "de_identified_min": row.de_identified_min,
            "de_identified_max": row.de_identified_max,
            "billing_class": row.billing_class,
            "setting": row.setting,
            "rate_methodology": row.rate_methodology,
            "data_completeness": row.data_completeness,
            "compliance_score": "unknown",
            "price_granularity": "itemized",
            "source": row.source,
            "source_type": row.source_type,
            "rate_quality": row.rate_quality,
        })

        for payer_id, (price_col, source_col, plan_col) in PAYER_RATE_MAP.items():
            price = getattr(row, price_col, None)
            if price is None:
                continue
            source_val = getattr(row, source_col, "")
            plan_val = getattr(row, plan_col, "") if plan_col != source_col else source_val
            payer_rates.append({
                "hospital_id": row.hospital_id,
                "cpt": row.cpt,
                "payer_id": payer_id,
                "negotiated_rate": price,
                "plan_name": plan_val or "",
                "source": source_val or "",
                "source_origin": "mrf",
                "billing_class": row.billing_class,
                "price_source": "seed",
            })

        if row.bcbs_tic_rate is not None:
            payer_rates.append({
                "hospital_id": row.hospital_id,
                "cpt": row.cpt,
                "payer_id": "BCBS_MA",
                "negotiated_rate": row.bcbs_tic_rate,
                "plan_name": "",
                "source": "",
                "source_origin": "tic",
                "billing_class": row.bcbs_tic_billing_class or "",
                "price_source": "seed",
            })

        if row.turquoise_bundled_price is not None:
            benchmarks.append({
                "hospital_id": row.hospital_id,
                "cpt": row.cpt,
                "benchmark_source": "turquoise",
                "component": "total",
                "price": row.turquoise_bundled_price,
                "quality_rating": row.turquoise_quality_rating,
            })

        if row.masscomparecare_total_paid is not None:
            benchmarks.append({
                "hospital_id": row.hospital_id,
                "cpt": row.cpt,
                "benchmark_source": "masscomparecare",
                "component": "total",
                "price": row.masscomparecare_total_paid,
                "quality_rating": None,
            })

        for component, wide_col in FH_COMPONENT_MAP.items():
            price = getattr(row, wide_col, None)
            if price is None:
                continue
            benchmarks.append({
                "hospital_id": row.hospital_id,
                "cpt": row.cpt,
                "benchmark_source": "fair_health",
                "component": component,
                "price": price,
                "quality_rating": None,
            })

    counts = {
        "procedures": _upsert_normalized(db, HospitalProcedure, procedures, "uq_hospital_procedures_hid_cpt"),
        "payer_rates": _upsert_normalized(db, HospitalPayerRate, payer_rates, "uq_hospital_payer_rates_natural_key"),
        "benchmarks": _upsert_normalized(db, HospitalBenchmark, benchmarks, "uq_hospital_benchmarks_natural_key"),
    }
    return counts


def _upsert_normalized(db: Session, model: type, rows: list[dict], constraint: str) -> int:
    if not rows:
        return 0
    table = model.__table__
    pk_cols = {c.name for c in table.primary_key.columns}
    update_cols = [c.name for c in table.columns if c.name not in pk_cols]
    stmt = pg_insert(table).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint=constraint,
        set_={col: stmt.excluded[col] for col in update_cols},
    )
    db.execute(stmt)
    db.flush()
    return len(rows)
