"""Derive onboarding insurance dropdowns from hospital_rates (PostgreSQL)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.db.tables import HospitalRate
from app.registries import all_payers

_payers = all_payers()

INSURER_LABELS: dict[str, str] = {p.slug: p.label for p in _payers.values()}

PRICE_COLUMNS: tuple[tuple[str, str], ...] = tuple(
    (p.price_column, p.slug) for p in _payers.values()
)

PLAN_FIELD_BY_INSURER_KEY: dict[str, str] = {p.slug: p.plan_column for p in _payers.values()}


def build_insurance_options(db: Session) -> dict[str, Any]:
    insurers: list[dict[str, str]] = []
    for col_name, key in PRICE_COLUMNS:
        col_attr = getattr(HospitalRate, col_name)
        has_rate = db.query(HospitalRate).filter(col_attr > 0).first()
        if not has_rate:
            continue
        label = INSURER_LABELS.get(key, key.replace("_", " ").title())
        insurers.append({"key": key, "label": label, "price_column": col_name})

    plan_options_by_insurer: dict[str, list[str]] = {}
    for ins in insurers:
        key = ins["key"]
        field = PLAN_FIELD_BY_INSURER_KEY.get(key)
        if not field:
            continue
        col_attr = getattr(HospitalRate, field, None)
        if col_attr is None:
            continue
        raw = [r[0] for r in db.query(distinct(col_attr)).all()]
        plan_options_by_insurer[key] = sorted(
            {str(p).strip() for p in raw if p is not None and str(p).strip()}
        )

    bcbs_plans = plan_options_by_insurer.get("bcbs", [])
    return {
        "insurers": insurers,
        "bcbs_plan_options": bcbs_plans,
        "plan_options_by_insurer": plan_options_by_insurer,
    }
