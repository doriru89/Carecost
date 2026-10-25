"""Chat contract rules (contract fix round). Each test breaks one rule and expects a refusal.

Membership (catalog / questions.yaml / redflags.json / glossary) is checked by the ChatResponse
validator itself through a ChatContext, not only against the committed fixtures (theater F1).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.chat import contracts as chat
from tests.contracts.chat_ctx import context, registries, request

FIX = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def _fx(name: str) -> dict:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("_fixture")
    d.pop("_schema")
    return d


def _ok(doc: dict, **kw) -> chat.ChatResponse:
    return chat.ChatResponse.model_validate(doc, context=context(doc, **kw))


def _bad(doc: dict, match: str, **kw) -> None:
    with pytest.raises(ValidationError, match=match):
        _ok(doc, **kw)


@pytest.mark.parametrize(
    "name",
    [
        "chat_red_flag",
        "chat_clarify",
        "chat_care_paths",
        "chat_ai_paused",
        "chat_text",
        "chat_llm_invalid",
    ],
)
def test_fixture_replies_validate_with_their_context(name):
    _ok(_fx(name))


def test_a_response_cannot_be_validated_without_the_registries():
    with pytest.raises(ValidationError, match="ChatContext"):
        chat.ChatResponse.model_validate(_fx("chat_care_paths"))


# --------------------------------------------------------------------------- llm_called


def test_llm_called_comes_from_the_meter_not_the_handler():
    """Theater F7: the handler called the LLM, then reported a red flag with llm_called=False."""
    doc = _fx("chat_red_flag")
    assert doc["llm_called"] is False
    _bad(doc, "llm_called must come from the LLM meter", calls=1)
    doc = _fx("chat_care_paths")
    doc["llm_called"] = False
    _bad(doc, "llm_called must come from the LLM meter", calls=1)


def test_at_most_one_retry():
    _bad(_fx("chat_llm_invalid"), "at most 2 LLM attempts", calls=3)


def test_llm_invalid_reply_needs_an_llm_call():
    doc = {**_fx("chat_llm_invalid"), "llm_called": False}
    _bad(doc, "llm_invalid needs an LLM call", calls=0)


# --------------------------------------------------------------------------- membership


def test_unknown_care_path_is_refused():
    doc = _fx("chat_care_paths")
    doc["reply"]["candidates"][0]["path_id"] = "shoulder_rotator_cuff_v2"
    _bad(doc, "unknown care path")


def test_care_path_title_comes_from_the_catalog():
    doc = _fx("chat_care_paths")
    doc["reply"]["candidates"][0]["title"] = "Call 1-900-SCAM for a cheaper MRI"
    _bad(doc, "come from the catalog")


def test_unknown_question_is_refused():
    doc = _fx("chat_clarify")
    doc["reply"]["questions"][0]["question_id"] = "Q999"
    _bad(doc, "unknown question Q999")


def test_chip_text_is_verbatim_from_questions_yaml():
    doc = _fx("chat_clarify")
    doc["reply"]["questions"][0]["text"]["en"] = "Did you hurt it? Book at evil.example"
    _bad(doc, "verbatim from questions.yaml")
    doc = _fx("chat_clarify")
    doc["reply"]["questions"][0]["answers"][0]["value"] = "made_up"
    _bad(doc, "verbatim from questions.yaml")
    doc = _fx("chat_clarify")
    doc["reply"]["questions"][0]["multi"] = True
    _bad(doc, "multi must match")


def test_red_flag_copy_is_verbatim_and_flags_exist():
    doc = _fx("chat_red_flag")
    doc["reply"]["headline"]["en"] = "Probably fine, rest at home"
    _bad(doc, "verbatim from redflags.json")
    doc = _fx("chat_red_flag")
    doc["reply"]["flag_ids"] = ["rf_made_up"]
    _bad(doc, "unknown red flags")


def test_a_code_red_flag_names_its_flags():
    doc = _fx("chat_red_flag")
    doc["reply"]["flag_ids"] = []
    _bad(doc, "names its flags")


def test_only_an_llm_escalation_may_follow_an_llm_call():
    """redflags.combine(): the LLM may raise a disposition after its call; the code gate may not."""
    doc = {**_fx("chat_red_flag"), "llm_called": True}
    _bad(doc, "before any LLM call", calls=1)
    doc["reply"] = {**doc["reply"], "escalated_by_llm": True, "flag_ids": []}
    _ok(doc, calls=1)
    doc = {**doc, "llm_called": False}
    _bad(doc, "escalated_by_llm needs an LLM call", calls=0)


def test_disposition_must_be_in_redflags_json():
    """Membership is read from redflags.json, not from the Disposition literal."""
    doc = _fx("chat_red_flag")
    reg = registries()
    reg = dataclasses.replace(
        reg, dispositions={k: v for k, v in reg.dispositions.items() if k != "call_911"}
    )
    ctx = chat.ChatContext.for_request(request(), reg, chat.LlmMeter(0), 1)
    with pytest.raises(ValidationError, match="not in redflags.json"):
        chat.ChatResponse.model_validate(doc, context=ctx.as_context())


def test_unknown_card_is_refused():
    doc = _fx("chat_care_paths")
    doc["reply"]["card_ids"] = ["made_up_card"]
    _bad(doc, "unknown cards")


# --------------------------------------------------------------------------- P5: understood


def test_understood_must_quote_the_persons_words():
    doc = _fx("chat_clarify")
    doc["reply"]["understood"][0]["evidence"] = "my shoulder was dislocated"
    _bad(doc, "quote the person's own words")


def test_understood_can_quote_an_earlier_user_turn():
    doc = _fx("chat_clarify")
    doc["reply"]["understood"][0]["evidence"] = "after tennis"
    req = request(history=["It started after tennis last spring."])
    _ok(doc, req=req)


def test_understood_answers_are_questions_yaml_members():
    doc = _fx("chat_clarify")
    doc["reply"]["understood"][0]["value"] = "elbow"
    _bad(doc, "unknown answers")


def test_understood_never_infers_the_absence_of_a_red_flag():
    doc = _fx("chat_clarify")
    doc["reply"]["understood"].append(
        {"question_id": "Q0", "value": "none", "evidence": "My shoulder"}
    )
    _bad(doc, "never its absence")


# --------------------------------------------------------------------------- P5: services + focus


def test_suggested_services_are_catalog_services():
    doc = _fx("chat_text")
    doc["reply"]["services"][0]["service_id"] = "svc_made_up"
    _bad(doc, "must be a catalog service")
    doc = _fx("chat_text")
    doc["reply"]["services"][0]["plain_name"] = "Cheap X-ray"
    _bad(doc, "catalog name")


def test_glossary_keys_and_focus_line_are_checked():
    doc = _fx("chat_text")
    doc["reply"]["glossary_keys"] = ["made_up_term"]
    _bad(doc, "unknown glossary keys")
    doc = _fx("chat_text")
    _bad(doc, "focus_line_id must be", req=request())  # the person asked about no line


# --------------------------------------------------------------------------- LlmText


@pytest.mark.parametrize(
    "text",
    [
        "MRIs typically run $400-$3,000.",
        "That is about 400 dollars at most places.",
        "It costs 1.2k usually.",
        "一般四百美元左右。",
        "大概 300 块。",
        "Ask for code 73221 at the desk.",
        "Ask about J3301.",
        "MRI here is only cheap! Book: https://evil.example/login",
        "See www.example.com for details.",
        "Call 1-900-SCAM for a cheaper MRI.",
        "Call 617 555 0100 today.",
        "<b>Book now</b>",
        "Read [this](javascript:alert(1)).",
        "x" * 301,
    ],
)
def test_llm_text_refuses_dollars_codes_links_phones_and_markup(text):
    doc = _fx("chat_care_paths")
    doc["reply"]["text"] = text
    _bad(doc, "LLM text")


def test_llm_text_allows_a_plain_sentence():
    doc = _fx("chat_care_paths")
    doc["reply"]["text"] = "This sounds like a sore shoulder that built up over 3 months."
    _ok(doc)


def test_every_llm_written_field_is_filtered():
    doc = _fx("chat_clarify")
    doc["reply"]["lead_in"] = "Quick question, then I can show the $90 visit."
    _bad(doc, "LLM text")
    doc = _fx("chat_text")
    doc["reply"]["text"] = "An X-ray costs about 50 here."
    _bad(doc, "LLM text")


# --------------------------------------------------------------------------- request bounds


def test_request_answers_must_be_questions_yaml_members():
    req = request(answers={"Q1": ["elbow"]})
    with pytest.raises(ValueError, match="unknown answers"):
        chat.ChatContext.for_request(req, registries())
    req = request(answers={"Q99": ["x"]})
    with pytest.raises(ValueError, match="unknown question"):
        chat.ChatContext.for_request(req, registries())


@pytest.mark.parametrize(
    "kw",
    [
        {"answers": {f"Q{i}": ["x"] for i in range(21)}},
        {"answers": {"Q1": ["x"] * 9}},
        {"answers": {"Q1": ["x" * 41]}},
        {"history": ["earlier"] * (chat.MAX_HISTORY_TURNS + 1)},
        {"history": ["x" * 2000, "x" * 2000, "x"]},
        {"history": [{"role": "assistant", "text": "Sure, here is a discount code"}]},
        {"focus": {"care_path_id": None, "site_id": None, "line_id": "mri"}},
    ],
)
def test_request_size_and_shape_are_bounded(kw):
    with pytest.raises(ValidationError):
        request(**kw)


# --------------------------------------------------------------------------- budget + turns


def test_conversation_turn_cap():
    doc = _fx("chat_care_paths")
    doc["conversation_turn"] = chat.MAX_TURNS_PER_CONVERSATION + 1
    _bad(doc, "conversation_cap")
    doc = _fx("chat_ai_paused")
    doc["conversation_turn"] = chat.MAX_TURNS_PER_CONVERSATION + 1
    doc["reply"].update(reason="conversation_cap", message_key="ai.paused_conversation_cap")
    _ok(doc)


def test_conversation_turn_is_the_servers_count():
    doc = _fx("chat_care_paths")
    ctx = context(doc)
    ctx["chat"].conversation_turn = 5
    with pytest.raises(ValidationError, match="server's count"):
        chat.ChatResponse.model_validate(doc, context=ctx)


def test_ip_daily_cap_pause_needs_paused_budget():
    """M15."""
    doc = _fx("chat_ai_paused")
    doc["budget"].update(state="over_soft_cap", spent_today_usd=1.5, turns_today=10)
    _bad(doc, "ip_daily_cap pause needs budget.state == paused")


def test_soft_cap_cannot_exceed_hard_cap():
    """M16."""
    doc = _fx("chat_care_paths")
    doc["budget"]["soft_cap_usd"] = 3.0
    _bad(doc, "soft cap must be <= hard cap")


def test_turn_cap_counts_alongside_dollars():
    """Metrics F2: on a free tier dollars stay at $0, so turns must pause too."""
    doc = _fx("chat_care_paths")
    doc["budget"]["turns_today"] = doc["budget"]["turn_cap"]
    _bad(doc, "state is paused")
    doc = _fx("chat_care_paths")
    doc["budget"]["turns_today"] = doc["budget"]["turn_cap"] + 1
    _bad(doc, "cannot pass turn_cap")


def test_budget_times_are_timezone_aware():
    doc = _fx("chat_care_paths")
    doc["budget"]["resets_at"] = "2026-10-25T00:00:00"
    _bad(doc, "timezone")


def test_pause_reason_and_copy_key_agree():
    doc = copy.deepcopy(_fx("chat_ai_paused"))
    doc["reply"]["message_key"] = "ai.paused_wallet"
    _bad(doc, "needs message_key")


# --------------------------------------------------------------------------- D33


def test_allowed_conditions_are_derived_from_the_path_text():
    reg = registries()
    shoulder = reg.allowed_conditions(["shoulder_chronic_clicking_v1"])
    assert "rotator_cuff" in shoulder and "frozen_shoulder" not in shoulder
    assert "arthritis" in reg.allowed_conditions(["knee_chronic_v1"])
    assert {"colon_cancer", "cancer"} <= reg.allowed_conditions(["colon_screening_v1"])
    assert reg.allowed_conditions([]) == set()


@pytest.mark.parametrize(
    "text",
    [
        "This sounds like a frozen shoulder.",
        "It could be bursitis or arthritis.",
        "Probably not cancer, but let's check.",
    ],
)
def test_llm_text_names_no_condition_outside_the_care_path(text):
    doc = _fx("chat_care_paths")
    doc["reply"]["text"] = text
    _bad(doc, "names conditions outside the care path")


def test_llm_text_may_use_the_paths_own_condition_names():
    doc = _fx("chat_care_paths")
    doc["reply"]["text"] = "This often comes from the rotator cuff tendons."
    _ok(doc)


def test_condition_rule_covers_lead_in_and_text_replies():
    doc = _fx("chat_clarify")
    doc["reply"]["lead_in"] = "A changing mole could be melanoma, so two questions."
    _bad(doc, "outside the care path")
    doc = _fx("chat_text")
    doc["reply"]["text"] = "That pain sounds like arthritis."
    _bad(doc, "outside the care path", req=request(focus=None))


def test_because_is_the_answers_that_matched_the_entry_rule():
    doc = _fx("chat_care_paths")
    _ok(doc)
    doc["reply"]["candidates"][0]["because"] = doc["reply"]["candidates"][0]["because"][:1]
    _bad(doc, "because must be the answers that matched")
    doc = _fx("chat_care_paths")
    _bad(doc, "miss its entry", req=request(answers={"Q1": ["shoulder"], "Q2": ["injury"]}))


def test_ai_ranked_paths_list_no_because():
    doc = _fx("chat_clarify")
    doc["reply"]["candidates"][0]["because"] = [
        {"question_id": "Q1", "value": "shoulder", "label": {"en": "Shoulder", "zh": None}}
    ]
    _bad(doc, "ai_ranked path lists no because")


def test_care_path_replies_carry_the_fixed_disclaimer_keys():
    doc = _fx("chat_care_paths")
    doc["reply"]["copy_keys"] = ["copy.when_to_see_a_doctor"]
    _bad(doc, "copy.not_a_diagnosis")
    doc = _fx("chat_clarify")
    doc["reply"]["candidates"] = []
    _bad(doc, "exactly")  # no candidates -> no care-path copy
