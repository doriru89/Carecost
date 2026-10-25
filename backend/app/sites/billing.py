"""Resolve ``billing_type: unknown`` through the health system's public structure (R7, P9).

    python -m app.sites.billing [--as-of D] [--no-nppes]   -> data/sites/billing_structure.yaml

A site the census could not classify is usually a hospital-system practice. Whether a visit
there adds a hospital facility fee is a licensing fact, not a guess from the name: a clinic that
is part of a hospital's license (on its campus or a DPH "Hospital Satellite") is a hospital
outpatient department and the hospital bills a facility line; a practice outside the license
bills one professional claim. Rules, in order; each records its source:

1. ``dph_hospital_campus``: the DPH facility list (Sept 2026 file, ``raw/dph``) has an Acute
   Hospital licence of the site's own system at the site's address key: an on-campus
   outpatient department -> ``hospital_outpatient``.
   ``dph_hospital_satellite``: a Hospital Satellite (or satellite emergency) licence of the
   site's system at the address, and the site is named as that hospital's own department
   (brand overlap; a physicians' organisation or private group in the building is not)
   -> ``hospital_outpatient``.
2. ``hpc_rpo``: the HPC Registration of Provider Organizations (2024, as quoted in the census
   row) gives provider-based status for this site's own location (same system, the site named
   as the hospital's department): YES -> ``hospital_outpatient``, NO -> ``office_visit``.
3. ``nppes_hospital_npi``: one of the site's own type-2 NPIs is a hospital (NPPES taxonomy
   282N*) of the site's system -> ``hospital_outpatient``.

Evidence about another organisation at the same address is recorded but never decides. When
rules disagree, or none applies, the site stays ``unknown`` and is listed for a person to check
(``billing_to_verify`` in ``data/sites/to_verify.yaml``); the quote engine prices it as a
hospital outpatient site with a "may add a hospital facility fee" line (P9). ``python -m
app.sites.build`` reads only this committed file, so the build stays reproducible from git.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.etl.config import Paths
from app.sites.address import akey

REPO = Path(__file__).resolve().parents[3]
SITES_DIR = REPO / "data" / "sites"
OUT = SITES_DIR / "billing_structure.yaml"
NPPES = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}"
NPPES_ALLOWED = ["npiregistry.cms.hhs.gov"]

HOSPITAL_LICENSES = {
    "Acute Hospital", "Hospital Satellite", "Satellite Emergency Facility",
    "Mob/Port Hospital Satellite", "Satellite Inpatient Unit",
}  # fmt: skip
CLINIC_LICENSES = {"Clinic", "Clinic Satellite"}

# system_id -> how its hospitals are named in the DPH list, the HPC RPO and NPPES (upper case)
SYSTEM_NAMES: dict[str, str] = {
    "mgb": r"MASS(ACHUSETTS)? GENERAL|\bMGH\b|BRIGHAM|\bBWH\b|NEWTON[- ]WELLESLEY|FAULKNER|"
    r"SALEM HOSP|MASS(ACHUSETTS)? EYE|SPAULDING|MCLEAN|\bMGB\b|NORTH SHORE MEDICAL|"
    r"GENERAL HOSPITAL CORP",
    "bilh": r"BETH ISRAEL|\bBIDMC\b|\bBID\b|MOUNT AUBURN|MT AUBURN|NEW ENGLAND BAPTIST|\bNEBH\b|"
    r"\bNEBOCC\b|LAHEY|WINCHESTER HOSP|ANNA JAQUES|\bBILH\b",
    "bmc": r"BOSTON MEDICAL|\bBMC\b|ST\.? ELIZABETH|GOOD SAMARITAN",
    "tufts_medicine": r"TUFTS|MELROSE|LOWELL GENERAL|HALLMARK",
    "cha": r"CAMBRIDGE HEALTH ALLIANCE|\bCHA\b|CAMBRIDGE PUBLIC HEALTH|CAMBRIDGE HOSP|"
    r"SOMERVILLE HOSP|WHIDDEN",
    "south_shore_health": r"SOUTH SHORE (HOSP|HEALTH)",
    "boston_childrens": r"CHILDREN'?S HOSP|BOSTON CHILDREN",
    "dana_farber": r"DANA[- ]FARBER",
}
# Hospital brands, so "is this clinic that licensed location?" is asked of the names, not just
# the system: a clinic named as the hospital's own department at an address where that hospital
# holds a satellite licence is that department; a private group in the same building is not.
BRANDS: list[tuple[str, str]] = [
    (r"MASS(ACHUSETTS)? GENERAL(?! BRIGHAM)|\bMGH\b|GENERAL HOSPITAL CORP", "mgh"),
    (r"BRIGHAM (AND|&) WOMEN|\bBWH\b", "bwh"),
    (r"NEWTON[- ]WELLESLEY", "nwh"),
    (r"NEW ENGLAND BAPTIST|\bNEBOCC\b|\bNEBH\b", "nebh"),
    (r"CAMBRIDGE HEALTH ALLIANCE|\bCHA\b|CAMBRIDGE PUBLIC HEALTH", "cha"),
    (r"MOUNT AUBURN|MT\.? AUBURN", "mtauburn"),
    (r"BETH ISRAEL|\bBIDMC\b|\bBID\b", "bid"),
    (r"BOSTON MEDICAL CENTER|\bBMC\b", "bmc"),
    (r"DANA[- ]FARBER", "dfci"),
    (r"SPAULDING", "spaulding"),
    (r"SALEM HOSP", "salem"),
    (r"MASS(ACHUSETTS)? EYE (AND|&) EAR", "meei"),
    (r"MELROSE", "melrose"),
    (r"CHILDREN'?S HOSP|BOSTON CHILDREN", "childrens"),
    (r"SOUTH SHORE (HOSP|HEALTH)", "south_shore"),
]
# a physicians' organisation / private group is not the hospital department, whatever its brand
GROUP_NAME = re.compile(
    r"PHYSICIANS|ASSOCIATES|\bGROUP\b|FOUNDATION|\bP\.?C\.?$|\bLLC\b|PLLC|PROFESSIONAL SERVICES",
    re.I,
)


def brands(name: str) -> set[str]:
    u = name.upper()
    return {tok for rx, tok in BRANDS if re.search(rx, u)}


def is_department_of(site_name: str, licence_name: str) -> bool:
    """The site is named as the licensed hospital's own department (brand overlap, no group)."""
    if GROUP_NAME.search(site_name):
        return False
    return bool(brands(site_name) & brands(licence_name))


