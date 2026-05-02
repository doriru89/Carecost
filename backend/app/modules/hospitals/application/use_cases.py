"""Hospital use-cases extracted from route layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.tables import Provider
from app.services.hospital_query import query_hospitals
from app.services.insurance_options import build_insurance_options

_PAYMENT_TABLE_PATH = Path(__file__).resolve().parents[5] / "data" / "seed" / "plan_payment_table.json"
_PAYMENT_TABLE: list[dict[str, Any]] = []
if _PAYMENT_TABLE_PATH.exists():
    _PAYMENT_TABLE = json.loads(_PAYMENT_TABLE_PATH.read_text())


def get_insurance_options(db: Session) -> dict[str, Any]:
    return build_insurance_options(db)


def list_hospitals(
    db: Session, *, cpt: str, specialty: str | None = None, metro_area: str | None = None
) -> list[dict[str, Any]]:
    hospitals = query_hospitals(db, cpt, metro_area=metro_area)
    counts = _provider_counts(db, specialty)
    for h in hospitals:
        h["doctor_count"] = counts.get(h["name"], 0)
    return hospitals


def _provider_counts(db: Session, specialty: str | None) -> dict[str, int]:
    q = db.query(Provider.hospital, func.count(Provider.npi).label("cnt")).filter(
        Provider.hospital != "",
        Provider.hospital.isnot(None),
    )
    if specialty:
        q = q.filter(Provider.specialties.contains([specialty]))
    return {row.hospital: row.cnt for row in q.group_by(Provider.hospital).all()}


def list_specialties(db: Session) -> list[dict[str, Any]]:
    from app.registries import all_specialty_names, bundles_for_specialty

    return [
        {
            "id": name.lower().replace(" ", "_"),
            "label": name,
            "procedures": [
                {"cpt": b.cpt, "desc": b.label, "bundle_id": bid}
                for bid, b in bundles_for_specialty(name).items()
            ],
        }
        for name in all_specialty_names()
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
