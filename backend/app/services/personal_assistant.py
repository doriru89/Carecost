"""Personal AI assistant: Gemini via Lava OpenAI-compatible API (same stack in dev and production)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings


def parse_json_from_llm_text(text: str) -> dict[str, Any]:
    """Strip optional markdown fences and parse JSON object."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return json.loads(t)


def lava_chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = 2048,
) -> str:
    """
    Send chat messages to the configured Gemini model through Lava's /v1/chat/completions endpoint.

    Set LAVA_API_KEY (and optionally LAVA_GEMINI_MODEL, LAVA_API_BASE_URL) in the environment.
    """
    settings = get_settings()
    if not settings.lava_api_key:
        raise RuntimeError("LAVA_API_KEY is not configured")
    base = settings.lava_api_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    body: dict[str, Any] = {
        "model": settings.lava_gemini_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.lava_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        snippet = ""
        try:
            snippet = (e.response.text or "")[:200]
        except Exception:
            pass
        raise RuntimeError(
            f"Lava HTTP {code} (check LAVA_API_KEY and LAVA_GEMINI_MODEL in backend/.env). {snippet}".strip()
        ) from e
    except httpx.RequestError as e:
        raise RuntimeError(
            f"Cannot reach Lava at {base} — check network and LAVA_API_BASE_URL. ({e})"
        ) from e
    return str(data["choices"][0]["message"]["content"])
