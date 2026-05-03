"""Tests for scripts/generate_frontend_registry.py output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GEN_DIR = _REPO_ROOT / "frontend" / "src" / "generated"
_BUNDLES_JSON = _GEN_DIR / "bundles.json"
_PAYERS_JSON = _GEN_DIR / "payers.json"
_PLAN_CONFIGS_JSON = _GEN_DIR / "plan_configs.json"


@pytest.fixture(scope="module")
def registry() -> dict:
    assert _BUNDLES_JSON.exists(), "Run generate_frontend_registry.py first"
    return json.loads(_BUNDLES_JSON.read_text())


@pytest.fixture(scope="module")
def payers() -> list[dict]:
    assert _PAYERS_JSON.exists(), "Run generate_frontend_registry.py first"
    return json.loads(_PAYERS_JSON.read_text())


@pytest.fixture(scope="module")
def plan_configs() -> list[dict]:
    assert _PLAN_CONFIGS_JSON.exists(), "Run generate_frontend_registry.py first"
    return json.loads(_PLAN_CONFIGS_JSON.read_text())


def test_has_all_bundles(registry: dict) -> None:
    assert len(registry["bundles"]) >= 29


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
        assert bundle["specialty"] in valid_specialties, (
            f"Bundle {bid} has unknown specialty: {bundle['specialty']}"
        )


def test_payers_has_entries(payers: list[dict]) -> None:
    assert len(payers) >= 1


def test_payers_shape(payers: list[dict]) -> None:
    required = {"key", "label", "payer_id"}
    for p in payers:
        missing = required - set(p.keys())
        assert not missing, f"Payer {p.get('key', '?')} missing fields: {missing}"


def test_payer_keys_match_yaml() -> None:
    import yaml

    raw = yaml.safe_load((_REPO_ROOT / "data" / "registries" / "payers.yaml").read_text())
    yaml_slugs = {p["slug"] for p in raw["payers"].values()}
    gen_keys = {p["key"] for p in json.loads(_PAYERS_JSON.read_text())}
    assert gen_keys == yaml_slugs, f"Mismatch: YAML={yaml_slugs}, generated={gen_keys}"


def test_plan_configs_has_entries(plan_configs: list[dict]) -> None:
    assert len(plan_configs) >= 1


def test_plan_configs_shape(plan_configs: list[dict]) -> None:
    required = {
        "id",
        "payer",
        "carrierKey",
        "planName",
        "planType",
        "deductible",
        "oopMax",
        "coinsurancePct",
        "copaySpecialist",
    }
    for pc in plan_configs:
        missing = required - set(pc.keys())
        assert not missing, f"Plan config {pc.get('id', '?')} missing fields: {missing}"


def test_plan_configs_types(plan_configs: list[dict]) -> None:
    for pc in plan_configs:
        assert pc["planType"] in ("PPO", "HMO"), (
            f"{pc['id']} has invalid planType: {pc['planType']}"
        )
        assert isinstance(pc["deductible"], (int, float)), f"{pc['id']} deductible not numeric"
        assert isinstance(pc["oopMax"], (int, float)), f"{pc['id']} oopMax not numeric"


def test_check_flag_passes() -> None:
    result = subprocess.run(
        ["python", str(_REPO_ROOT / "scripts" / "generate_frontend_registry.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"--check failed: {result.stdout}{result.stderr}"
