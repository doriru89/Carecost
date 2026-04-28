"""
Symptom-first GI flow: AI asks clarifying questions, then maps to a validated decision-tree leaf (CPT).

Tree leaf ids remain the source of truth; the model must only return leaf ids from the allowed catalog.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.personal_assistant import lava_chat_completion, parse_json_from_llm_text
from app.services.safety_crisis import crisis_response_payload, crisis_scan_messages

# Keep in sync with frontend `GI_PROCEDURE_NODES` leaves (giDecisionTree.ts).
GI_LEAF_CATALOG: list[dict[str, str]] = [
    {
        "id": "leaf_colonoscopy_screening",
        "cpt": "45378",
        "title": "Screening colonoscopy",
        "summary": "Preventive screening when there are no active GI symptoms.",
    },
    {
        "id": "leaf_colonoscopy_diagnostic",
        "cpt": "45378",
        "title": "Diagnostic colonoscopy",
        "summary": "Colonoscopy to evaluate symptoms, abnormal tests, or follow-up findings.",
    },
    {
        "id": "leaf_colonoscopy_polyp",
        "cpt": "45385",
        "title": "Colonoscopy with polypectomy",
        "summary": "Procedure focused on removing polyps or similar interventions.",
    },
    {
        "id": "leaf_colonoscopy_with_biopsy",
        "cpt": "45380",
        "title": "Colonoscopy with biopsy",
        "summary": "Colonoscopy including mucosal biopsies when indicated.",
    },
    {
        "id": "leaf_egd_with_biopsy",
        "cpt": "43235",
        "title": "EGD (upper endoscopy) with biopsy",
        "summary": "Upper endoscopy with biopsy for reflux, dyspepsia, or similar evaluation.",
    },
    {
        "id": "leaf_egd_bleeding",
        "cpt": "43255",
        "title": "EGD for bleeding",
        "summary": "Upper endoscopy for bleeding evaluation or therapeutic control.",
    },
    {
        "id": "leaf_egd_dilation",
        "cpt": "43249",
        "title": "EGD with dilation",
        "summary": "Endoscopy with dilation of a stricture or similar.",
    },
    {
        "id": "leaf_gi_imaging_ct",
        "cpt": "74176",
        "title": "CT abdomen / pelvis without contrast",
        "summary": "Cross-sectional abdominal imaging used in GI workups.",
    },
    {
        "id": "leaf_capsule_endoscopy",
        "cpt": "91110",
        "title": "Capsule endoscopy",
        "summary": "Wireless capsule study of the small bowel.",
    },
]

ALLOWED_LEAF_IDS = {row["id"] for row in GI_LEAF_CATALOG}


class GiSymptomRefineResponse(BaseModel):
    phase: Literal["continue", "propose"] = Field(
        ...,
        description="continue = ask another symptom question; propose = ready to map to one leaf",
    )
    next_question: str | None = None
    recommended_leaf_id: str | None = None
    assistant_message: str = ""
    choice_options: list[str] = Field(
        default_factory=list,
        description="Short tap labels for discrete choices (2–6); empty if free-text only.",
    )
    confidence: Literal["high", "medium", "low"] = "low"
    rationale: str | None = Field(
        None,
        description="Short reason for the proposed mapping (for transparency, not medical advice)",
    )
    safety_hold: bool = Field(
        False,
        description="True = crisis language detected; client must show resources and skip estimates.",
    )
    safety_message: str = ""
    safety_resources: list[dict[str, str]] = Field(default_factory=list)


def _build_system_prompt() -> str:
    catalog_json = json.dumps(GI_LEAF_CATALOG, ensure_ascii=False)
    return (
        "You are a quick, natural intake assistant for a hospital cost-estimate demo (US). "
        "You do NOT diagnose, treat, or give medical advice.\n\n"
        "Voice & pacing:\n"
        "- Sound human and efficient—like a good triage chat, not a form letter.\n"
        "- Do NOT use repetitive fillers: avoid starting turns with phrases like \"I understand\", "
        "\"Thank you for sharing\", \"That makes sense\", \"Got it\", or similar stock acknowledgments. "
        "Do not repeat the same opening across consecutive turns.\n"
        "- assistant_message: at most ONE short optional clause (or empty). Put the real ask in next_question. "
        "No fluff; get to the point.\n\n"
        "Substance:\n"
        "- Map the patient's symptoms and goals in plain language to ONE procedure bucket from the catalog when ready.\n"
        "- Ask ONE focused follow-up at a time. Never ask the patient to pick a CPT code.\n"
        "- Prefer at least two meaningful exchanges before proposing unless the first message is already very specific.\n"
        "- When unsure between buckets, ask one more distinguishing question instead of guessing.\n\n"
        "choice_options (tap targets):\n"
        "- If next_question can be answered by choosing among clear options, set choice_options to 2–6 SHORT labels "
        "(under 12 words each) for on-screen buttons. Cover the common cases; add \"Something else\" when useful.\n"
        "- If the patient must describe something in their own words (location, duration, story), set choice_options to [].\n\n"
        "Output ONLY valid JSON with keys:\n"
        "phase (\"continue\" or \"propose\"),\n"
        "next_question (string or null),\n"
        "recommended_leaf_id (string or null),\n"
        "assistant_message (string, brief),\n"
        "choice_options (array of strings, may be empty),\n"
        "confidence (\"high\"|\"medium\"|\"low\"),\n"
        "rationale (string or null).\n"
        "- If phase is \"continue\": recommended_leaf_id null; next_question is your single question.\n"
        "- If phase is \"propose\": recommended_leaf_id must be exactly one catalog id; next_question null; choice_options [].\n\n"
        "Allowed leaf catalog (id must match exactly when proposing):\n"
        f"{catalog_json}\n"
    )


def refine_symptom_session(
    *,
    messages: list[dict[str, str]],
    symptom_notes: str = "",
) -> GiSymptomRefineResponse:
    settings = get_settings()
    if not settings.lava_api_key:
        raise RuntimeError("LAVA_API_KEY is not configured")

    if crisis_scan_messages(symptom_notes, list(messages)):
        payload = crisis_response_payload()
        return GiSymptomRefineResponse(
            phase="continue",
            next_question=None,
            recommended_leaf_id=None,
            assistant_message=payload["safety_message"],
            choice_options=[],
            confidence="low",
            rationale=None,
            safety_hold=True,
            safety_message=payload["safety_message"],
            safety_resources=list(payload["safety_resources"]),
        )

    # Only user/assistant roles for transcript
    safe_messages: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role")
        content = str(m.get("content", "")).strip()
        if role not in ("user", "assistant") or not content:
            continue
        safe_messages.append({"role": role, "content": content})

    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in safe_messages[-24:])

    user_block = {
        "patient_free_text_symptoms_or_goals": symptom_notes.strip(),
        "conversation_transcript": transcript or "(no messages yet — this is the first turn)",
    }
    user = (
        "Based on the free-text notes and the conversation, either ask the next single symptom question "
        "or propose the best-matching leaf id.\n\n"
        + json.dumps(user_block, ensure_ascii=False)
    )

    llm_messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": user},
    ]
    raw = lava_chat_completion(llm_messages, temperature=0.35, max_tokens=1200)
    data = parse_json_from_llm_text(raw)

    return _normalize_response(data)


def _normalize_choice_options(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        s = str(x).strip()
        if not s or len(s) > 160:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= 6:
            break
    return out


def _normalize_response(data: dict[str, Any]) -> GiSymptomRefineResponse:
    phase_raw = str(data.get("phase") or "continue").lower()
    phase: Literal["continue", "propose"] = "propose" if phase_raw == "propose" else "continue"

    nq = data.get("next_question")
    next_question = str(nq).strip() if nq is not None else ""

    rec = data.get("recommended_leaf_id")
    recommended_leaf_id: str | None = None
    if rec is not None:
        rid = str(rec).strip()
        if rid in ALLOWED_LEAF_IDS:
            recommended_leaf_id = rid

    msg = str(data.get("assistant_message") or "").strip()

    conf_raw = str(data.get("confidence") or "low").lower()
    conf: Literal["high", "medium", "low"] = (
        conf_raw if conf_raw in ("high", "medium", "low") else "low"
    )

    rationale_val = data.get("rationale")
    rationale = str(rationale_val).strip() if rationale_val is not None else None
    if rationale == "":
        rationale = None

    # Enforce consistency
    if phase == "propose":
        if recommended_leaf_id is None:
            phase = "continue"
            if not next_question:
                next_question = (
                    "To pick the right procedure for your estimate, what is the main reason for the visit—"
                    "routine screening, new symptoms, or follow-up on something already found?"
                )
        else:
            next_question = ""

    choice_opts = _normalize_choice_options(data.get("choice_options"))

    if phase == "continue":
        recommended_leaf_id = None
        if not next_question:
            next_question = "What symptoms or concerns brought you in today?"
    else:
        choice_opts = []

    if phase == "propose" and not msg:
        msg = "Here’s the closest match for your estimate based on what you shared."

    return GiSymptomRefineResponse(
        phase=phase,
        next_question=next_question if phase == "continue" else None,
        recommended_leaf_id=recommended_leaf_id,
        assistant_message=msg,
        choice_options=choice_opts,
        confidence=conf,
        rationale=rationale,
        safety_hold=False,
        safety_message="",
        safety_resources=[],
    )
