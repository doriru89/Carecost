"""Tests for Phase 20 Step 7 — SSOT bug fixes."""

from __future__ import annotations


def test_default_payer_id_from_registry() -> None:
    from app.registries import all_payers, default_payer_id

    payer_id = default_payer_id()
    assert payer_id in all_payers()


def test_gi_leaf_ids_match_registry() -> None:
    from app.registries import bundles_for_specialty, default_specialty
    from app.services.gi_symptom_refinement import _GI_LEAF_IDS

    gi_specialty = default_specialty()
    registry_ids = list(bundles_for_specialty(gi_specialty).keys())
    assert set(_GI_LEAF_IDS) == set(registry_ids)
    assert len(_GI_LEAF_IDS) == len(registry_ids)


def test_default_specialty_from_registry() -> None:
    from app.registries import all_specialty_names, default_specialty

    specialty = default_specialty()
    assert specialty in all_specialty_names()
