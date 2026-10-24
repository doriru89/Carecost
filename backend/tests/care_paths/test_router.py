"""Deterministic routing: red flags stop first; answers pick exactly one path or card."""

from __future__ import annotations

from app.care_paths import router


def test_red_flag_stops_before_any_path(bundle):
    r = router.route({"Q0": ["rf_cardiac"], "Q1": "shoulder", "Q2": "no_injury"}, bundle)
    assert r.kind == "stop" and r.target == "call_911"


def test_chronic_shoulder(bundle):
    r = router.route({"Q0": [], "Q1": "shoulder", "Q2": "no_injury"}, bundle)
    assert (r.kind, r.target) == ("path", "shoulder_chronic_clicking_v1")


def test_hmo_turns_on_referral_layer(bundle):
    r = router.route(
        {"Q0": [], "Q1": "shoulder", "Q2": "no_injury", "Q14": "hmo_referral_required"}, bundle
    )
    assert r.layer0_referral is True
    r2 = router.route({"Q0": [], "Q1": "shoulder", "Q2": "no_injury", "Q14": "ppo"}, bundle)
    assert r2.layer0_referral is False


def test_tier_modifiers_apply(bundle):
    base = router.route({"Q0": [], "Q1": "shoulder", "Q2": "no_injury"}, bundle)
    bumped = router.route(
        {"Q0": [], "Q1": "shoulder", "Q2": "no_injury", "Q4": "yes_still_bad"}, bundle
    )
    assert base.tiers["tendon_scan_mri"] == "possible"
    assert bumped.tiers["tendon_scan_mri"] == "likely"


def test_screening_vs_diagnostic_colonoscopy(bundle):
    screen = router.route(
        {"Q0": [], "Q1": "screening", "Q8": "age_45_59", "Q11": "none", "Q13": "none"}, bundle
    )
    assert screen.target == "colon_screening_v1"
    fit = router.route(
        {
            "Q0": [],
            "Q1": "screening",
            "Q8": "age_60_75",
            "Q11": "none",
            "Q13": "positive_stool_test",
        },
        bundle,
    )
    assert fit.target == "colon_screening_v1"
    diag = router.route(
        {"Q0": [], "Q1": "bowel", "Q8": "age_45_59", "Q11": "yes"},
        bundle,
    )
    assert diag.target == "colon_diagnostic_v1"


def test_recent_normal_colonoscopy_gets_not_due_card(bundle):
    r = router.route(
        {"Q0": [], "Q1": "screening", "Q8": "age_45_59", "Q11": "none", "Q13": "normal_within_10y"},
        bundle,
    )
    assert (r.kind, r.target) == ("card", "colon_not_due_yet")


def test_unknown_area_falls_to_card(bundle):
    r = router.route({"Q0": [], "Q1": "other"}, bundle)
    assert r.kind == "card"
