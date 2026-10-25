"""Shared helpers for the chat tests. Every LLM is a FakeClient: no test makes a live call."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any

from app.chat.config import ChatSettings
from app.chat.contracts import ChatRequest
from app.chat.llm import FakeClient
from app.chat.service import ChatService, Content
from app.quote.contracts import Catalog

REPO = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)  # 11:00 Pacific

FIRST = "My shoulder has hurt for a few months and it clicks when I lift my arm."


@cache
def content() -> Content:
    """The real content files + the fixture catalog (it has services, the fallback has none)."""
    d = json.loads((REPO / "contracts" / "fixtures" / "catalog.json").read_text())
    d.pop("_fixture"), d.pop("_schema")
    return Content.load(Catalog.model_validate(d))


def settings(tmp: Path, **kw: Any) -> ChatSettings:
    base: dict[str, Any] = dict(
        provider="gemini",
        hmac_secret=b"test-secret",
        ledger_path=tmp / "ledger.sqlite",
    )
    base.update(kw)
    return ChatSettings(**base)


def service(tmp: Path, script: list | None = None, clock=lambda: NOW, **kw: Any):
    fake = FakeClient(list(script or []))
    svc = ChatService(settings(tmp, **kw), content(), client=fake, clock=clock)
    return svc, fake


def req(**kw: Any) -> ChatRequest:
    base: dict[str, Any] = dict(
        conversation_id=None,
        text=FIRST,
        payment={"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None},
        email="someone@example.com",
        answers={},
        history=[],
        focus=None,
        locale="en",
    )
    base.update(kw)
    return ChatRequest.model_validate(base)


def llm(**kw: Any) -> dict:
    """One well-formed model output; override fields per test."""
    base: dict[str, Any] = dict(
        message="Did this start after a fall or a twist, or did it come on slowly?",
        understood=[{"question_id": "Q1", "value": "shoulder", "evidence": "My shoulder"}],
        next_question_id="Q2",
        path_ids=[],
        service_ids=[],
        glossary_keys=[],
        escalate=None,
    )
    base.update(kw)
    return base


SHOULDER_DONE = {"Q1": ["shoulder"], "Q2": ["no_injury"]}


def run(svc: ChatService, r: ChatRequest, ip: str = "203.0.113.7") -> dict:
    return json.loads(svc.handle(r, ip))


def blocked(r: dict) -> bool:
    """The model's text did not reach the screen: llm_invalid, or (P13) the code-only reply with
    fixed copy after two rejected outputs. Either way the model ran (llm_called)."""
    reply = r["reply"]
    fixed = reply.get("fixed_text_key") or ""
    return r["llm_called"] and (reply["kind"] == "llm_invalid" or fixed.startswith("chat.fixed"))


def chips_without_llm(r: dict) -> bool:
    """R18: no model this turn, but the code-only chip flow answered."""
    reply = r["reply"]
    return (
        r["llm_called"] is False
        and reply["kind"] in ("clarify", "care_paths")
        and reply["fixed_text_key"] == "ai.paused_provider_chips"
    )


__all__ = ["FakeClient", "NOW", "FIRST", "SHOULDER_DONE", "blocked", "chips_without_llm",
           "content", "llm", "req", "run", "service", "settings"]  # fmt: skip
