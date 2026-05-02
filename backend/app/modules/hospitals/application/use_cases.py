"""Hospital use-cases extracted from route layer."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.tables import Provider
from app.services.hospital_query import query_hospitals
from app.services.insurance_options import build_insurance_options


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


