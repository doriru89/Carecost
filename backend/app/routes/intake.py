from fastapi import APIRouter

from app.api.deps import DbDep
from app.models.api import IntakeRequest, IntakeResponse
from app.modules.assistant.application.use_cases import run_intake

router = APIRouter()


@router.post("", response_model=IntakeResponse)
def post_intake(body: IntakeRequest, db: DbDep) -> IntakeResponse:
    _ = db  # reserved for session persistence
    raw = body.model_dump(exclude_none=True)
    normalized, missing = run_intake(raw)
    return IntakeResponse(normalized=normalized, missing_required=missing)
