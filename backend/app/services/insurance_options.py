"""Derive onboarding insurance dropdowns from normalized payer rates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.db.tables import HospitalPayerRate
from app.registries import all_payers

_payers = all_payers()

INSURER_LABELS: dict[str, str] = {p.slug: p.label for p in _payers.values()}
PAYER_ID_TO_SLUG: dict[str, str] = {pid: p.slug for pid, p in _payers.items()}


def build_insurance_options(db: Session) -> dict[str, Any]:
    insurers: list[dict[str, str]] = []

    available_payers = (
        db.query(distinct(HospitalPayerRate.payer_id))
        .filter(HospitalPayerRate.negotiated_rate > 0)
        .filter(HospitalPayerRate.source_origin == "mrf")
        .all()
    )
    slug_to_db_key: dict[str, str] = {}
    for (payer_id,) in available_payers:
        slug = PAYER_ID_TO_SLUG.get(payer_id)
        if not slug:
            continue
        label = INSURER_LABELS.get(slug, slug.replace("_", " ").title())
        insurers.append({"key": slug, "label": label, "payer_id": slug})
        slug_to_db_key[slug] = payer_id

    plan_options_by_insurer: dict[str, list[str]] = {}
    for ins in insurers:
        db_key = slug_to_db_key[ins["key"]]
        raw = [
            r[0]
            for r in db.query(distinct(HospitalPayerRate.plan_name))
            .filter(HospitalPayerRate.payer_id == db_key)
            .all()
        ]
        plan_options_by_insurer[ins["key"]] = sorted(
            {str(p).strip() for p in raw if p is not None and str(p).strip()}
        )

    bcbs_plans = plan_options_by_insurer.get("bcbs", [])
    return {
        "insurers": insurers,
        "bcbs_plan_options": bcbs_plans,
        "plan_options_by_insurer": plan_options_by_insurer,
    }
