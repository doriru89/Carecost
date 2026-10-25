"""Coordinator review 2026-10-24: two model outputs reached the screen as clarify.lead_in.
1. money spelled out in words; 2. a diagnosis with no condition-shaped word."""

from __future__ import annotations

import pytest

from app.chat import guard

from .util import SHOULDER_DONE, llm, req, run, service


def _rejected(tmp_path, msg, **rq):
    svc, fake = service(tmp_path, script=[llm(message=msg), llm(message=msg)])
    r = run(svc, req(**rq))
    return r["reply"]["kind"] == "llm_invalid" and len(fake.calls) == 2


# --------------------------------------------------------------------------- 1. money in words

MONEY = [
    "An X-ray is usually around three hundred dollars.",
    "Expect a few hundred bucks for the visit.",
    "The scan runs a couple grand without insurance.",
    "It is only a few cents per pill.",
    "Most places charge in USD only.",
    "Did it start with an injury? The visit is a dollar or so.",
    "拍片大概三百美元。",
    "大概几百美金。",
    "大概几百块钱。",
    "一般要几百元。",
]


@pytest.mark.parametrize("msg", MONEY)
def test_money_words_are_rejected(tmp_path, msg):
    assert _rejected(tmp_path, msg)


@pytest.mark.parametrize(
    "msg",
    [
        "Did it start with an injury, like a fall or a twist?",
        "肩膀这块是慢慢开始疼的吗？",  # 块 = 'this area', not money
        "这个单元格不算钱。",  # 单元 is not 元
    ],
)
def test_money_rule_leaves_ordinary_words(msg):
    guard.check_money(msg)


# --------------------------------------------------------------------------- 2. diagnostic cues


def test_pinched_nerve_on_a_no_path_turn_is_rejected(tmp_path):
    assert _rejected(tmp_path, "It might be a pinched nerve in your neck.")


@pytest.mark.parametrize(
    "msg",
    [
        "It could be gout. Did it start with an injury?",
        "Sounds like a muscle strain. Did it start with an injury?",
        "You probably have a trapped nerve. Did it start with a fall?",
        "This is consistent with a nerve problem. Did it start with a fall?",
        "可能是神经压迫。是受伤开始的吗？",
        "像是肌肉拉伤。是受伤开始的吗？",
    ],
)
def test_diagnostic_cues_without_a_shown_path_are_rejected(tmp_path, msg):
    assert _rejected(tmp_path, msg)


DONE = dict(answers=SHOULDER_DONE, history=["my shoulder hurts"], text="It came on slowly.")


def test_cue_on_a_path_turn_must_point_at_the_paths_own_words(tmp_path):
    bad = llm(message="It might be a pinched nerve in your neck.", understood=[],
              next_question_id=None)  # fmt: skip
    svc, _ = service(tmp_path, script=[bad, bad])
    assert run(svc, req(**DONE))["reply"]["kind"] == "llm_invalid"
    good = llm(message="It is most likely the rotator cuff tendons.", understood=[],
               next_question_id=None)  # fmt: skip
    svc2, _ = service(tmp_path / "b", script=[good])
    assert run(svc2, req(**DONE))["reply"]["kind"] == "care_paths"
