from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.api import EstimateResponse
from app.services.estimate_service import build_estimate_response


def estimate_from_intake(
    db: Session,
    *,
    intake: dict[str, Any],
    confirmed: dict[str, Any] | None,
    bundle_id: str | None,
    scenario_id: str | None,
) -> EstimateResponse:
    return build_estimate_response(db, intake, confirmed, bundle_id, scenario_id)
