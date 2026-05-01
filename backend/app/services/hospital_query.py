"""Query normalized hospital tables — production API shape."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.tables import HospitalBenchmark, HospitalPayerRate, HospitalProcedure


def query_hospitals_normalized(db: Session, cpt: str) -> list[dict[str, Any]]:
    """Return hospital pricing data from normalized tables.

    Each result contains base procedure facts, a list of payer rates,
    and a list of benchmarks. This is the natural normalized shape —
    no wide-format column pivoting.
    """
    procs = db.query(HospitalProcedure).filter(HospitalProcedure.cpt == cpt).all()
    if not procs:
        return []

    hospital_ids = [p.hospital_id for p in procs]

    rates_raw = (
        db.query(HospitalPayerRate)
        .filter(HospitalPayerRate.cpt == cpt, HospitalPayerRate.hospital_id.in_(hospital_ids))
        .all()
    )
    rates_by_hid: dict[str, list[HospitalPayerRate]] = {}
    for r in rates_raw:
        rates_by_hid.setdefault(r.hospital_id, []).append(r)

    bm_raw = (
        db.query(HospitalBenchmark)
        .filter(HospitalBenchmark.cpt == cpt, HospitalBenchmark.hospital_id.in_(hospital_ids))
        .all()
    )
    bm_by_hid: dict[str, list[HospitalBenchmark]] = {}
    for b in bm_raw:
        bm_by_hid.setdefault(b.hospital_id, []).append(b)

    results = []
    for proc in procs:
        hid = proc.hospital_id
        results.append({
            "hospital_id": hid,
            "cpt": proc.cpt,
            "cpt_desc": proc.cpt_desc,
            "gross_charge": proc.gross_charge,
            "discounted_cash": proc.discounted_cash,
            "de_identified_min": proc.de_identified_min,
            "de_identified_max": proc.de_identified_max,
            "billing_class": proc.billing_class,
            "setting": proc.setting,
            "rate_methodology": proc.rate_methodology,
            "payer_rates": [
                {
                    "payer_id": r.payer_id,
                    "negotiated_rate": r.negotiated_rate,
                    "plan_name": r.plan_name,
                    "source": r.source,
                    "source_origin": r.source_origin,
                    "billing_class": r.billing_class,
                }
                for r in rates_by_hid.get(hid, [])
            ],
            "benchmarks": [
                {
                    "benchmark_source": b.benchmark_source,
                    "component": b.component,
                    "price": b.price,
                    "quality_rating": b.quality_rating,
                }
                for b in bm_by_hid.get(hid, [])
            ],
        })

    return results
