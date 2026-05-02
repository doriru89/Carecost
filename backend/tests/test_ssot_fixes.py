"""Tests for Phase 20 Step 7 — SSOT bug fixes."""

from __future__ import annotations


def test_default_payer_id_from_registry() -> None:
    from app.registries import default_payer_id

    assert default_payer_id() == "BCBS_MA"


def test_gi_leaf_ids_match_registry() -> None:
    from app.registries import bundles_for_specialty
    from app.services.gi_symptom_refinement import _GI_LEAF_IDS

    registry_ids = list(bundles_for_specialty("Gastroenterology").keys())
    assert set(_GI_LEAF_IDS) == set(registry_ids)
    assert len(_GI_LEAF_IDS) == 10


def test_default_specialty_from_registry() -> None:
    from app.registries import default_specialty

    assert default_specialty() == "Gastroenterology"
