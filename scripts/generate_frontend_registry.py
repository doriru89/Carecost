#!/usr/bin/env python3
"""Generate frontend/src/generated/bundles.json from YAML registries.

Usage:
    python scripts/generate_frontend_registry.py          # generate
    python scripts/generate_frontend_registry.py --check  # verify freshness (CI gate)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data" / "registries"
_OUTPUT = _REPO_ROOT / "frontend" / "src" / "generated" / "bundles.json"


def build_registry() -> dict:
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


def main() -> int:
    registry = build_registry()
    content = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"

    if "--check" in sys.argv:
        if not _OUTPUT.exists():
            print(f"FAIL: {_OUTPUT} does not exist. Run without --check to generate.")
            return 1
        existing = _OUTPUT.read_text()
        if existing == content:
            print(f"OK: {_OUTPUT.name} is up-to-date ({len(registry['bundles'])} bundles)")
            return 0
        else:
            print(f"FAIL: {_OUTPUT.name} is stale. Regenerate with: python scripts/generate_frontend_registry.py")
            return 1

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(content)
    print(f"Generated {_OUTPUT.name}: {len(registry['specialties'])} specialties, {len(registry['bundles'])} bundles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
