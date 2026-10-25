"""LLM clients. The model only phrases things; every client returns raw text plus token counts.

- ``GeminiClient``: Gemini API ``models.generateContent`` (paid tier, D26), JSON output forced
  with ``responseMimeType`` + ``responseSchema``. Key from ``CARECOST_GEMINI_API_KEY``, sent in the
  ``x-goog-api-key`` header (never in the URL, so it cannot end up in an access log).
- ``LavaClient``: the D15 switch. Lava's gateway is OpenAI-compatible (``/v1/chat/completions``),
  the same call the 2026-04 code made (b4c63f3 ``personal_assistant.lava_chat_completion``).
- ``FakeClient``: scripted, for every test. No test makes a live call.

Prices (USD per 1M tokens, paid tier), from https://ai.google.dev/gemini-api/docs/pricing
(page "Last updated 2026-10-22 UTC", read 2026-10-24). Thinking tokens bill as output.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import httpx

from app.chat.contracts import LlmMeter

# model -> list of (effective from, input per 1M, output per 1M)
PRICES: dict[str, list[tuple[date, float, float]]] = {
    "gemini-3.8-flash": [(date(2000, 1, 1), 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.6-flash": [(date(2000, 1, 1), 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.5-flash-lite": [(date(2000, 1, 1), 0.30, 2.50)],
    "gemini-2.5-flash": [(date(2000, 1, 1), 0.30, 2.50)],
}


def price_per_mtok(model: str, on: date) -> tuple[float, float]:
    rows = PRICES.get(model)
    if not rows:
        raise KeyError(f"no price for model {model!r}: set CARECOST_CHAT_PRICE_*_PER_MTOK")
    cur = rows[0]
    for r in rows:
        if r[0] <= on:
            cur = r
    return cur[1], cur[2]


@dataclass(frozen=True)
class Price:
    in_per_mtok: float
    out_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.in_per_mtok + output_tokens * self.out_per_mtok) / 1_000_000


@dataclass(frozen=True)
class LlmResult:
    text: str
    input_tokens: int
    output_tokens: int  # including thinking tokens


class ProviderError(Exception):
    """No usable answer from the provider. ``maybe_billed``: a timeout may still be charged."""

    def __init__(self, msg: str, maybe_billed: bool = False):
        super().__init__(msg)
        self.maybe_billed = maybe_billed


class LlmClient(Protocol):
    model: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult: ...


def estimate_input_tokens(*texts: str) -> int:
    """Upper-bound guess for the reservation: ~3 chars per token (English is ~4, CJK ~1-2 per
    char so CJK counts 1 token per char). Settlement uses the provider's real count."""
    n = 0
    for t in texts:
        cjk = sum(1 for ch in t if "　" <= ch <= "鿿")
        n += cjk + (len(t) - cjk) // 3 + 1
    return n + 64


class MeteredClient:
    """Wraps a client; ``meter.record()`` once per provider answer (theater F7: the handler never
    sets llm_called itself). A call that got no answer is not recorded."""

    def __init__(self, inner: LlmClient, meter: LlmMeter):
        self.inner = inner
        self.meter = meter
        self.model = inner.model

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        r = self.inner.complete(system, user, schema)
        self.meter.record()
        return r


# --------------------------------------------------------------------------- Gemini


def to_gemini_schema(s: Any) -> Any:
    """JSON Schema subset -> Gemini OpenAPI-subset schema (upper-case types, nullable)."""
    if isinstance(s, dict):
        out: dict[str, Any] = {}
        for k, v in s.items():
            if k == "type":
                if isinstance(v, list):
                    types = [t for t in v if t != "null"]
                    out["type"] = types[0].upper()
                    if "null" in v:
                        out["nullable"] = True
                else:
                    out["type"] = v.upper()
            elif k in ("additionalProperties",):
                continue
            else:
                out[k] = to_gemini_schema(v)
        return out
    if isinstance(s, list):
        return [to_gemini_schema(x) for x in s]
    return s


@dataclass
class GeminiClient:
    api_key: str = field(repr=False)
    model: str = "gemini-3.8-flash"
    thinking_level: str | None = "low"
    max_output_tokens: int = 1024
    timeout_s: float = 20.0
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    transport: httpx.BaseTransport | None = None

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        gen: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseSchema": to_gemini_schema(schema),
            "maxOutputTokens": self.max_output_tokens,
            "temperature": 0.3,
        }
        if self.thinking_level:
            gen["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        }
        url = f"{self.base_url}/models/{self.model}:generateContent"
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as c:
                r = c.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        except httpx.TimeoutException as e:
            raise ProviderError("gemini timeout", maybe_billed=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini transport error: {type(e).__name__}") from e
        if r.status_code != 200:
            # body may echo the request; keep only the status and Google's error status word
            status = ""
            try:
                status = r.json().get("error", {}).get("status", "")
            except ValueError:
                pass
            raise ProviderError(f"gemini HTTP {r.status_code} {status}".strip())
        data = r.json()
        um = data.get("usageMetadata", {})
        tin = int(um.get("promptTokenCount", 0))
        tout = int(um.get("candidatesTokenCount", 0)) + int(um.get("thoughtsTokenCount", 0))
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return LlmResult(text, tin, tout)


# --------------------------------------------------------------------------- Lava (D15)


@dataclass
class LavaClient:
    api_key: str = field(repr=False)
    model: str = "gemini-3.8-flash"
    base_url: str = "https://api.lava.so/v1"
    max_output_tokens: int = 1024
    timeout_s: float = 20.0
    transport: httpx.BaseTransport | None = None

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system
                    + "\n\nReply with JSON only, matching this JSON Schema:\n"
                    + json.dumps(schema),
                },
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": self.max_output_tokens,
        }
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as c:
                r = c.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.TimeoutException as e:
            raise ProviderError("lava timeout", maybe_billed=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"lava transport error: {type(e).__name__}") from e
        if r.status_code != 200:
            raise ProviderError(f"lava HTTP {r.status_code}")
        data = r.json()
        usage = data.get("usage", {})
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return LlmResult(
            text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        )


# --------------------------------------------------------------------------- fake (tests)


@dataclass
class FakeClient:
    """Returns scripted outputs in order. Each item is a dict (sent as JSON), a raw string, an
    exception to raise, or a callable(system, user) -> one of those."""

    script: list[Any] = field(default_factory=list)
    model: str = "gemini-3.8-flash"
    calls: list[tuple[str, str]] = field(default_factory=list)
    input_tokens: int = 1500
    output_tokens: int = 200

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        self.calls.append((system, user))
        if not self.script:
            raise AssertionError("FakeClient called more often than scripted")
        item = self.script.pop(0)
        if isinstance(item, Callable):  # type: ignore[arg-type]
            item = item(system, user)
        if isinstance(item, BaseException):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return LlmResult(text, self.input_tokens, self.output_tokens)
