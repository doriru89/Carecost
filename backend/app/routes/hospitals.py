"""Hospitals API — normalized shape with dimension enrichment."""

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbDep
from app.modules.hospitals.application.use_cases import (
    get_insurance_options as get_insurance_options_use_case,
    get_payment_table as get_payment_table_use_case,
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
) -> list[dict[str, Any]]:
    return list_hospitals_use_case(db, cpt=cpt, specialty=specialty, metro_area=metro_area)


@router.get("/specialties")
def list_specialties(db: DbDep) -> list[dict[str, Any]]:
    return list_specialties_use_case(db)


@router.get("/payment-table")
def get_payment_table(
    plan_id: str | None = Query(None),
    cpt: str | None = Query(None),
    hospital_id: str | None = Query(None),
    scenario_id: str | None = Query(None),
    specialty: str | None = Query(None),
) -> list[dict[str, Any]]:
    return get_payment_table_use_case(
        plan_id=plan_id,
        cpt=cpt,
        hospital_id=hospital_id,
        scenario_id=scenario_id,
        specialty=specialty,
    )
