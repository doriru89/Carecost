"""
GI symptom → CPT path: AI suggests which decision-tree branch to take next.

The tree (node ids, bundle mapping) remains the source of truth; the model may only
return a recommended_next_id that exists in the current question's options.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.personal_assistant import lava_chat_completion, parse_json_from_llm_text
from app.services.safety_crisis import crisis_scan_text, crisis_response_payload


class GiNextSuggestion(BaseModel):
    recommended_next_id: str | None = None
    assistant_message: str = ""
    confidence: Literal["high", "medium", "low"] = "low"
    safety_hold: bool = False
    safety_message: str = ""
    safety_resources: list[dict[str, str]] = Field(default_factory=list)


def suggest_gi_next_step(
    *,
    current_node_id: str,
    question_prompt: str,
    hint: str | None,
    options: list[dict[str, str]],
    symptom_notes: str = "",
    user_message: str = "",
) -> GiNextSuggestion:
    """
    Ask Gemini (via Lava) which option best matches the patient text.
    Validates that recommended_next_id is one of the provided option nextIds.
    """
    settings = get_settings()
    if not settings.lava_api_key:
        raise RuntimeError("LAVA_API_KEY is not configured")

    combined = f"{symptom_notes.strip()} {user_message.strip()}".strip()
    if crisis_scan_text(combined):
        payload = crisis_response_payload()
        return GiNextSuggestion(
            recommended_next_id=None,
            assistant_message=payload["safety_message"],
            confidence="low",
            safety_hold=True,
            safety_message=payload["safety_message"],
            safety_resources=list(payload["safety_resources"]),
        )

    allowed_ids = {o["nextId"] for o in options if "nextId" in o}
    if not allowed_ids:
        return GiNextSuggestion(
            recommended_next_id=None,
            assistant_message="No options were provided for this step.",
            confidence="low",
            safety_hold=False,
            safety_message="",
            safety_resources=[],
        )

    options_json: list[dict[str, str]] = [
        {"nextId": o["nextId"], "label": o.get("label", "")} for o in options if "nextId" in o
    ]

    system = (
        "You help patients choose the next step in a fixed GI procedure finder for hospital cost estimates only. "
        "You are not diagnosing or prescribing. "
        "You MUST pick exactly one nextId from the allowed list, or use null if the patient text does not fit any option. "
        "Never invent a nextId. Output ONLY valid JSON with keys: recommended_next_id (string or null), "
        "assistant_message (1-3 short sentences in plain language), confidence (high|medium|low)."
    )
    user_payload: dict[str, Any] = {
        "current_node_id": current_node_id,
        "question": question_prompt,
        "hint": hint or "",
        "allowed_options": options_json,
        "patient_notes": symptom_notes.strip(),
        "user_message": user_message.strip(),
    }
    user = json.dumps(user_payload, ensure_ascii=False)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = lava_chat_completion(messages, temperature=0.2, max_tokens=1024)
    data = parse_json_from_llm_text(raw)

    rec = data.get("recommended_next_id")
    if rec is not None:
        rec = str(rec).strip()
        if rec not in allowed_ids:
            rec = None

    msg = str(data.get("assistant_message") or "").strip()
    if not msg:
        msg = "Review the choices below and pick the one that fits best."

    conf_raw = str(data.get("confidence") or "low").lower()
    conf: Literal["high", "medium", "low"] = (
        conf_raw if conf_raw in ("high", "medium", "low") else "low"
    )

    if rec is None and not msg:
        msg = "I could not match your description to a single option. Please choose the closest button below."

    return GiNextSuggestion(
        recommended_next_id=rec,
        assistant_message=msg,
        confidence=conf,
        safety_hold=False,
        safety_message="",
        safety_resources=[],
    )
