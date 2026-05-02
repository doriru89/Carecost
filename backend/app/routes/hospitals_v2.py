"""V2 hospitals API — normalized shape with dimension enrichment."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.modules.hospitals.application.use_cases import (
    get_insurance_options,
    list_hospitals_v2,
    list_specialties,
)
from app.api.deps import DbDep

router = APIRouter()


@router.get("/hospitals")
def get_hospitals_v2(
    db: DbDep,
    cpt: str = Query(..., description="CPT code for pricing"),
    specialty: str | None = Query(None, description="Specialty for provider counts"),
    metro_area: str | None = Query(None, description="Filter by metro area"),
) -> list[dict[str, Any]]:
    return list_hospitals_v2(db, cpt=cpt, specialty=specialty, metro_area=metro_area)


@router.get("/hospitals/specialties")
def get_specialties_v2(db: DbDep) -> list[dict[str, Any]]:
    return list_specialties(db)


@router.get("/hospitals/insurance-options")
def get_insurance_options_v2(db: DbDep) -> dict[str, Any]:
    return get_insurance_options(db)
