"""R19 / P12: the stomach ache and rash paths route from chips, carry their red flags, stay pending review."""

from __future__ import annotations

import pytest

from app.care_paths import redflags
from app.care_paths.router import route
from app.care_paths.validator import validate_all

NEW = {"stomach_ache_v1": "belly_pain", "rash_v1": "rash"}


@pytest.mark.parametrize("pid,answer", NEW.items())
def test_routes_from_one_chip(bundle, pid, answer):
    r = route({"Q0": [], "Q1": answer}, bundle)
    assert (r.kind, r.target) == ("path", pid)
    assert r.tiers["visit"] == "certain"


@pytest.mark.parametrize("pid", NEW)
def test_clean_cited_and_pending(bundle, pid):
    p = bundle.paths[pid]
    assert p.review.status == "pending_austin" and not p.review.reviewers
    assert [v for v in validate_all(bundle) if v.where.startswith(pid)] == []
    for s in p.steps:
        assert any(c.claim_field == "why" for c in s.citations), s.id


def test_q1_labels_in_both_languages(bundle):
    q1 = {a.value: a for q in bundle.questions.questions if q.id == "Q1" for a in q.answers}
    assert (
        q1["belly_pain"].label.en == "Stomach ache or belly pain"
        and "肚子疼" in q1["belly_pain"].label.zh
    )
    assert q1["rash"].label.en == "A rash" and "起疹子" in q1["rash"].label.zh


def test_self_pay_label(bundle):
    q14 = {a.value: a for q in bundle.questions.questions if q.id == "Q14" for a in q.answers}
    assert q14["cash"].label.en == "Self-pay (no insurance)"
    assert q14["cash"].label.zh == "自费（无保险）"


def test_new_checklists(bundle):
    ab = {f.id for f in redflags.checklist_for_area("gi_abdomen", bundle.redflags)}
    assert {"rf_gi_bleed_heavy", "rf_gi_bleed_dark_stool", "rf_abdomen_severe",
            "rf_abdomen_rigid_or_pregnant", "rf_abdomen_fever_or_moving"} <= ab  # fmt: skip
    rash = {f.id for f in redflags.checklist_for_area("skin_rash", bundle.redflags)}
    assert {"rf_non_blanching_rash", "rf_rash_blistering", "rf_rash_fever",
            "rf_allergic_airway"} <= rash  # fmt: skip
    # the non-fading-rash flag stays out of every other checklist
    for area in bundle.redflags.path_areas:
        if area != "skin_rash":
            ids = {f.id for f in redflags.checklist_for_area(area, bundle.redflags)}
            assert "rf_non_blanching_rash" not in ids, area
