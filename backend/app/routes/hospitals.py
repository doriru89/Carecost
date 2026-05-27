"""Hospitals API — normalized shape with dimension enrichment."""

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbDep
from app.modules.hospitals.application.use_cases import (
    get_insurance_options as get_insurance_options_use_case,
    list_hospitals as list_hospitals_use_case,
    list_specialties as list_specialties_use_case,
)

router = APIRouter()


@router.get("/insurance-options")
def get_insurance_options(db: DbDep) -> dict[str, Any]:
    return get_insurance_options_use_case(db)


@router.get("")
def list_hospitals(
    db: DbDep,
    cpt: str = Query(..., description="CPT code for pricing"),
    specialty: str | None = Query(None, description="Filter providers by specialty"),
    metro_area: str | None = Query(None, description="Filter by metro area"),
    include_government: bool = Query(False, description="Include Medicare/Medicaid rates"),
) -> list[dict[str, Any]]:
    return list_hospitals_use_case(
        db, cpt=cpt, specialty=specialty, metro_area=metro_area, include_government=include_government,
    )


@router.get("/specialties")
def list_specialties(db: DbDep) -> list[dict[str, Any]]:
    return list_specialties_use_case(db)
