"""Publishability: AI-drafted content stays pending until two non-AI humans sign off.

These tests must never be satisfied by editing data to look approved. Approval is recorded by
Austin (and a clinician) adding themselves under review.reviewers; an AI agent must not do that.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.care_paths import validator
from app.care_paths.models import Review, Reviewer


def test_all_ai_drafted_paths_are_pending_and_unpublishable(bundle):
    for path in bundle.paths.values():
        if path.review.drafted_by.startswith("ai:"):
            assert path.review.status == "pending_austin", path.id
            reasons = validator.publishable(path, bundle)
            assert reasons, f"{path.id} must not be publishable yet"


def test_no_recorded_approvals_from_ai_or_drafter(bundle):
    for path in bundle.paths.values():
        for r in path.review.reviewers:
            assert not r.id.startswith("ai:"), path.id
            assert r.kind != "ai", path.id
            assert r.id != path.review.drafted_by, path.id


def test_glossary_and_redflags_are_pending(bundle):
    assert bundle.glossary.review.status == "pending_austin"
    assert bundle.redflags.review.status == "pending_austin"
    assert bundle.questions.review.status == "pending_austin"


def _human(i: str, kind: str = "human_nonclinician") -> Reviewer:
    return Reviewer(id=i, kind=kind, at=dt.date(2026, 11, 1), verdict="ok")


def test_approved_requires_two_distinct_humans():
    with pytest.raises(ValidationError):
        Review(status="approved", drafted_by="ai:claude-opus", reviewers=[_human("austin")])
    with pytest.raises(ValidationError):
        Review(
            status="approved",
            drafted_by="ai:claude-opus",
            reviewers=[_human("austin"), _human("austin")],
        )
    with pytest.raises(ValidationError):
        Review(
            status="approved",
            drafted_by="ai:claude-opus",
            reviewers=[_human("austin"), Reviewer(id="ai:gpt", kind="ai", at=None, verdict="ok")],
        )
    ok = Review(
        status="approved",
        drafted_by="ai:claude-opus",
        reviewers=[_human("austin"), _human("dr_x", "human_clinician")],
    )
    assert ok.status == "approved"


def test_public_launch_needs_a_clinician(mutable_bundle):
    path = mutable_bundle.paths["skin_changing_mole_v1"]
    path.review = Review(
        status="approved",
        drafted_by="ai:claude-opus",
        reviewers=[_human("austin"), _human("friend")],
    )
    reasons = validator.publishable(path, mutable_bundle, audience="public")
    assert any("clinician" in r for r in reasons)


def test_asserted_code_mappings_block_publishing(bundle):
    path = bundle.paths["shoulder_chronic_clicking_v1"]
    reasons = validator.publishable(path, bundle)
    assert any("asserted" in r for r in reasons)
