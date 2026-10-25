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
