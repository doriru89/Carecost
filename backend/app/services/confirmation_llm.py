"""LLM-assisted confirmation: strict schema, no invented prices."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.models.api import IntakeRequest


class LlmConfirmJson(BaseModel):
    missing_fields: list[str] = Field(default_factory=list)
    follow_up_questions: list[dict[str, str]] = Field(default_factory=list)
    suggested_updates: dict[str, Any] = Field(default_factory=dict)


class LLMClient(Protocol):
    def confirm_fields(self, payload: dict[str, Any], schema_hint: str) -> LlmConfirmJson: ...


class FakeLLMClient:
    """Deterministic canned responses for tests."""

    def __init__(self, canned: LlmConfirmJson | None = None) -> None:
        self.canned = canned or LlmConfirmJson(
            missing_fields=["symptom_severity"],
            follow_up_questions=[{"id": "sev", "text": "How severe are your symptoms?"}],
            suggested_updates={},
        )

    def confirm_fields(self, payload: dict[str, Any], schema_hint: str) -> LlmConfirmJson:
        return self.canned


class OpenAICompatibleClient:
    """OpenAI-compatible HTTP client: direct OpenAI or Lava gateway (Gemini, etc.)."""

    def __init__(self, settings: Settings) -> None:
        if settings.lava_api_key:
            self._api_key = settings.lava_api_key
            self._base_url = settings.lava_api_base_url.rstrip("/")
            self._model = settings.lava_gemini_model
            self._json_response_format = False  # Gemini via Lava: rely on prompt; avoid unsupported response_format
        else:
            self._api_key = settings.llm_api_key
            self._base_url = "https://api.openai.com/v1"
            self._model = settings.llm_model
            self._json_response_format = True

    def confirm_fields(self, payload: dict[str, Any], schema_hint: str) -> LlmConfirmJson:
        if not self._api_key:
            return LlmConfirmJson(
                missing_fields=[],
                follow_up_questions=[],
                suggested_updates={},
            )
        system = (
            "You help complete healthcare intake. Output ONLY valid JSON matching the schema. "
            "Never invent prices or network status. Propose follow-up questions only from allowed topics."
        )
        user = json.dumps({"fields": payload, "schema": schema_hint})
        url = f"{self._base_url}/chat/completions"
        req_json: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._json_response_format:
            req_json["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=req_json,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            raw = json.loads(content)
        return validate_llm_confirm(raw)


def validate_llm_confirm(raw: dict[str, Any]) -> LlmConfirmJson:
    """Discard hallucinated keys by validating against Pydantic."""
    allowed_question_keys = {"id", "text"}
    questions: list[dict[str, str]] = []
    for q in raw.get("follow_up_questions") or []:
        if isinstance(q, dict) and allowed_question_keys.issuperset(q.keys()):
            questions.append({"id": str(q["id"]), "text": str(q["text"])})
    allowed = set(IntakeRequest.model_fields.keys())
    sugg = raw.get("suggested_updates") or {}
    if not isinstance(sugg, dict):
        sugg = {}
    filtered = {k: v for k, v in sugg.items() if k in allowed}
    return LlmConfirmJson(
        missing_fields=[str(x) for x in (raw.get("missing_fields") or [])],
        follow_up_questions=questions,
        suggested_updates=filtered,
    )


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.lava_api_key or settings.llm_api_key:
        return OpenAICompatibleClient(settings)
    return FakeLLMClient()
