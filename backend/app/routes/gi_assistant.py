"""GI decision-tree AI helper: suggests next branch; tree options remain authoritative."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.gi_symptom_refinement import GiSymptomRefineResponse, refine_symptom_session
from app.services.gi_tree_assistant import GiNextSuggestion, suggest_gi_next_step

router = APIRouter()


class GiSymptomRefineBody(BaseModel):
    messages: list[dict[str, str]] = Field(
        default_factory=list,
        description="Prior turns: {role: user|assistant, content: string}",
    )
    symptom_notes: str = ""


@router.post("/gi-assistant/symptom-refine", response_model=GiSymptomRefineResponse)
def symptom_refine(body: GiSymptomRefineBody) -> GiSymptomRefineResponse:
    """
    Symptom-first interview: AI asks clarifying questions, then proposes a validated tree leaf id.
    """
    try:
        return refine_symptom_session(
            messages=body.messages,
            symptom_notes=body.symptom_notes,
        )
    except RuntimeError as e:
        if "LAVA_API_KEY" in str(e):
            raise HTTPException(
                status_code=503,
                detail="AI assistant is not configured. Add LAVA_API_KEY to backend/.env (see .env.example).",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


class GiAssistantSuggestBody(BaseModel):
    current_node_id: str = Field(..., description="Decision tree node id (e.g. gi_start)")
    question_prompt: str
    hint: str | None = None
    options: list[dict[str, str]] = Field(
        ...,
        description="Each item must include label and nextId (matches frontend tree)",
    )
    symptom_notes: str = ""
    user_message: str = ""


@router.post("/gi-assistant/suggest-next", response_model=GiNextSuggestion)
def suggest_next(body: GiAssistantSuggestBody) -> GiNextSuggestion:
    """
    Suggest which option to follow next. Server validates that the model only returns
    allowed nextIds from the current question.
    """
    try:
        return suggest_gi_next_step(
            current_node_id=body.current_node_id,
            question_prompt=body.question_prompt,
            hint=body.hint,
            options=body.options,
            symptom_notes=body.symptom_notes,
            user_message=body.user_message,
        )
    except RuntimeError as e:
        if "LAVA_API_KEY" in str(e):
            raise HTTPException(
                status_code=503,
                detail="AI assistant is not configured. Add LAVA_API_KEY to backend/.env (see .env.example).",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
