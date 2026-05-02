"""Tests for Phase 20 Step 3 — list_specialties from registry."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_list_specialties_returns_gi_and_derm() -> None:
    from app.modules.hospitals.application.use_cases import list_specialties

    db = MagicMock()
    result = list_specialties(db)

    assert len(result) == 2
    labels = {s["label"] for s in result}
    assert labels == {"Gastroenterology", "Dermatology"}


def test_list_specialties_gi_has_10_bundles() -> None:
    from app.modules.hospitals.application.use_cases import list_specialties

    db = MagicMock()
    result = list_specialties(db)
    gi = next(s for s in result if s["label"] == "Gastroenterology")
    assert len(gi["procedures"]) == 10


def test_list_specialties_derm_has_19_bundles() -> None:
    from app.modules.hospitals.application.use_cases import list_specialties

    db = MagicMock()
    result = list_specialties(db)
    derm = next(s for s in result if s["label"] == "Dermatology")
    assert len(derm["procedures"]) == 19


def test_list_specialties_procedures_have_required_fields() -> None:
    from app.modules.hospitals.application.use_cases import list_specialties

    db = MagicMock()
    result = list_specialties(db)
    for specialty in result:
        for proc in specialty["procedures"]:
            assert "cpt" in proc, f"Missing cpt in {proc}"
            assert "desc" in proc, f"Missing desc in {proc}"
            assert "bundle_id" in proc, f"Missing bundle_id in {proc}"
