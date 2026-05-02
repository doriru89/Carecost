"""Query normalized hospital tables — production API shape."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.tables import Hospital, HospitalBenchmark, HospitalPayerRate, HospitalProcedure
from app.services.insurance_options import PAYER_ID_TO_SLUG

logger = logging.getLogger(__name__)


def query_hospitals(
    db: Session, cpt: str, *, metro_area: str | None = None
) -> list[dict[str, Any]]:
    """Normalized hospital data with dimension enrichment.

    JOINs Hospital dimension for lat, lng, metro_area, system_name, neighborhood.
    Filters by metro_area when provided.
    Excludes seed-era payer_rates (source_file = '').
    Skips hospitals missing from dimension table (logs warning).
    """
    procs = db.query(HospitalProcedure).filter(HospitalProcedure.cpt == cpt).all()
    if not procs:
        return []

    hospital_ids = [p.hospital_id for p in procs]

    hospitals_dim = {
        h.hospital_id: h
        for h in db.query(Hospital).filter(Hospital.hospital_id.in_(hospital_ids)).all()
    }

    if metro_area:
        hospitals_dim = {
            hid: h for hid, h in hospitals_dim.items() if h.metro_area == metro_area
        }

    rates_raw = (
        db.query(HospitalPayerRate)
        .filter(
            HospitalPayerRate.cpt == cpt,
            HospitalPayerRate.hospital_id.in_(list(hospitals_dim.keys())),
            HospitalPayerRate.source_file != "",
        )
        .all()
    )
    rates_by_hid: dict[str, list[HospitalPayerRate]] = {}
    for r in rates_raw:
        rates_by_hid.setdefault(r.hospital_id, []).append(r)

    bm_raw = (
        db.query(HospitalBenchmark)
        .filter(
            HospitalBenchmark.cpt == cpt,
            HospitalBenchmark.hospital_id.in_(list(hospitals_dim.keys())),
        )
        .all()
    )
    bm_by_hid: dict[str, list[HospitalBenchmark]] = {}
    for b in bm_raw:
        bm_by_hid.setdefault(b.hospital_id, []).append(b)

    results = []
    for proc in procs:
        hid = proc.hospital_id
        hosp = hospitals_dim.get(hid)
        if not hosp:
            logger.warning("Hospital %s in procedures but missing from dimension table", hid)
            continue

        results.append({
            "hospital_id": hid,
            "name": hosp.name,
            "system_name": hosp.system_name,
            "metro_area": hosp.metro_area,
            "neighborhood": hosp.neighborhood,
            "lat": hosp.lat,
            "lng": hosp.lng,
            "cpt": proc.cpt,
            "cpt_desc": proc.cpt_desc,
            "gross_charge": proc.gross_charge,
            "discounted_cash": proc.discounted_cash,
            "de_identified_min": proc.de_identified_min,
            "de_identified_max": proc.de_identified_max,
            "payer_rates": [
                {
                    "payer_id": PAYER_ID_TO_SLUG.get(r.payer_id, r.payer_id.lower()),
                    "negotiated_rate": r.negotiated_rate,
                    "plan_name": r.plan_name,
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
