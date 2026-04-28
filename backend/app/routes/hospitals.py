"""Hospital-level summary: coordinates, multi-source pricing with provenance."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.api.deps import DbDep
from app.db.tables import HospitalRate, Provider
from app.services.insurance_options import build_insurance_options

router = APIRouter()

_PAYMENT_TABLE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "az-data"
    / "plan_payment_table.json"
)
_PAYMENT_TABLE: list[dict[str, Any]] = []
if _PAYMENT_TABLE_PATH.exists():
    _PAYMENT_TABLE = json.loads(_PAYMENT_TABLE_PATH.read_text())

_HOSPITAL_INFO: dict[str, dict[str, Any]] = {
    "Massachusetts General Hospital": {"id": "mgh", "lat": 42.3632, "lng": -71.0686},
    "Brigham and Women's Hospital": {"id": "brigham", "lat": 42.3358, "lng": -71.1065},
    "Beth Israel Deaconess Medical Center": {"id": "bidmc", "lat": 42.3389, "lng": -71.1063},
    "Boston Medical Center": {"id": "bmc", "lat": 42.3346, "lng": -71.0721},
    "Tufts Medical Center": {"id": "tufts", "lat": 42.3495, "lng": -71.0636},
    "Brigham and Women's Faulkner": {"id": "faulkner", "lat": 42.3082, "lng": -71.1271},
    "Boston Children's Hospital": {"id": "childrens", "lat": 42.3375, "lng": -71.1064},
    "Dana-Farber Cancer Institute": {"id": "dana_farber", "lat": 42.3382, "lng": -71.1068},
    "BMC Brighton (Formerly St. Elizabeth's)": {
        "id": "bmc_brighton",
        "lat": 42.3545,
        "lng": -71.1525,
    },
    "Mount Auburn Hospital": {"id": "mtauburn", "lat": 42.3738, "lng": -71.1284},
    "CHA Cambridge Hospital": {"id": "cha", "lat": 42.3667, "lng": -71.1050},
    "Franciscan Childrens": {"id": "franciscan", "lat": 42.3540, "lng": -71.1530},
}


@router.get("/insurance-options")
def get_insurance_options(db: DbDep) -> dict[str, Any]:
    return build_insurance_options(db)


@router.get("")
def list_hospitals(
    db: DbDep,
    cpt: str = Query("45378", description="CPT code for pricing"),
    specialty: str | None = Query(None, description="Filter providers by specialty"),
) -> list[dict[str, Any]]:
    """Return one entry per hospital with coordinates and all price sources."""
    # Count doctors per hospital
    q = db.query(Provider.hospital, func.count(Provider.npi).label("cnt")).filter(
        Provider.hospital != "",
        Provider.hospital.isnot(None),
    )
    if specialty:
        q = q.filter(Provider.specialties.contains([specialty]))
    counts = {row.hospital: row.cnt for row in q.group_by(Provider.hospital).all()}

    # Get pricing for requested CPT
    rates_by_id: dict[str, HospitalRate] = {}
    for rate in db.query(HospitalRate).filter(HospitalRate.cpt == cpt).all():
        rates_by_id[rate.hospital_id] = rate

    all_hospital_names: set[str] = set(counts.keys())
    for name, info in _HOSPITAL_INFO.items():
        hid = info.get("id")
        if hid and hid in rates_by_id:
            all_hospital_names.add(name)

    results = []
    for name in all_hospital_names:
        info = _HOSPITAL_INFO.get(name, {})
        lat = info.get("lat")
        lng = info.get("lng")
        if lat is None or lng is None:
            continue
        hid = info.get("id")
        rate = rates_by_id.get(hid) if hid else None
        count = counts.get(name, 0)
        results.append(
            {
                "name": name,
                "hospital_id": hid,
                "lat": lat,
                "lng": lng,
                "doctor_count": count,
                "bcbs_price": rate.bcbs_price if rate else None,
                "bcbs_source": rate.bcbs_source if rate else "",
                "bcbs_plan": rate.bcbs_plan if rate else "",
                "aetna_price": rate.aetna_price if rate else None,
                "aetna_source": rate.aetna_source if rate else "",
                "harvard_pilgrim_price": rate.harvard_pilgrim_price if rate else None,
                "hp_plan_name": rate.hp_plan_name if rate else "",
                "hp_source": rate.hp_source if rate else "",
                "uhc_price": rate.uhc_price if rate else None,
                "uhc_source": rate.uhc_source if rate else "",
                "de_identified_min": rate.de_identified_min if rate else None,
                "de_identified_max": rate.de_identified_max if rate else None,
                "gross_charge": rate.gross_charge if rate else None,
                "discounted_cash": rate.discounted_cash if rate else None,
                "bcbs_tic_rate": rate.bcbs_tic_rate if rate else None,
                "bcbs_tic_billing_class": rate.bcbs_tic_billing_class if rate else "",
                "billing_class": rate.billing_class if rate else "unknown",
                "setting": rate.setting if rate else "",
                "rate_methodology": rate.rate_methodology if rate else "",
                "turquoise_bundled_price": rate.turquoise_bundled_price if rate else None,
                "turquoise_quality_rating": rate.turquoise_quality_rating if rate else None,
                "masscomparecare_total_paid": rate.masscomparecare_total_paid if rate else None,
                "fh_physician_in_network": rate.fh_physician_in_network if rate else None,
                "fh_anesthesia_in_network": rate.fh_anesthesia_in_network if rate else None,
                "fh_facility_hosp_in_network": rate.fh_facility_hosp_in_network if rate else None,
                "fh_pathology_in_network": rate.fh_pathology_in_network if rate else None,
                "cpt": cpt,
                "cpt_desc": rate.cpt_desc if rate else "",
            }
        )

    results.sort(key=lambda x: x["doctor_count"], reverse=True)
    return results


@router.get("/specialties")
def list_specialties(db: DbDep) -> list[dict[str, Any]]:
    """Available specialties with their CPT codes."""
    rows = db.query(HospitalRate.cpt, HospitalRate.cpt_desc).distinct().all()
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


@router.get("/payment-table")
def get_payment_table(
    plan_id: str | None = Query(None),
    cpt: str | None = Query(None),
    hospital_id: str | None = Query(None),
    scenario_id: str | None = Query(None),
    specialty: str | None = Query(None),
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
