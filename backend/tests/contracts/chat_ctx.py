"""ChatContext for the chat fixtures: the registries, the request each reply answers, and an LLM
meter with as many calls as the fixture says happened."""

from __future__ import annotations

import json
from pathlib import Path

from app.chat import contracts as chat
from app.quote.contracts import Catalog

FIX = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def _doc(name: str) -> dict:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("_fixture")
    d.pop("_schema")
    return d


def registries() -> chat.ChatRegistries:
    return chat.ChatRegistries.load(Catalog.model_validate(_doc("catalog")))


def request(**kw) -> chat.ChatRequest:
    return chat.ChatRequest.model_validate({**_doc("chat_request_first_message"), **kw})


def context(body: dict, *, calls: int | None = None, req: chat.ChatRequest | None = None) -> dict:
    reply = body["reply"]
    if req is None:
        focus = None
        if reply.get("focus_line_id"):
            focus = {
                "care_path_id": "shoulder_chronic_clicking_v1",
                "site_id": "mount_auburn_hospital",
                "line_id": reply["focus_line_id"],
            }
        req = request(focus=focus)
    if calls is None:
        calls = {"llm_invalid": 2}.get(reply["kind"], 1) if body["llm_called"] else 0
    ctx = chat.ChatContext.for_request(
        req,
        registries(),
        chat.LlmMeter(calls=calls),
        conversation_turn=body["conversation_turn"],
    )
    return ctx.as_context()


def fixture_context(body: dict) -> dict:
    return context(body)