RPO = re.compile(
    r"HPC RPO (\d{4}): provider-based status (YES|NO) \(([^()]*(?:\([^()]*\)[^()]*)*)\)", re.I
)


def same_system(system_id: str | None, name: str) -> bool:
    rx = SYSTEM_NAMES.get(system_id or "")
    return bool(rx and re.search(rx, name.upper()))


def load_dph(paths: Paths) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    from app.sites.dph import current, parse_facilities

    got = current(paths, "facilities")
    if got is None:
        raise SystemExit("DPH facility list not on disk: run `python -m app.sites.dph fetch`")
    path, rec = got
    rows, as_of = parse_facilities(path)
    by: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        k = akey(r["street"], r["zip"])
        if k:
            by.setdefault(k, []).append(r)
    meta = {
        "file": rec.get("filename"),
        "sha256": rec.get("sha256"),
        "file_date": as_of.isoformat() if as_of else None,
        "fetched_at": rec.get("fetched_at"),
        "url": rec.get("final_url") or rec.get("link_url"),
    }
    return by, meta


def nppes_lookup(npis: list[str], cache: dict[str, Any]) -> dict[str, Any]:
    from app.etl.fetch import FetchError, http_get_bytes

    for n in npis:
        if n in cache:
            continue
        try:
            body, _f, _h = http_get_bytes(NPPES.format(npi=n), NPPES_ALLOWED, 2_000_000)
            res = json.loads(body).get("results") or []
            cache[n] = _nppes_brief(res[0]) if res else None
        except FetchError as e:
            cache[n] = {"error": str(e)}
        time.sleep(0.2)
    return cache


def _nppes_brief(r: dict[str, Any]) -> dict[str, Any]:
    b = r.get("basic") or {}
    loc = next((a for a in r.get("addresses") or [] if a.get("address_purpose") == "LOCATION"), {})
    tax = (
        next((t for t in r.get("taxonomies") or [] if t.get("primary")), None)
        or ((r.get("taxonomies") or [{}])[0])
    )
    return {
        "name": b.get("organization_name") or "",
        "taxonomy": tax.get("code") or "",
        "taxonomy_desc": tax.get("desc") or "",
        "street": loc.get("address_1") or "",
        "zip": (loc.get("postal_code") or "")[:5],
    }


