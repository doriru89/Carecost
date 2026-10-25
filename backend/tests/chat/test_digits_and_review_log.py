"""Review round 2 (2026-10-24, Austin chose option A): no digits in model text; a local review
log of model attempts; drop a question-shaped lead_in when candidates already show."""

from __future__ import annotations

import pytest

from .util import llm, req, run, service

DIGITS = [
    "The visit runs roughly 150.",
    "Did it start in the last 6 weeks?",
    "Try it for ２ weeks first.",  # full-width digit
    "大概要３００。",
]


@pytest.mark.parametrize("msg", DIGITS)
def test_any_digit_in_model_text_is_rejected(tmp_path, msg):
    svc, fake = service(tmp_path, script=[llm(message=msg), llm(message=msg)])
    r = run(svc, req())
    assert r["reply"]["kind"] == "llm_invalid" and len(fake.calls) == 2


def test_number_words_without_currency_are_still_allowed(tmp_path):
    msg = "Did it start in the last few weeks, or more than six weeks ago?"
    svc, _ = service(tmp_path, script=[llm(message=msg)])
    assert run(svc, req())["reply"]["lead_in"] == msg


# --------------------------------------------------------------------------- review log

import json  # noqa: E402

from app.chat.config import ChatSettings  # noqa: E402

SECRET_TEXT = "My shoulder zebraquartz has hurt for months"
SECRET_EMAIL = "hidden.person.xyz@example.com"
SECRET_IP = "198.51.100.231"


def _lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_review_log_is_off_by_default(tmp_path):
    assert ChatSettings().review_log is False
    svc, _ = service(tmp_path, script=[llm()], review_log_path=tmp_path / "rev.jsonl")
    run(svc, req())
    assert not (tmp_path / "rev.jsonl").exists()


def test_review_log_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("CARECOST_CHAT_REVIEW_LOG", "1")
    monkeypatch.setenv("CARECOST_CHAT_REVIEW_LOG_PATH", str(tmp_path / "x.jsonl"))
    s = ChatSettings.from_env()
    assert s.review_log is True and s.review_log_path == tmp_path / "x.jsonl"


def test_review_log_one_line_per_attempt(tmp_path):
    p = tmp_path / "rev.jsonl"
    bad = llm(message="Around three hundred dollars. Did it start with a fall?")
    good = llm(message="Did it start with a fall or a twist?")
    svc, _ = service(tmp_path, script=[bad, good], review_log=True, review_log_path=p)
    r = run(svc, req())
    a, b = _lines(p)
    assert (a["attempt"], a["outcome"], a["rule"]) == (1, "rejected", "money")
    assert a["message"] == bad["message"] and "money" in a["reason"]
    assert (b["attempt"], b["outcome"], b["rule"]) == (2, "shown", None)
    assert a["final_kind"] == b["final_kind"] == "clarify" == r["reply"]["kind"]
    assert a["turn"] == 1 and len(a["conversation_hash"]) == 64
    assert r["conversation_id"] not in p.read_text()  # the id itself is hashed
    assert {"ts", "conversation_hash", "turn", "attempt", "message", "outcome", "rule",
            "reason", "final_kind"} == set(a)  # fmt: skip


def test_review_log_never_holds_user_text_email_or_ip(tmp_path):
    from app.chat.llm import ProviderError

    p = tmp_path / "rev.jsonl"
    quote = {"question_id": "Q1", "value": "shoulder", "evidence": "zebraquartz"}
    script = [
        # contract failure whose INPUT is a quote of the person's words ("none" is refused)
        llm(understood=[{"question_id": "Q9", "value": "none", "evidence": "zebraquartz"}]),
        "not json at all zebraquartz",  # unparsed raw output is never logged
        llm(understood=[quote], message="Roughly 150. Did it start with a fall?"),
        llm(understood=[quote]),
        ProviderError("gemini HTTP 503"),
    ]
    svc, _ = service(tmp_path, script=script, review_log=True, review_log_path=p)
    kw = dict(text=SECRET_TEXT, email=SECRET_EMAIL, history=["earlier words mangosteen"])
    run(svc, req(**kw), ip=SECRET_IP)
    run(svc, req(**kw), ip=SECRET_IP)
    run(svc, req(**kw), ip=SECRET_IP)
    dump = p.read_text()
    assert len(dump.splitlines()) == 5
    for secret in ("zebraquartz", "mangosteen", SECRET_EMAIL, "hidden.person", SECRET_IP):
        assert secret not in dump, secret
    outcomes = [x["outcome"] for x in _lines(p)]
    assert outcomes == ["rejected", "rejected", "rejected", "shown", "provider_error"]


# --------------------------------------------------------------------------- voice: lead_in


def test_question_lead_in_is_dropped_when_candidates_and_understood_show(tmp_path):
    # live zh run: knee paths shown, model still asked for the location it had understood
    out = llm(
        understood=[
            {"question_id": "Q1", "value": "knee", "evidence": "膝盖"},
            {"question_id": "Q2", "value": "no_injury", "evidence": "慢慢开始疼"},
        ],
        next_question_id="Q5",
        message="请确认疼痛的具体部位？",
    )
    svc, _ = service(tmp_path, script=[out])
    rep = run(svc, req(text="我的膝盖慢慢开始疼，已经两个月了", locale="zh"))["reply"]
    assert rep["kind"] == "clarify" and rep["candidates"]
    assert rep["lead_in"] is None


def test_statement_lead_in_stays_with_candidates(tmp_path):
    out = llm(
        understood=[
            {"question_id": "Q1", "value": "knee", "evidence": "knee"},
            {"question_id": "Q2", "value": "no_injury", "evidence": "slowly"},
        ],
        next_question_id="Q5",
        message="One more detail helps narrow the knee options.",
    )
    svc, _ = service(tmp_path, script=[out])
    rep = run(svc, req(text="my knee started hurting slowly"))["reply"]
    assert rep["candidates"] and rep["lead_in"] == out["message"]
