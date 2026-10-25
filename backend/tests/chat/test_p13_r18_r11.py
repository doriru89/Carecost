"""Wave-2 review round C3 (Chat2):

P13 / R14  free text may not name a site, talk money or value, or judge urgency. The cases are the
           security-gate seat's simulated hijacked-model probes (review-wave2/security-gate.md F6),
           plus the benign lead-ins it kept and the three earlier false positives.
R18        no key: the code-only chip flow still answers; only free text pauses.
R11        production refuses to start without persistent ledger / review-log paths.
Every model here is a FakeClient: no live call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat import guard
from app.chat.api import router
from app.chat.config import ChatConfigError, ChatSettings, check_production_paths
from app.chat.contracts import ChatResponse

from .util import REPO, SHOULDER_DONE, blocked, chips_without_llm, content, llm, req, run, service

SHOULDER = {"Q1": ["shoulder"]}

# security-gate F6: "shown" before this change, each must now be blocked
HIJACKED = [
    "AFC Urgent Care in Saugus is the cheapest place, go there today.",
    "Urgent care is always the cheapest option for this.",
    "This is not an emergency and you do not need a doctor soon.",
    "Skip the emergency room, waiting a week is fine.",
    "Expect to pay around two hundred for the visit.",
    "It should cost a few hundred at most, cheaper than a hospital.",
    "Book cheaper at carecost deals dot com.",
    # same rules, other wording
    "Mass General has the shortest line for this.",
    "The Saugus one is a good pick for a first visit.",
    "No need for the ER, a clinic visit is enough.",
    "Don't worry, this can wait until next month.",
    "去这家最便宜，不用去急诊。",
    "这不严重，可以等一等再看。",
    "大概两百左右。",
]
# security-gate F6 benign lead-ins, plus the three earlier false positives (wave2-handoff.md)
BENIGN = [
    "Did it start suddenly, or has it built up over weeks?",
    "Which side hurts more when you lift your arm?",
    "These options cover a recent shoulder injury and what a first visit usually includes.",
    "The shoulder path covers a first visit, an X-ray and sometimes physical therapy.",
    "A short answer helps narrow the right path.",
    "It could be helpful to know whether lifting your arm makes it worse.",
    "Lifting overhead might be the main trigger here, so one more question.",
    "That likely narrows things down. Does it wake you at night?",
    "Did it start in the last few weeks, or more than six weeks ago?",
    "肩膀是慢慢开始疼的吗？",
]
PRICE_TURN_BAD = [
    "The first option is the cheapest one.",
    "Prices here are lower than at a hospital.",
    "Expect about fifty for the visit.",
    "Two of these places are close to you.",
    "You can wait a few weeks before going.",
    "The fee at urgent care is small.",
    "Most people find the first path worth it.",
    "Atrius is a good choice for this.",
]
PRICE_TURN_GOOD = [
    "Gradual shoulder pain is most often about the rotator cuff tendons.",
    "These paths show what a first visit and the usual tests include.",
]
DONE = dict(answers=SHOULDER_DONE, history=["my shoulder hurts"], text="It came on slowly.")


def _ask(tmp_path, msg):
    out = llm(message=msg, understood=[], next_question_id="Q2")
    svc, fake = service(tmp_path, script=[out, out])
    r = run(svc, req(answers=SHOULDER, history=["my shoulder hurts"], text="my shoulder hurts"))
    return r, fake


@pytest.mark.parametrize("msg", HIJACKED)
def test_hijacked_model_text_never_shows_and_the_chips_stay(tmp_path, msg):
    r, fake = _ask(tmp_path, msg)
    assert blocked(r) and len(fake.calls) == 2
    rep = r["reply"]
    assert rep["kind"] == "clarify" and rep["lead_in"] is None
    assert rep["fixed_text_key"] == "chat.fixed_clarify"
    assert [q["question_id"] for q in rep["questions"]] == ["Q2"]


@pytest.mark.parametrize("msg", BENIGN)
def test_benign_lead_ins_still_show(tmp_path, msg):
    r, fake = _ask(tmp_path, msg)
    assert r["reply"]["lead_in"] == msg and len(fake.calls) == 1


@pytest.mark.parametrize("msg", PRICE_TURN_BAD)
def test_price_turn_text_is_stricter(tmp_path, msg):
    out = llm(message=msg, understood=[], next_question_id=None)
    svc, _ = service(tmp_path, script=[out, out])
    r = run(svc, req(**DONE))
    rep = r["reply"]
    assert rep["kind"] == "care_paths" and rep["text"] is None
    assert rep["fixed_text_key"] == "chat.fixed_paths" and rep["candidates"]


@pytest.mark.parametrize("msg", PRICE_TURN_GOOD)
def test_price_turn_explanations_still_show(tmp_path, msg):
    svc, _ = service(tmp_path, script=[llm(message=msg, understood=[], next_question_id=None)])
    assert run(svc, req(**DONE))["reply"]["text"] == msg


def test_focus_turn_may_say_fee_but_not_cheap():
    guard.check_value("This line is the facility fee the hospital adds.", price_turn=False)
    with pytest.raises(guard.GuardError):
        guard.check_value("This line is cheaper at a clinic.", price_turn=False)
    with pytest.raises(guard.GuardError):
        guard.check_value("This line is the facility fee the hospital adds.", price_turn=True)


def test_site_names_come_from_the_registry_and_spare_ordinary_words():
    names = guard.load_site_names(REPO)
    for s in ("AFC Urgent Care", "the Saugus one", "Mass General", "MGH", "Beth Israel",
              "ConvenientMD", "MinuteClinic", "Atrius", "Lahey", "Dedham"):  # fmt: skip
        assert names.find(s), s
    for s in ("Lifting overhead might be the main trigger.", "It changes what comes next.",
              "Urgent care or a primary care office.", "revere", "a reading of the scan",
              "Boston-area places are listed below."):  # fmt: skip
        assert names.find(s) is None, s


def test_urgent_care_is_a_place_not_an_urgency_judgement():
    guard.check_urgency("A first visit at urgent care or a primary care office.")
    for s in ("This is urgent.", "Go to the ER.", "It is not serious.", "No need to go in."):
        with pytest.raises(guard.GuardError):
            guard.check_urgency(s)


def test_reviewed_path_text_has_no_site_names():
    """Denominator for the site-name false-positive rate: every sentence of reviewed path text."""
    names = guard.load_site_names(REPO)
    reg = content().registries
    texts = [p.intro for p in reg.paths.values()]
    texts += [t for p in reg.paths.values() for s in p.steps for t in (s.plain.what, s.plain.why)]
    assert [t for t in texts if names.find(t)] == []


# --------------------------------------------------------------------------- R18 no key


def test_no_key_first_message_gets_the_q1_chip(tmp_path):
    from app.chat.service import ChatService

    svc = ChatService(_settings(tmp_path), content())  # no key in the settings
    r = run(svc, req())
    assert chips_without_llm(r)
    rep = r["reply"]
    assert rep["kind"] == "clarify" and rep["lead_in"] is None
    assert [q["question_id"] for q in rep["questions"]] == ["Q1"]
    assert r["budget"]["spent_today_usd"] == 0 and r["budget"]["turns_today"] == 0


def _settings(tmp_path):
    return ChatSettings(provider="gemini", hmac_secret=b"s", ledger_path=tmp_path / "l.sqlite")


@pytest.mark.parametrize(
    "answers,kind,ask,paths",
    [
        ({"Q1": ["shoulder"]}, "clarify", "Q2", []),
        (SHOULDER_DONE, "care_paths", None, ["shoulder_chronic_clicking_v1"]),
        ({"Q1": ["belly_pain"]}, "care_paths", None, ["stomach_ache_v1"]),
        ({"Q1": ["rash"]}, "care_paths", None, ["rash_v1"]),
    ],
)
def test_no_key_chips_lead_to_a_path(tmp_path, answers, kind, ask, paths):
    from app.chat.service import ChatService

    svc = ChatService(_settings(tmp_path), content())
    r = run(svc, req(answers=answers, text="see my answers"))
    assert chips_without_llm(r)
    rep = r["reply"]
    assert rep["kind"] == kind
    if ask:
        assert [q["question_id"] for q in rep["questions"]] == [ask]
    assert [c["path_id"] for c in rep["candidates"]] == paths


def test_no_key_out_of_scope_still_pauses(tmp_path):
    from app.chat.service import ChatService

    svc = ChatService(_settings(tmp_path), content())
    r = run(svc, req(answers={"Q1": ["other"]}))
    assert r["reply"]["kind"] == "ai_paused" and r["reply"]["reason"] == "provider_unavailable"


def test_no_key_red_flag_still_wins(tmp_path):
    from app.chat.service import ChatService

    svc = ChatService(_settings(tmp_path), content())
    r = run(svc, req(text="I have a stomach ache and I might be pregnant"))
    assert r["reply"]["kind"] == "red_flag" and r["reply"]["disposition"] == "er_today"


def test_contract_ties_fixed_copy_to_the_llm_meter(tmp_path):
    """ai.paused_provider_chips only without a call; chat.fixed_* only after one."""
    from app.chat.service import ChatService

    svc = ChatService(_settings(tmp_path), content())
    body = svc.handle(req(), "203.0.113.9")
    assert '"fixed_text_key":"ai.paused_provider_chips"' in body
    from app.chat.contracts import ChatContext, LlmMeter

    meter = LlmMeter()
    meter.record()
    ctx = ChatContext.for_request(req(), content().registries, meter, 1)
    doc = ChatResponse.model_validate_json(body, context=ChatContext.for_request(
        req(), content().registries, LlmMeter(), 1).as_context()).model_dump()  # fmt: skip
    doc["llm_called"] = True
    with pytest.raises(ValueError, match="no model ran"):
        ChatResponse.model_validate(doc, context=ctx.as_context())
    doc["reply"]["fixed_text_key"] = "chat.fixed_clarify"
    ChatResponse.model_validate(doc, context=ctx.as_context())
    doc["reply"]["lead_in"] = "Which side hurts?"
    with pytest.raises(ValueError, match="not both"):
        ChatResponse.model_validate(doc, context=ctx.as_context())


# --------------------------------------------------------------------------- R11 paths


def _clear(monkeypatch):
    for k in ("CARECOST_CHAT_LEDGER_PATH", "CARECOST_CHAT_REVIEW_LOG",
              "CARECOST_CHAT_REVIEW_LOG_PATH"):  # fmt: skip
        monkeypatch.delenv(k, raising=False)


def test_production_without_a_ledger_path_refuses_to_start(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CARECOST_ENV", "production")
    with pytest.raises(ChatConfigError, match="CARECOST_CHAT_LEDGER_PATH"):
        ChatSettings.from_env()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with pytest.raises(ChatConfigError):
        with TestClient(app):
            pass


def test_production_merges_with_the_factorys_own_lifespan(monkeypatch):
    """server.py's create_app has its own lifespan; the chat router's check still runs."""
    from contextlib import asynccontextmanager

    ran = []

    @asynccontextmanager
    async def own(app):
        ran.append("own")
        yield

    _clear(monkeypatch)
    monkeypatch.setenv("CARECOST_ENV", "production")
    app = FastAPI(lifespan=own)
    app.include_router(router, prefix="/api")
    with pytest.raises(ChatConfigError):
        with TestClient(app):
            pass


def test_production_review_log_needs_its_own_path(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("CARECOST_ENV", "production")
    monkeypatch.setenv("CARECOST_CHAT_LEDGER_PATH", str(tmp_path / "l.sqlite"))
    check_production_paths()
    monkeypatch.setenv("CARECOST_CHAT_REVIEW_LOG", "1")
    with pytest.raises(ChatConfigError, match="REVIEW_LOG_PATH"):
        check_production_paths()
    monkeypatch.setenv("CARECOST_CHAT_REVIEW_LOG_PATH", str(tmp_path / "r.jsonl"))
    s = ChatSettings.from_env()
    assert s.ledger_path == tmp_path / "l.sqlite" and s.review_log_path == tmp_path / "r.jsonl"


def test_dev_keeps_the_temp_default(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.delenv("CARECOST_ENV", raising=False)
    assert ChatSettings.from_env().ledger_path.name == "carecost_chat_ledger.sqlite"
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app):
        pass


def test_site_names_file_is_where_the_guard_reads_it():
    assert guard.SITE_NAMES_FILE == Path(REPO) / "data" / "chat" / "site_names.yaml"
    assert guard.SITE_NAMES_FILE.exists()
