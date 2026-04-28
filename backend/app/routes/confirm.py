from fastapi import APIRouter, Depends

from app.api.deps import DbDep
from app.models.api import (
    ConfirmApplyRequest,
    ConfirmApplyResponse,
    ConfirmRequest,
    ConfirmResponse,
)
from app.modules.assistant.application.use_cases import apply_confirm, run_confirm
from app.services.confirmation_llm import LLMClient, get_llm_client

router = APIRouter()


@router.post("", response_model=ConfirmResponse)
def post_confirm(
    body: ConfirmRequest,
    db: DbDep,
    llm: LLMClient = Depends(get_llm_client),
) -> ConfirmResponse:
    _ = db
    return run_confirm(dict(body.fields), llm)


@router.post("/apply", response_model=ConfirmApplyResponse)
def post_confirm_apply(body: ConfirmApplyRequest, db: DbDep) -> ConfirmApplyResponse:
    _ = db
    return apply_confirm(body)
