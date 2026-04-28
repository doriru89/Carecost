from fastapi import APIRouter

from app.api.deps import DbDep
from app.models.api import IntakeRequest, IntakeResponse
from app.services.intake import validate_intake_payload

router = APIRouter()


@router.post("", response_model=IntakeResponse)
def post_intake(body: IntakeRequest, db: DbDep) -> IntakeResponse:
    _ = db  # reserved for session persistence
    raw = body.model_dump(exclude_none=True)
    normalized, missing = validate_intake_payload(raw)
    return IntakeResponse(normalized=normalized, missing_required=missing)
