"""V1-V10 content rules (clinical-sources.md §5.3). Each rule runs on the real data and must be clean,
and each rule has a negative case proving it actually catches the failure it exists for."""

from __future__ import annotations

import datetime as dt
import warnings

import pytest

from app.care_paths import validator
from app.care_paths.models import Citation, Reviewer


def _fmt(violations) -> str:
    return "\n".join(str(v) for v in violations[:40])


@pytest.mark.parametrize("rule", ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V10"])
def test_rule_clean_on_real_data(bundle, rule):
    violations = validator.RULES[rule](bundle)
    assert not violations, _fmt(violations)


def _first_step(b, path_id="shoulder_chronic_clicking_v1", step_id=None):
    path = b.paths[path_id]
    if step_id is None:
        return path.steps[0]
    return next(s for s in path.steps if s.id == step_id)


# V1 -- every why has guideline/government evidence
def test_v1_catches_why_backed_only_by_secondary(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.citations = [c for c in step.citations if c.claim_field != "why"]
    assert validator.RULES["V1"](mutable_bundle)


def test_v1_catches_clinical_skip_without_evidence(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.when_skipped_basis = "clinical"
    step.citations = [c for c in step.citations if c.claim_field != "when_skipped"]
    assert validator.RULES["V1"](mutable_bundle)


# V2 -- quotes are <=15 words and verbatim in the stored snapshot
def test_v2_catches_fabricated_quote(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    c = step.citations[0]
    step.citations[0] = Citation(
        **{**c.model_dump(), "quote": "Radiography is always required first"}
    )
    assert validator.RULES["V2"](mutable_bundle)


def test_v2_catches_citation_year_drift(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    c = step.citations[0]
    step.citations[0] = Citation(**{**c.model_dump(), "year": c.year - 4})
    assert validator.RULES["V2"](mutable_bundle)


def test_v2_catches_rating_that_disagrees_with_acr_table(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.appropriateness.rating = "MBA"
    assert validator.RULES["V2"](mutable_bundle)


# V3 -- likelihood bounded by appropriateness
def test_v3_catches_may_be_appropriate_marked_likely(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="steroid_injection")
    assert step.appropriateness.rating == "MBA"
    step.likelihood_tier = "likely"
    assert validator.RULES["V3"](mutable_bundle)


def test_v3_catches_modifier_that_breaks_the_bound(mutable_bundle):
    path = mutable_bundle.paths["shoulder_chronic_clicking_v1"]
    mod = path.tier_modifiers[0]
    mod.tier = "certain"
    mod.appropriateness = None
    step = next(s for s in path.steps if s.id == mod.step)
    step.appropriateness.rating = "MBA"
    assert validator.RULES["V3"](mutable_bundle)


def test_v3_cap_table():
    assert validator.max_tier("UA") == "certain"
    assert validator.max_tier("MBA") == "possible"
    assert validator.max_tier("UNA") == "rare"


# V4 -- "after normal radiographs" steps come after the X-ray
def test_v4_catches_mri_without_xray_before(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="tendon_scan_mri")
    step.after = []
    assert validator.RULES["V4"](mutable_bundle)


# V5 -- every CPT exists in the 2026 registry; every step priced or explicitly unpriced
def test_v5_catches_unknown_code(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.cpts[0].code = "99999"
    assert validator.RULES["V5"](mutable_bundle)


def test_v5_catches_step_with_no_price_and_no_flag(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.cpts = []
    step.no_price = False
    assert validator.RULES["V5"](mutable_bundle)


# V6 -- no raw codes, no unglossed jargon, plain name leads (D8)
def test_v6_catches_raw_code_in_copy(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.plain.why = step.plain.why + " Billed as 73030."
    assert validator.RULES["V6"](mutable_bundle)


def test_v6_catches_jargon_without_glossary(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="xray")
    step.plain.what = step.plain.what + " Sometimes an MRI follows."
    step.glossary = [g for g in step.glossary if g != "mri"]
    assert validator.RULES["V6"](mutable_bundle)


def test_v6_catches_technical_term_as_main_name(mutable_bundle):
    step = _first_step(mutable_bundle, step_id="tendon_scan_mri")
    step.plain.name = "Shoulder MRI"
    assert validator.RULES["V6"](mutable_bundle)


# V7 -- red flags screened before entry
def test_v7_catches_missing_global_flag(mutable_bundle):
    path = mutable_bundle.paths["shoulder_chronic_clicking_v1"]
    path.red_flags = [f for f in path.red_flags if f != "rf_cardiac"]
    assert validator.RULES["V7"](mutable_bundle)


# V8 -- two-person rule
def test_v8_catches_ai_reviewer(mutable_bundle):
    path = mutable_bundle.paths["shoulder_chronic_clicking_v1"]
    fake = Reviewer.model_construct(
        id="ai:claude-opus", kind="human_clinician", at=dt.date(2026, 10, 24), verdict="ok"
    )
    path.review.reviewers.append(fake)
    assert validator.RULES["V8"](mutable_bundle)


def test_v8_catches_approved_status_with_no_reviewers(mutable_bundle):
    path = mutable_bundle.paths["shoulder_chronic_clicking_v1"]
    path.review.status = "approved"
    assert validator.RULES["V8"](mutable_bundle)


# V9 -- freshness sweep (warning, not failure)
def test_v9_every_source_has_freshness_fields(bundle):
    for sid, src in bundle.sources.items():
        assert src.checked_at is not None, sid
        assert src.recheck_after_days > 0, sid


def test_v9_flags_stale_sources_as_warning(bundle):
    future = dt.date.today() + dt.timedelta(days=5000)
    stale = validator.stale_sources(bundle, today=future)
    assert stale, "every source should be stale 5000 days from now"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        validator.warn_stale(bundle, today=future)
    assert any("recheck" in str(w.message) for w in caught)


def test_v9_current_staleness_report(bundle):
    stale = validator.stale_sources(bundle)
    if stale:
        warnings.warn(f"V9: sources past recheck date: {sorted(stale)}", stacklevel=1)


# V10 -- golden vignettes
def test_v10_every_path_has_golden_cases(bundle):
    for path in bundle.paths.values():
        assert len(path.golden_cases) >= 3, f"{path.id} needs >=3 golden cases"


def test_v10_catches_wrong_expectation(mutable_bundle):
    path = mutable_bundle.paths["shoulder_chronic_clicking_v1"]
    path.golden_cases[0].expect = "skin_changing_mole_v1"
    assert validator.RULES["V10"](mutable_bundle)
