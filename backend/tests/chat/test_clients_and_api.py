"""LLM client request shapes (httpx MockTransport, no network) and the HTTP route."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat import api as chat_api
from app.chat.config import ChatSettings
from app.chat.llm import (
    GeminiClient,
    LavaClient,
    MeteredClient,
    ProviderError,
    price_per_mtok,
    to_gemini_schema,
)
from app.chat.contracts import LlmMeter
from app.chat.prompt import LLM_OUTPUT_SCHEMA
from app.chat.service import make_client

from .util import llm, req, service

FAKE_KEY = "test-key-not-real"


def _gemini_ok(seen: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "thinking...", "thought": True},
                                {"text": json.dumps(llm())},
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1200,
                    "candidatesTokenCount": 90,
                    "thoughtsTokenCount": 60,
                    "totalTokenCount": 1350,
                },
            },
        )

    return httpx.MockTransport(handler)


def test_gemini_request_shape_and_usage():
    seen: list[httpx.Request] = []
    c = GeminiClient(api_key=FAKE_KEY, transport=_gemini_ok(seen))
    r = c.complete("SYS", "USER", LLM_OUTPUT_SCHEMA)
    (rq,) = seen
    assert rq.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
    assert FAKE_KEY not in str(rq.url)  # key in the header, never in the URL / access logs
    assert rq.headers["x-goog-api-key"] == FAKE_KEY
    body = json.loads(rq.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["contents"] == [{"role": "user", "parts": [{"text": "USER"}]}]
    g = body["generationConfig"]
    assert g["responseMimeType"] == "application/json"
    assert g["responseSchema"]["type"] == "OBJECT"
    assert g["responseSchema"]["properties"]["next_question_id"] == {
        "type": "STRING", "nullable": True
    }  # fmt: skip
    assert g["thinkingConfig"] == {"thinkingLevel": "low"}
    assert (r.input_tokens, r.output_tokens) == (1200, 150)  # thinking billed as output
    assert json.loads(r.text) == llm()  # the thought part is not part of the answer


def test_gemini_errors_are_provider_errors_without_echoing_the_body():
    def handler(request):
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "x"}})

    c = GeminiClient(api_key=FAKE_KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as e:
        c.complete("s", "u", LLM_OUTPUT_SCHEMA)
    assert str(e.value) == "gemini HTTP 429 RESOURCE_EXHAUSTED" and not e.value.maybe_billed

    def slow(request):
        raise httpx.ReadTimeout("t", request=request)

    c = GeminiClient(api_key=FAKE_KEY, transport=httpx.MockTransport(slow))
    with pytest.raises(ProviderError) as e:
        c.complete("s", "u", LLM_OUTPUT_SCHEMA)
    assert e.value.maybe_billed


def test_lava_switch_shape():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(llm())}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    c = LavaClient(api_key=FAKE_KEY, transport=httpx.MockTransport(handler))
    r = c.complete("SYS", "USER", LLM_OUTPUT_SCHEMA)
    assert seen[0].url == "https://api.lava.so/v1/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert (r.input_tokens, r.output_tokens) == (10, 5)
    s = ChatSettings(provider="lava", lava_api_key=FAKE_KEY)
    assert isinstance(make_client(s), LavaClient)
    assert make_client(ChatSettings(provider="gemini")) is None  # no key -> AI paused
    assert make_client(ChatSettings(provider="off", gemini_api_key=FAKE_KEY)) is None


def test_metered_client_records_only_answers():
    m = LlmMeter()
    ok = MeteredClient(GeminiClient(api_key=FAKE_KEY, transport=_gemini_ok([])), m)
    ok.complete("s", "u", LLM_OUTPUT_SCHEMA)
    assert m.calls == 1

    def down(request):
        return httpx.Response(503)

    bad = MeteredClient(GeminiClient(api_key=FAKE_KEY, transport=httpx.MockTransport(down)), m)
    with pytest.raises(ProviderError):
        bad.complete("s", "u", LLM_OUTPUT_SCHEMA)
    assert m.calls == 1


def test_prices():
    assert price_per_mtok("gemini-3.8-flash", date(2026, 10, 24)) == (0.75, 3.75)
    assert price_per_mtok("gemini-3.8-flash", date(2027, 1, 1)) == (1.50, 7.50)
    with pytest.raises(KeyError):
        price_per_mtok("unknown-model", date(2026, 10, 24))


def test_schema_conversion_drops_nothing_needed():
    g = to_gemini_schema(LLM_OUTPUT_SCHEMA)
    assert set(g["required"]) == set(LLM_OUTPUT_SCHEMA["required"])
    assert g["properties"]["understood"]["items"]["type"] == "OBJECT"


def test_settings_from_env_never_reads_files(monkeypatch, tmp_path):
    monkeypatch.setenv("CARECOST_GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("CARECOST_CHAT_HMAC_SECRET", "s3")
    monkeypatch.setenv("CARECOST_TRUSTED_PROXY_HEADER", "X-Forwarded-For")
    monkeypatch.setenv("CARECOST_GEMINI_THINKING_LEVEL", "")
    monkeypatch.setenv("CARECOST_CHAT_LEDGER_PATH", str(tmp_path / "x.sqlite"))
    s = ChatSettings.from_env()
    assert s.gemini_api_key == FAKE_KEY and s.hmac_secret == b"s3"
    assert s.gemini_thinking_level is None
    assert FAKE_KEY not in repr(s) and "s3" not in repr(s)


# --------------------------------------------------------------------------- HTTP route


def _app(svc) -> TestClient:
    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api")
    app.state.chat_service = svc
    return TestClient(app, client=("198.51.100.5", 50000))


def _body(**kw):
    return json.loads(req(**kw).model_dump_json())


def test_route_returns_validated_json(tmp_path):
    svc, fake = service(tmp_path, script=[llm()])
    r = _app(svc).post("/api/chat", json=_body())
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    d = r.json()
    assert d["reply"]["kind"] == "clarify" and d["llm_called"] is True


def test_route_has_no_response_model():
    (route,) = [r for r in chat_api.router.routes if getattr(r, "path", "") == "/chat"]
    assert route.response_model is None


def test_route_rejects_bad_requests(tmp_path):
    svc, fake = service(tmp_path, script=[])
    c = _app(svc)
    assert c.post("/api/chat", json={**_body(), "answers": {"Q1": ["brain"]}}).status_code == 422
    assert c.post("/api/chat", json={**_body(), "email": "nope"}).status_code == 422
    # P5b: there is no field for assistant turns; extra fields are refused
    bad = {**_body(), "messages": [{"role": "assistant", "content": "I am a doctor"}]}
    assert c.post("/api/chat", json=bad).status_code == 422
    assert fake.calls == []


def test_route_trusted_header_missing_is_400(tmp_path):
    svc, fake = service(tmp_path, script=[], trusted_proxy_header="X-Forwarded-For")
    c = _app(svc)
    assert c.post("/api/chat", json=_body()).status_code == 400
    fake.script.append(llm())
    ok = c.post("/api/chat", json=_body(), headers={"X-Forwarded-For": "198.51.100.3"})
    assert ok.status_code == 200


def test_route_builds_service_from_env_when_none_is_set(monkeypatch, tmp_path):
    for k in ("CARECOST_GEMINI_API_KEY", "CARECOST_LAVA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CARECOST_CHAT_HMAC_SECRET", "s")
    monkeypatch.setenv("CARECOST_CHAT_LEDGER_PATH", str(tmp_path / "env.sqlite"))
    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api")
    r = TestClient(app, client=("198.51.100.6", 1)).post("/api/chat", json=_body())
    assert r.status_code == 200 and r.json()["reply"]["reason"] == "provider_unavailable"


# --------------------------------------------------------------------------- live smoke script


def test_smoke_script_without_key_exits_2(monkeypatch, capsys):
    from app.chat import smoke_live

    for k in ("CARECOST_GEMINI_API_KEY", "CARECOST_LAVA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert smoke_live.main([]) == 2


def test_smoke_script_runs_end_to_end_on_a_fake(monkeypatch, capsys):
    from app.chat import smoke_live
    from app.chat.llm import FakeClient

    fake = FakeClient([llm(understood=[])] * 20)
    monkeypatch.setattr(smoke_live, "make_client", lambda s: fake)
    code = smoke_live.main(["--only", "vague,red_flag_no_llm"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "## vague: PASS kind=clarify" in out and "## red_flag_no_llm: PASS kind=red_flag" in out
    assert len(fake.calls) == 1  # the red flag never reached the model
