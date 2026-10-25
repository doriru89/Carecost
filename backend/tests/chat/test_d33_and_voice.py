"""D33: condition names only from the shown care path; "because" = the person's own chip answers;
fixed not-a-diagnosis + when-to-see-a-doctor copy. Plus the Kenza voice rules that are mechanical."""

from __future__ import annotations

import pytest

from app.chat import guard
from app.chat.contracts import CARE_PATH_COPY_KEYS

from .util import SHOULDER_DONE, blocked, llm, req, run, service

DONE = dict(answers=SHOULDER_DONE, history=["my shoulder hurts"], text="It came on slowly.")


def _care(msg: str) -> dict:
    return llm(message=msg, understood=[], next_question_id=None)


def test_care_paths_reply_explains_with_path_names_and_the_persons_answers(tmp_path):
    svc, _ = service(
        tmp_path,
        script=[_care("Slow shoulder pain like this most often comes from the rotator cuff.")],
    )
    r = run(svc, req(**DONE))
    rep = r["reply"]
    assert rep["kind"] == "care_paths"
    assert rep["copy_keys"] == list(CARE_PATH_COPY_KEYS)
    (c,) = rep["candidates"]
    assert c["path_id"] == "shoulder_chronic_clicking_v1" and c["match"] == "entry_matched"
    # because = the person's own chip answers, labels verbatim from questions.yaml
    assert [(b["question_id"], b["value"], b["label"]["en"]) for b in c["because"]] == [
        ("Q1", "shoulder", "Shoulder"),
        ("Q2", "no_injury", "No, it came on gradually"),
    ]


REJECT = [
    # listed in condition_names.yaml but not in this path's intro/glossary -> contract D33 check
    "This sounds like bursitis.",
    "It could be a frozen shoulder.",
    "Common causes include cancer.",
    # NOT in the deny-list: caught by the chat guard's medical word shapes
    "It might be avascular necrosis or osteonecrosis.",
    "This could be a SLAP lesion.",
    "Could be thoracic outlet syndrome.",
    "It may be Parsonage-Turner neuropathy.",
    "可能是肩周炎。",
]


@pytest.mark.parametrize("msg", REJECT)
def test_condition_outside_the_path_is_rejected_twice_then_llm_invalid(tmp_path, msg):
    svc, fake = service(tmp_path, script=[_care(msg), _care(msg)])
    r = run(svc, req(**DONE))
    assert blocked(r)
    assert r["llm_called"] is True and len(fake.calls) == 2
    # the retry prompt tells the model what was wrong
    assert "rejected" in fake.calls[1][1]


def test_one_bad_attempt_then_a_good_one(tmp_path):
    good = "Gradual shoulder pain is most often about the rotator cuff tendons."
    svc, fake = service(tmp_path, script=[_care("This is bursitis."), _care(good)])
    r = run(svc, req(**DONE))
    assert r["reply"]["kind"] == "care_paths" and r["reply"]["text"] == good
    assert len(fake.calls) == 2
    assert r["budget"]["spent_today_usd"] > 0  # both attempts charged


def test_condition_named_by_the_path_is_allowed_only_while_that_path_shows(tmp_path):
    # "sprain" is in the ankle path's intro; the shoulder path does not name it
    svc, _ = service(tmp_path, script=[_care("Most of these are a sprain."), _care("A sprain.")])
    assert blocked(run(svc, req(**DONE)))
    ankle = dict(
        answers={"Q1": ["ankle"], "Q2": ["injury"]}, history=["I twisted my ankle"], text="yes"
    )
    svc2, _ = service(tmp_path / "b", script=[_care("Most twisted ankles are a sprain.")])
    assert run(svc2, req(**ankle))["reply"]["kind"] == "care_paths"


def test_clarify_lead_in_with_no_path_shown_may_name_no_condition(tmp_path):
    bad = llm(message="Rotator cuff problems are common. Did it start with an injury?")
    svc, _ = service(tmp_path, script=[bad, bad])
    assert blocked(run(svc, req()))


@pytest.mark.parametrize(
    "msg",
    [
        "I understand. Did it start with a fall?",
        "Thanks for sharing that. Did it start with a fall?",
        "Got it — did it start with a fall?",
        "That makes sense. Did it start with a fall?",
        "Sorry to hear that. Did it start with a fall?",
        "明白了。是受伤开始的吗？",
    ],
)
def test_stock_acknowledgement_openers_are_rejected(tmp_path, msg):
    svc, fake = service(tmp_path, script=[llm(message=msg), llm(message=msg)])
    assert blocked(run(svc, req())) and len(fake.calls) == 2


def test_one_question_per_turn_and_chips_verbatim(tmp_path):
    svc, _ = service(tmp_path, script=[llm()])
    rep = run(svc, req())["reply"]
    assert rep["kind"] == "clarify" and len(rep["questions"]) == 1
    q = rep["questions"][0]
    assert q["question_id"] == "Q2"
    assert q["text"]["en"] == "Did it start with an injury, like a fall, a twist or a hit?"


def test_model_question_outside_the_allowed_set_is_replaced_by_the_codes_choice(tmp_path):
    # Q12 is a heartburn question; for a shoulder the distinguishing question is Q2
    svc, _ = service(tmp_path, script=[llm(next_question_id="Q12", message="Any heartburn?")])
    rep = run(svc, req())["reply"]
    assert rep["questions"][0]["question_id"] == "Q2"
    assert rep["lead_in"] is None  # the model's sentence was about another question


def test_first_turn_is_a_question_unless_specific(tmp_path):
    # vague first message: the model's path guess is dropped on turn 1 -> clarify, no candidates
    vague = llm(
        understood=[], next_question_id="Q1", message="Where is the problem?",
        path_ids=["knee_chronic_v1"],
    )  # fmt: skip
    svc, _ = service(tmp_path, script=[vague])
    rep = run(svc, req(text="something hurts"))["reply"]
    assert rep["kind"] == "clarify" and rep["candidates"] == []
    assert rep["questions"][0]["question_id"] == "Q1"


def test_specific_first_message_shows_prices_from_turn_one(tmp_path):
    specific = llm(
        understood=[
            {"question_id": "Q1", "value": "shoulder", "evidence": "my shoulder"},
            {"question_id": "Q2", "value": "no_injury", "evidence": "no injury"},
        ],
        next_question_id="Q5",
        message="Does it catch or click with pain?",
    )
    svc, _ = service(tmp_path, script=[specific])
    rep = run(svc, req(text="my shoulder slowly started hurting, no injury"))["reply"]
    assert rep["kind"] == "clarify"
    (c,) = rep["candidates"]
    assert c["match"] == "ai_ranked" and c["because"] == []  # read by the model: no listed reason
    assert rep["copy_keys"] == list(CARE_PATH_COPY_KEYS)


def test_guard_shapes_unit():
    assert guard.condition_like_words("It is not a diagnosis") == set()
    assert "osteonecrosis" in guard.condition_like_words("maybe osteonecrosis")
    guard.check_condition_shapes("a stretched or torn ligament", "a stretched or torn ligament")
    with pytest.raises(guard.GuardError):
        guard.check_condition_shapes("a torn tendon", "shoulder pain")
