"""Tests for scripts/generate_frontend_registry.py output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLES_JSON = _REPO_ROOT / "frontend" / "src" / "generated" / "bundles.json"


@pytest.fixture(scope="module")
def registry() -> dict:
    assert _BUNDLES_JSON.exists(), "Run generate_frontend_registry.py first"
    return json.loads(_BUNDLES_JSON.read_text())


def test_has_all_29_bundles(registry: dict) -> None:
    assert len(registry["bundles"]) == 29


def test_has_2_specialties(registry: dict) -> None:
    assert set(registry["specialties"].keys()) == {"Gastroenterology", "Dermatology"}


def test_every_bundle_has_required_fields(registry: dict) -> None:
    required = {"cpt", "label", "specialty", "description", "tags"}
    for bid, bundle in registry["bundles"].items():
        missing = required - set(bundle.keys())
        assert not missing, f"Bundle {bid} missing fields: {missing}"


def test_bundles_reference_valid_specialties(registry: dict) -> None:
    valid_specialties = set(registry["specialties"].keys())
    for bid, bundle in registry["bundles"].items():
        assert bundle["specialty"] in valid_specialties, f"Bundle {bid} has unknown specialty: {bundle['specialty']}"


def test_check_flag_passes() -> None:
    result = subprocess.run(
        ["python", str(_REPO_ROOT / "scripts" / "generate_frontend_registry.py"), "--check"],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"--check failed: {result.stdout}{result.stderr}"
