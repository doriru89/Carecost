"""Hospital use-cases extracted from route layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.tables import HospitalProcedure, Provider
from app.registries import all_hospitals
from app.services.hospital_legacy import flatten_to_legacy
from app.services.hospital_query import query_hospitals_normalized
from app.services.insurance_options import build_insurance_options

_PAYMENT_TABLE_PATH = Path(__file__).resolve().parents[5] / "data" / "seed" / "plan_payment_table.json"
_PAYMENT_TABLE: list[dict[str, Any]] = []
if _PAYMENT_TABLE_PATH.exists():
    _PAYMENT_TABLE = json.loads(_PAYMENT_TABLE_PATH.read_text())

_HOSPITAL_INFO: dict[str, dict[str, Any]] = {
    h.name: {"id": hid, "lat": h.lat, "lng": h.lng}
    for hid, h in all_hospitals().items()
}


def get_insurance_options(db: Session) -> dict[str, Any]:
    return build_insurance_options(db)


def list_hospitals(db: Session, *, cpt: str, specialty: str | None) -> list[dict[str, Any]]:
    q = db.query(Provider.hospital, func.count(Provider.npi).label("cnt")).filter(
        Provider.hospital != "",
        Provider.hospital.isnot(None),
    )
    if specialty:
        q = q.filter(Provider.specialties.contains([specialty]))
    counts = {row.hospital: row.cnt for row in q.group_by(Provider.hospital).all()}

    normalized = query_hospitals_normalized(db, cpt)
    normalized_by_hid = {h["hospital_id"]: h for h in normalized}

    all_hospital_names: set[str] = set(counts.keys())
    for name, info in _HOSPITAL_INFO.items():
        hid = info.get("id")
        if hid and hid in normalized_by_hid:
            all_hospital_names.add(name)

    results = []
    for name in all_hospital_names:
        info = _HOSPITAL_INFO.get(name, {})
        lat = info.get("lat")
        lng = info.get("lng")
        if lat is None or lng is None:
            continue
        hid = info.get("id")
        norm = normalized_by_hid.get(hid) if hid else None
        d = flatten_to_legacy(norm) if norm else _empty_legacy(cpt)
        d["name"] = name
        d["hospital_id"] = hid
        d["lat"] = lat
        d["lng"] = lng
        d["doctor_count"] = counts.get(name, 0)
        results.append(d)
    results.sort(key=lambda x: x["doctor_count"], reverse=True)
    return results


def _empty_legacy(cpt: str) -> dict[str, Any]:
    """Default dict for hospitals with no pricing data."""
    return {
        "cpt": cpt, "cpt_desc": "", "gross_charge": None,
        "discounted_cash": None, "de_identified_min": None,
        "de_identified_max": None, "billing_class": "unknown",
        "setting": "", "rate_methodology": "",
        "bcbs_price": None, "bcbs_source": "", "bcbs_plan": "",
        "aetna_price": None, "aetna_source": "",
        "harvard_pilgrim_price": None, "hp_plan_name": "", "hp_source": "",
        "uhc_price": None, "uhc_source": "",
        "bcbs_tic_rate": None, "bcbs_tic_billing_class": "",
        "turquoise_bundled_price": None, "turquoise_quality_rating": None,
        "masscomparecare_total_paid": None,
        "fh_physician_in_network": None, "fh_anesthesia_in_network": None,
        "fh_facility_hosp_in_network": None, "fh_pathology_in_network": None,
    }


def list_specialties(db: Session) -> list[dict[str, Any]]:
    rows = db.query(HospitalProcedure.cpt, HospitalProcedure.cpt_desc).distinct().all()
    gi_cpts = []
    derm_cpts = []
    for cpt, desc in rows:
        desc_lower = (desc or "").lower()
        if any(kw in desc_lower for kw in ["colon", "egd", "esophago", "gastro", "capsule", "gi "]):
            gi_cpts.append({"cpt": cpt, "desc": desc})
        elif any(kw in desc_lower for kw in ["skin", "derm", "biopsy", "destruction", "excision"]):
            derm_cpts.append({"cpt": cpt, "desc": desc})
        else:
            gi_cpts.append({"cpt": cpt, "desc": desc})
    return [
        {"id": "gi", "label": "Gastroenterology", "procedures": gi_cpts},
        {"id": "derm", "label": "Dermatology", "procedures": derm_cpts},
    ]


def get_payment_table(
    *,
    plan_id: str | None,
    cpt: str | None,
    hospital_id: str | None,
    scenario_id: str | None,
    specialty: str | None,
) -> list[dict[str, Any]]:
    results = _PAYMENT_TABLE
    if plan_id:
        results = [r for r in results if r["plan_id"] == plan_id]
    if cpt:
        results = [r for r in results if r["cpt"] == cpt]
    if hospital_id:
        results = [r for r in results if r["hospital_id"] == hospital_id]
    if scenario_id:
        results = [r for r in results if r["scenario_id"] == scenario_id]
    if specialty:
        results = [r for r in results if r["specialty"].lower() == specialty.lower()]
    return results