def decide(
    site: dict[str, Any],
    dph: dict[str, list[dict[str, str]]],
    dph_meta: dict[str, Any],
    nppes: dict[str, Any],
) -> dict[str, Any]:
    """One unknown site -> {billing_type, confidence, rule, source} or {reason, evidence}."""
    sysid = site.get("system_id")
    a = site["address"]
    k = akey(a["street"], a["zip"])
    votes: list[tuple[str, str, str]] = []  # (billing_type, rule, source)
    seen: list[str] = []
    for r in dph.get(k or "", []):
        lic = f"DPH {r['type']} licence {r['id']} ({r['name']}) at {r['street']}, {r['zip']}"
        tag = f"{lic} (list dated {dph_meta['file_date']}, sha {str(dph_meta['sha256'])[:12]})"
        if r["type"] in HOSPITAL_LICENSES:
            if not same_system(sysid, r["name"]):
                seen.append(f"{tag}: another organisation's licence, not used")
            elif r["type"] == "Acute Hospital":
                # on the hospital's licensed main campus: an on-campus outpatient department
                votes.append(("hospital_outpatient", "dph_hospital_campus", tag))
            elif is_department_of(site["name"], r["name"]):
                votes.append(("hospital_outpatient", "dph_hospital_satellite", tag))
            else:
                seen.append(
                    f"{tag}: same system, but the site is not named as this licensed location"
                )
        elif r["type"] in CLINIC_LICENSES:
            seen.append(f"{tag}: clinic licence (not decisive)")
    for m in RPO.finditer(site.get("billing_type_source") or ""):
        year, yes, what = m.group(1), m.group(2).upper() == "YES", m.group(3)
        tag = f"HPC RPO {year} (via clinic-census row): provider-based {m.group(2)} for '{what}'"
        if same_system(sysid, what) and is_department_of(site["name"], what):
            votes.append(("hospital_outpatient" if yes else "office_visit", "hpc_rpo", tag))
        else:
            seen.append(f"{tag}: not this site's own location record, not used")
    for n in site.get("type_2_npis") or []:
        e = nppes.get(n) or {}
        if not e or "error" in e:
            seen.append(f"NPPES {n}: {e.get('error', 'not found') if e else 'not looked up'}")
            continue
        tag = (
            f"NPPES {n} {e['name']} taxonomy {e['taxonomy']} ({e['taxonomy_desc']}) "
            f"at {e['street']} {e['zip']}"
        )
        if e["taxonomy"].startswith("282N") and same_system(sysid, e["name"]):
            votes.append(("hospital_outpatient", "nppes_hospital_npi", tag))
        else:
            seen.append(f"{tag}: not a hospital NPI")
    kinds = {v[0] for v in votes}
    if len(kinds) == 1:
        bt = kinds.pop()
        return {
            "billing_type": bt,
            "confidence": "likely",
            "rules": sorted({v[1] for v in votes}),
            "source": " ; ".join(v[2] for v in votes),
            "also_seen": seen,
        }
    reason = (
        "rules disagree: " + " | ".join(f"{v[0]} by {v[1]}" for v in votes)
        if votes
        else "no licence, provider-based record or hospital NPI of the site's own system at "
        "this address"
    )
    return {
        "billing_type": "unknown",
        "reason": reason,
        "evidence_seen": seen + [v[2] for v in votes],
    }


def resolve(
    sites: list[dict[str, Any]], paths: Paths, as_of: date, use_nppes: bool = True
) -> dict[str, Any]:
    dph, meta = load_dph(paths)
    unknown = [s for s in sites if s.get("billing_type") == "unknown" and s.get("census_id")]
    cache: dict[str, Any] = {}
    if use_nppes:
        nppes_lookup(sorted({n for s in unknown for n in s.get("type_2_npis") or []}), cache)
    resolved, todo = {}, {}
    for s in sorted(unknown, key=lambda x: x["census_id"]):
        d = decide(s, dph, meta, cache)
        entry = {"site_id": s["id"], "name": s["name"], "system_id": s.get("system_id")}
        if d["billing_type"] == "unknown":
            todo[s["census_id"]] = {
                **entry,
                "reason": d["reason"],
                "evidence_seen": d["evidence_seen"],
            }
        else:
            resolved[s["census_id"]] = {**entry, **d}
    return {
        "version": 1,
        "as_of": as_of.isoformat(),
        "method": "python -m app.sites.billing (rules in its docstring)",
        "sources": {
            "dph_facilities": meta,
            "hpc_rpo": "HPC Registration of Provider Organizations 2024, as quoted in "
            "data/sites/census/clinic-census-2026-10-24.csv billing_evidence",
            "nppes": f"NPI Registry API v2.1 ({NPPES.split('?')[0]}), looked up {as_of.isoformat()}"
            if use_nppes
            else "not used (--no-nppes)",
        },
        "counts": {"unknown_in": len(unknown), "resolved": len(resolved), "to_verify": len(todo)},
        "resolved": resolved,
        "to_verify": todo,
    }


def load(path: Path = OUT) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    from app.sites.build import DEFAULT_CENSUS, build

    p = argparse.ArgumentParser(prog="python -m app.sites.billing")
    p.add_argument("--as-of", default=date.today().isoformat())
    p.add_argument("--data-dir", default=None)
    p.add_argument("--no-nppes", action="store_true")
    a = p.parse_args(argv)
    paths = Paths.resolve(a.data_dir)
    as_of = date.fromisoformat(a.as_of)
    sites, _todo, _rep = build(DEFAULT_CENSUS, as_of, use_billing=False)
    raw = [json.loads(s.model_dump_json()) for s in sites.sites]
    doc = resolve(raw, paths, as_of, use_nppes=not a.no_nppes)
    head = "# GENERATED by `python -m app.sites.billing` (R7, P9). Rules: backend/app/sites/billing.py.\n"
    OUT.write_text(head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110))
    c = doc["counts"]
    print(
        f"BILLING {c['unknown_in']} unknown: {c['resolved']} resolved, {c['to_verify']} to verify -> {OUT}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
