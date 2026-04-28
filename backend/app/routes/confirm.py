from fastapi import APIRouter, Depends

from app.api.deps import DbDep
from app.models.api import (
    ConfirmApplyRequest,
    ConfirmApplyResponse,
    ConfirmRequest,
    ConfirmResponse,
    FollowUpQuestion,
)
from app.services.confirmation_llm import LLMClient, get_llm_client, validate_llm_confirm
from app.services.intake import missing_required_fields, normalize_intake

router = APIRouter()


@router.post("", response_model=ConfirmResponse)
def post_confirm(
    body: ConfirmRequest,
    db: DbDep,
    llm: LLMClient = Depends(get_llm_client),
) -> ConfirmResponse:
    _ = db
    fields = dict(body.fields)
    merged = normalize_intake(fields)
    schema_hint = "missing_fields: string[], follow_up_questions: {id,text}[], suggested_updates: object"
    llm_out = llm.confirm_fields(merged, schema_hint)
    # Re-validate through Pydantic to strip bad keys
    validated = validate_llm_confirm(llm_out.model_dump())
    base_missing = set(missing_required_fields(merged))
    llm_missing = set(validated.missing_fields)
    all_missing = sorted(base_missing | llm_missing)
    questions = [FollowUpQuestion(id=q["id"], text=q["text"]) for q in validated.follow_up_questions]
    return ConfirmResponse(
        missing_fields=all_missing,
        follow_up_questions=questions,
        suggested_updates=validated.suggested_updates,
    )


@router.post("/apply", response_model=ConfirmApplyResponse)
def post_confirm_apply(body: ConfirmApplyRequest, db: DbDep) -> ConfirmApplyResponse:
    _ = db
    merged = {**body.fields, **body.answers}
    normalized = normalize_intake(merged)
    missing = missing_required_fields(normalized)
    return ConfirmApplyResponse(
        normalized=normalized,
        missing_required=missing,
        ready_for_estimate=len(missing) == 0,
    )
