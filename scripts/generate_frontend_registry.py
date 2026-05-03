#!/usr/bin/env python3
"""Generate frontend/src/generated/*.json from YAML registries.

Outputs:
    bundles.json      — CPT bundles + specialties (from cpt_bundles.yaml + specialties.yaml)
    payers.json       — payer list for fallback (from payers.yaml)
    plan_configs.json — plan financial defaults (from plan_defaults.yaml)
    plan_rules.json   — OOP rule classifications (from plan_rules.yaml)

Usage:
    python scripts/generate_frontend_registry.py          # generate all
    python scripts/generate_frontend_registry.py --check  # verify freshness (CI gate)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data" / "registries"
_GEN_DIR = _REPO_ROOT / "frontend" / "src" / "generated"


def _build_bundles() -> dict:
    bundles_raw = yaml.safe_load((_DATA_DIR / "cpt_bundles.yaml").read_text())["bundles"]
    specialties_raw = yaml.safe_load((_DATA_DIR / "specialties.yaml").read_text())["specialties"]

    specialties = {}
    for name, spec in specialties_raw.items():
        specialties[name] = {
            "id": name.lower().replace(" ", "_"),
            "taxonomy": spec["taxonomy"],
            "default_scenario": spec["default_scenario"],
        }

    bundles = {}
    for bid, b in bundles_raw.items():
        entry = {
            "cpt": b["cpt"],
            "label": b["label"],
            "specialty": b["specialty"],
            "description": b["description"],
            "tags": b.get("tags", []),
        }
        if b.get("aliases_to"):
            entry["aliases_to"] = b["aliases_to"]
        bundles[bid] = entry

    return {"specialties": specialties, "bundles": bundles}


def _build_payers() -> list[dict]:
    payers_raw = yaml.safe_load((_DATA_DIR / "payers.yaml").read_text())["payers"]
    return [
        {"key": p["slug"], "label": p["label"], "payer_id": p["slug"]}
        for p in payers_raw.values()
    ]


def _build_plan_configs() -> list[dict]:
    plans_raw = yaml.safe_load((_DATA_DIR / "plan_defaults.yaml").read_text())["plan_defaults"]
    return [
        {
            "id": pid,
            "payer": p["payer"],
            "carrierKey": p["carrier"],
            "planName": p["plan_name"],
            "planType": p["plan_type"],
            "deductible": p["deductible"],
            "oopMax": p["oop_max"],
            "coinsurancePct": p["coinsurance_pct"],
            "copaySpecialist": p["copay_specialist"],
            "deductibleAppliesToSpecialist": p.get("deductible_applies_to_specialist", False),
        }
        for pid, p in plans_raw.items()
    ]


def _build_plan_rules() -> dict:
    rules_raw = yaml.safe_load((_DATA_DIR / "plan_rules.yaml").read_text())
    return {
        "scenario_rules": rules_raw.get("scenario_rules", {}),
        "cpt_rules": rules_raw.get("cpt_rules", {}),
        "default_rule": rules_raw.get("default_rule", {"rule_type": "ded_coinsurance", "summary": "Deductible then coinsurance"}),
    }


_OUTPUTS: list[tuple[str, callable]] = [
    ("bundles.json", _build_bundles),
    ("payers.json", _build_payers),
    ("plan_configs.json", _build_plan_configs),
    ("plan_rules.json", _build_plan_rules),
]


def main() -> int:
    check_mode = "--check" in sys.argv
    _GEN_DIR.mkdir(parents=True, exist_ok=True)
    failures = []

    for filename, builder in _OUTPUTS:
        path = _GEN_DIR / filename
        data = builder()
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        if check_mode:
            if not path.exists():
                failures.append(f"{filename} does not exist")
            elif path.read_text() != content:
                failures.append(f"{filename} is stale")
            else:
                count = len(data) if isinstance(data, list) else sum(len(v) for v in data.values())
                print(f"OK: {filename} ({count} entries)")
        else:
            path.write_text(content)
            count = len(data) if isinstance(data, list) else sum(len(v) for v in data.values())
            print(f"Generated {filename}: {count} entries")

    if check_mode and failures:
        for f in failures:
            print(f"FAIL: {f}")
        print("Regenerate with: python scripts/generate_frontend_registry.py")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
