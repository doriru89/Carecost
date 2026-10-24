"""Schema: pydantic models parse every data file; the exported JSON Schema contract is current."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.care_paths import schema_export
from app.care_paths.loader import REPO_ROOT
from app.care_paths.models import Citation, Plain, Step


def test_bundle_loads_and_has_core_paths(bundle):
    for path_id in (
        "shoulder_chronic_clicking_v1",
        "shoulder_acute_injury_v1",
        "skin_changing_mole_v1",
        "colon_screening_v1",
        "colon_diagnostic_v1",
    ):
        assert path_id in bundle.paths, f"missing core path {path_id}"


def test_contract_file_matches_models():
    committed = json.loads((REPO_ROOT / "contracts" / "care_path.schema.json").read_text())
    assert committed == schema_export.build_schema(), (
        "contracts/care_path.schema.json is stale. Run: "
        "python -m app.care_paths.schema_export (from backend/)"
    )


def test_quote_over_15_words_is_rejected():
    with pytest.raises(ValidationError):
        Citation(
            doc="x",
            year=2024,
            section="Variant 1",
            url="https://example.org",
            quote="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen",
            claim_field="why",
        )


def test_plain_requires_all_fields():
    with pytest.raises(ValidationError):
        Plain(name="Quick bone picture", technical_name="X-ray", what="a", why="b")  # type: ignore[call-arg]


def test_ai_potential_must_be_labelled(bundle):
    step = next(iter(bundle.paths.values())).steps[0]
    data = step.model_dump()
    data["ai_potential"] = [
        {"text": "Something", "label": "Likely extra cost", "ai_generated": True}
    ]
    with pytest.raises(ValidationError):
        Step.model_validate(data)


def test_every_ai_potential_item_is_labelled(bundle):
    for path in bundle.paths.values():
        for step in path.steps:
            for item in step.ai_potential:
                assert item.label == "AI-suggested"
                assert item.ai_generated is True
