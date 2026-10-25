"""Adversarial tests for the free-text red-flag gate, and one-way escalation.

Data:
  data/redflags/adversarial.json       labelled phrases written before the gate was expanded;
                                       expect = the exact disposition (null = must not fire)
  data/redflags/holdout_blind_v1.json  written blind by an independent agent; expect = minimum
                                       disposition (a higher rank passes), null = must not fire

The chat gate runs before any care path is known, so everything here uses areas=None.

The rule tests at the bottom each kill one mutant (see the docstrings): most-urgent-wins,
negation scope, one-way escalation, crisis_988 routing.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.care_paths import redflags as R
from app.care_paths.loader import DATA_ROOT

ADV = json.loads((DATA_ROOT / "redflags" / "adversarial.json").read_text())["cases"]
HOLD = json.loads((DATA_ROOT / "redflags" / "holdout_blind_v1.json").read_text())["cases"]

# Holdout negatives that fire on purpose: crisis language is never negated (ambivalent statements
# screen positive). Edit by hand only; the list must not grow silently.
HOLDOUT_KNOWN_FP = {
    "never had suicidal thoughts, just need a therapist copay",
    "没想过自杀，只是想找心理咨询价格",
}


def _ids(cases):
    return [f"{c['category']}:{c['text'][:40]}" for c in cases]


# --------------------------------------------------------------------------- phrase sets


@pytest.mark.parametrize("case", ADV, ids=_ids(ADV))
def test_adversarial_exact(bundle, case):
    r = R.screen_text(case["text"], bundle.redflags)
    assert r.disposition == case["expect"], f"{case['text']!r}: {r.disposition} via {r.evidence}"


@pytest.mark.parametrize("case", HOLD, ids=_ids(HOLD))
def test_blind_holdout(bundle, case):
    key = R.rank_key(bundle.redflags)
    r = R.screen_text(case["text"], bundle.redflags)
    if case["expect"] is None:
        if case["text"] in HOLDOUT_KNOWN_FP:
            assert r.disposition is not None, "known FP no longer fires: remove it from the list"
        else:
            assert r.disposition is None, f"{case['text']!r}: false positive via {r.evidence}"
    else:
        assert r.disposition is not None, f"{case['text']!r}: missed"
        assert key[r.disposition][0] >= key[case["expect"]][0], (case["text"], r.disposition)


def test_phrase_set_shape():
    cats = {c["category"] for c in ADV}
    assert {
        "negation_true",
        "negation_trap",
        "msk",
        "figurative",
        "third_person",
        "typo",
        "mixed",
    } <= cats
    assert {"crisis_direct", "crisis_indirect", "verified_miss"} <= cats
    assert {c["lang"] for c in ADV} == {"en", "zh", "mixed"}
    assert len(ADV) >= 200 and len(HOLD) >= 150


def test_every_free_text_flag_fires_somewhere(bundle):
    """Every non-checklist-only emergency flag is exercised by at least one adversarial phrase."""
    fired: set[str] = set()
    for c in ADV:
        fired |= set(R.screen_text(c["text"], bundle.redflags).flag_ids)
    new = {
        "rf_suicide_self_harm",
        "rf_overdose",
        "rf_breathing",
        "rf_breathing_mild",
        "rf_stroke",
        "rf_thunderclap_headache",
        "rf_unresponsive_seizure",
        "rf_chest_pain_alone",
        "rf_cauda_equina",
    }
    assert new <= fired, new - fired


def test_every_term_parses(bundle):
    for f in bundle.redflags.flags:
        for pattern in f.patterns:
            for group in pattern:
                for raw in group:
                    t = R.parse_term(raw)
                    assert t.left and (t.right is None or t.right), (f.id, raw)


# --------------------------------------------------------------------------- verified misses


@pytest.mark.parametrize(
    ("text", "disposition", "flag"),
    [
        ("my chest hurts", "call_911", "rf_chest_pain_alone"),
        ("I want to kill myself", "crisis_988", "rf_suicide_self_harm"),
        ("worst headache of my life", "call_911", "rf_thunderclap_headache"),
        ("I cant feel my groin", "er_today", "rf_cauda_equina"),
    ],
)
def test_verified_misses_are_caught(bundle, text, disposition, flag):
    r = R.screen_text(text, bundle.redflags)
    assert r.disposition == disposition and flag in r.flag_ids, r


# --------------------------------------------------------------------------- rule: most urgent wins


def test_most_urgent_wins(bundle):
    """Mutant: _pick takes min instead of max -> 'routine' would win here."""
    r = R.screen_text(
        "back pain, I lost weight without trying, and now my chest hurts", bundle.redflags
    )
    assert {"rf_back_risk_history", "rf_chest_pain_alone"} <= set(r.flag_ids)
    assert r.disposition == "call_911"
    r = R.screen_checklist(["rf_back_risk_history", "rf_septic_joint"], bundle.redflags)
    assert r.disposition == "er_today"


def test_tie_between_911_and_988_goes_to_911(bundle):
    """Same rank: the disposition listed first in redflags.json (call_911) is shown.
    Mutant: tie-break flipped -> crisis_988."""
    r = R.screen_text("i want to die and i cant breathe", bundle.redflags)
    assert {"rf_suicide_self_harm", "rf_breathing"} <= set(r.flag_ids)
    assert r.disposition == "call_911"


# --------------------------------------------------------------------------- rule: negation scope


@pytest.mark.parametrize(
    ("text", "fires"),
    [
        ("no chest pain", False),
        ("没有胸痛", False),
        ("my chest doesn't hurt", False),
        ("胸口不痛", False),
        ("not sure if it's chest pain", True),
        ("no idea why but my chest hurts", True),
        ("no fever, but chest pain", True),
        ("不知道是不是胸痛", True),
        ("没有胸痛，但是喘不上气", True),
        ("ive never had chest pain this bad", True),
    ],
)
def test_negation_scope(bundle, text, fires):
    """Mutants: negation window ignores clause breaks (no fever, but chest pain -> missed);
    uncertainty treated as negation (not sure if -> missed); in-gap negation ignored
    (chest doesnt hurt -> fires)."""
    r = R.screen_text(text, bundle.redflags)
    assert (r.disposition is not None) is fires, (text, r)


# --------------------------------------------------------------------------- rule: crisis routing


@pytest.mark.parametrize(
    "text",
    [
        "I want to kill myself",
        "i dont want to be here anymore",
        "不想活了",
        "i dont want to kill myself but i keep thinking about it",
    ],
)
def test_crisis_routes_to_988(bundle, text):
    """Mutant: rf_suicide_self_harm.disposition -> call_911 (or crisis terms negatable)."""
    r = R.screen_text(text, bundle.redflags)
    assert r.disposition == "crisis_988" and "rf_suicide_self_harm" in r.flag_ids, r


def test_crisis_disposition_copy_mentions_988_and_911(bundle):
    d = {x.id: x for x in bundle.redflags.dispositions}["crisis_988"]
    assert "988" in d.headline.en and "988" in d.headline.zh
    assert "911" in d.text.en and "911" in d.text.zh
    assert d.rank == {x.id: x for x in bundle.redflags.dispositions}["call_911"].rank


def test_figurative_killing_is_not_crisis(bundle):
    assert R.screen_text("this bill is killing me", bundle.redflags).disposition is None


# --------------------------------------------------------------------------- rule: one-way escalation


def _code(bundle, text):
    return R.screen_text(text, bundle.redflags)


@pytest.mark.parametrize("llm", ["routine", "seen_today", "er_today", None])
@pytest.mark.parametrize(
    ("text", "code_disp"),
    [("my chest hurts", "call_911"), ("I want to kill myself", "crisis_988")],
)
def test_llm_can_never_lower_a_top_code_flag(bundle, text, code_disp, llm):
    """Mutant: combine returns the LLM value whenever it is valid -> routine wins."""
    code = _code(bundle, text)
    assert code.disposition == code_disp
    out = R.combine(code, llm, bundle.redflags)
    assert out.disposition == code_disp
    assert out.flag_ids == code.flag_ids and not out.escalated_by_llm


def test_llm_does_not_swap_equal_rank_pages(bundle):
    code = _code(bundle, "I want to kill myself")
    assert R.combine(code, "call_911", bundle.redflags).disposition == "crisis_988"
    code = _code(bundle, "my chest hurts")
    assert R.combine(code, "crisis_988", bundle.redflags).disposition == "call_911"


def test_llm_can_raise(bundle):
    code = _code(bundle, "my stool has been black for two days")
    assert code.disposition == "seen_today"
    out = R.combine(code, "call_911", bundle.redflags)
    assert out.disposition == "call_911" and out.escalated_by_llm
    assert out.flag_ids == code.flag_ids


def test_llm_can_raise_from_nothing(bundle):
    code = _code(bundle, "my shoulder clicks when I rotate my arm")
    assert code.disposition is None
    out = R.combine(code, "crisis_988", bundle.redflags)
    assert out.disposition == "crisis_988" and out.escalated_by_llm and out.flag_ids == []


@pytest.mark.parametrize("bad", ["CALL_911", "emergency", "", "safe", "none"])
def test_unknown_llm_values_are_ignored_and_logged(bundle, bad, caplog):
    code = _code(bundle, "knee pain for 3 weeks")
    with caplog.at_level(logging.WARNING, logger="app.care_paths.redflags"):
        out = R.combine(code, bad, bundle.redflags)
    assert out is code
    assert "invalid LLM disposition" in caplog.text


def test_unknown_llm_value_cannot_clear_a_code_flag(bundle):
    code = _code(bundle, "my chest hurts")
    assert R.combine(code, "clear", bundle.redflags).disposition == "call_911"
