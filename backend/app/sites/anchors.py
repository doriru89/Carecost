"""Monthly anchor checks for the site registry (census §8 step 7). Loud: exit 1 on any miss.

    python -m app.sites.anchors

* NPPES (CMS NPI Registry API v2.1): AFC Urgent Care Watertown's org NPI 1164772299 must still
  exist, be active, and practice in Watertown.
* sites.yaml: AFC Watertown still carries TIN 460903626 (the BCBS TiC match, P1 problem 4).
* DPH: BIDMC Chelsea (2ED8) is checked by ``python -m app.sites.dph check``.
"""

from __future__ import annotations

import json
import sys

import yaml

from app.etl.fetch import FetchError, http_get_bytes
from app.sites.build import SITES_DIR

NPPES = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}"
ALLOWED = ["npiregistry.cms.hhs.gov"]
ANCHORS = [
    {"site_id": "afc_watertown", "npi": "1164772299", "city": "WATERTOWN", "tin": "460903626"}
]


def check_nppes(npi: str, city: str) -> list[str]:
    try:
        body, _final, _h = http_get_bytes(NPPES.format(npi=npi), ALLOWED, 2_000_000)
    except FetchError as e:
        return [f"NPPES {npi}: {e}"]
    d = json.loads(body)
    res = d.get("results") or []
    if not res:
        return [f"NPPES {npi}: not found"]
    r = res[0]
    probs = []
    if (r.get("basic") or {}).get("status", "A") != "A":
        probs.append(f"NPPES {npi}: status {(r.get('basic') or {}).get('status')}")
    cities = {
        (a.get("city") or "").upper()
        for a in r.get("addresses", []) + r.get("practiceLocations", [])
    }
    if city not in cities:
        probs.append(f"NPPES {npi}: no address in {city} ({sorted(cities)})")
    return probs


def main() -> int:
    sites = {s["id"]: s for s in yaml.safe_load((SITES_DIR / "sites.yaml").read_text())["sites"]}
    problems = []
    for a in ANCHORS:
        s = sites.get(a["site_id"])
        if not s:
            problems.append(f"{a['site_id']} missing from sites.yaml")
        elif a["tin"] not in s.get("tins", []):
            problems.append(f"{a['site_id']}: TIN {a['tin']} gone")
        problems += check_nppes(a["npi"], a["city"])
    for p in problems:
        print(f"FAIL   {p}")
    print(f"ANCHOR {len(ANCHORS)} checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
