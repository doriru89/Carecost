from __future__ import annotations

from app.models.api import (
    ConfirmApplyRequest,
    ConfirmApplyResponse,
    ConfirmResponse,
    FollowUpQuestion,
)
from app.services.confirmation_llm import LLMClient, validate_llm_confirm
from app.services.gi_symptom_refinement import GiSymptomRefineResponse, refine_symptom_session
from app.services.gi_tree_assistant import GiNextSuggestion, suggest_gi_next_step
from app.services.intake import missing_required_fields, normalize_intake, validate_intake_payload


def run_intake(payload: dict) -> tuple[dict, list[str]]:
    return validate_intake_payload(payload)


def run_confirm(fields: dict, llm: LLMClient) -> ConfirmResponse:
    merged = normalize_intake(fields)
    schema_hint = "missing_fields: string[], follow_up_questions: {id,text}[], suggested_updates: object"
    llm_out = llm.confirm_fields(merged, schema_hint)
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


def apply_confirm(body: ConfirmApplyRequest) -> ConfirmApplyResponse:
    merged = {**body.fields, **body.answers}
    normalized = normalize_intake(merged)
    missing = missing_required_fields(normalized)
    return ConfirmApplyResponse(
        normalized=normalized,
        missing_required=missing,
        ready_for_estimate=len(missing) == 0,
    )


def run_gi_symptom_refine(*, messages: list[dict[str, str]], symptom_notes: str) -> GiSymptomRefineResponse:
    return refine_symptom_session(messages=messages, symptom_notes=symptom_notes)


def run_gi_suggest_next(
    *,
    current_node_id: str,
    question_prompt: str,
    hint: str | None,
    options: list[dict[str, str]],
    symptom_notes: str,
    user_message: str,
) -> GiNextSuggestion:
    return suggest_gi_next_step(
        current_node_id=current_node_id,
        question_prompt=question_prompt,
        hint=hint,
        options=options,
        symptom_notes=symptom_notes,
        user_message=user_message,
    )
