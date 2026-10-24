"""Red flags: 4 dispositions, table-driven English + Chinese cases, checklist size, path coverage."""

from __future__ import annotations

import json

import pytest

from app.care_paths import redflags
from app.care_paths.loader import DATA_ROOT

CASES = json.loads((DATA_ROOT / "redflags" / "cases.json").read_text())["cases"]


def test_exactly_four_dispositions(bundle):
    assert [d.id for d in bundle.redflags.dispositions] == [
        "call_911",
        "er_today",
        "seen_today",
        "routine",
    ]


def test_cases_cover_both_languages_and_all_dispositions():
    langs = {c["lang"] for c in CASES}
    assert {"en", "zh"} <= langs
    expected = {c["expect"] for c in CASES}
    assert {"call_911", "er_today", "seen_today", "routine", None} <= expected


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:40] for c in CASES])
def test_free_text_screen(bundle, case):
    result = redflags.screen_text(case["text"], bundle.redflags, areas=case.get("areas"))
    assert result.disposition == case["expect"], (
        f"{case['text']!r}: got {result.disposition} via {result.flag_ids}"
    )


def test_highest_disposition_wins(bundle):
    r = redflags.screen_text(
        "my back hurts, I have a fever and now numbness in both legs", bundle.redflags
    )
    assert r.disposition == "er_today"
    assert len(r.flag_ids) >= 2


def test_checklist_screen(bundle):
    assert redflags.screen_checklist(["rf_cardiac"], bundle.redflags).disposition == "call_911"
    assert redflags.screen_checklist([], bundle.redflags).disposition is None


def test_every_flag_has_bilingual_copy_and_a_source(bundle):
    src_ids = set(bundle.sources)
    for f in bundle.redflags.flags:
        assert f.checklist.en and f.checklist.zh, f.id
        assert f.sources and set(f.sources) <= src_ids, f.id
        assert f.patterns, f"{f.id} has no free-text patterns"


def test_q0_checklist_is_short_per_area(bundle):
    """Long red-flag screens train users to click 'no' on everything (UCHealth 84->39 lesson)."""
    for area in bundle.redflags.path_areas:
        items = redflags.checklist_for_area(area, bundle.redflags)
        assert len(items) <= 7, f"{area}: {len(items)} checklist items"
