"""Build ``data/sites/sites.yaml`` + ``data/sites/to_verify.yaml`` (D14, D27, P12).

    python -m app.sites.build [--census CSV] [--as-of YYYY-MM-DD] [--check]

Inputs (all committed):

* ``data/sites/census/clinic-census-<date>.csv``: the registry-first census (398 rows; research-v3).
* ``data/registries/hospitals.yaml`` + ``data/etl/sources.yaml``: one hospital-outpatient site per
  hospital with a price file (address from the file's own ``hospital_address``, which the build
  reads from the staged meta when present, else ``data/sites/hospital_addresses.yaml``).
* ``data/sites/curated.yaml``: hand-checked entries (hours, booking, posted cash prices), keyed by
  ``census_id`` or ``hospital_entity_id``; a non-empty curated field wins over a derived one.
* ``data/sites/dph_services.yaml`` (optional, from ``python -m app.sites.dph``): licensed-clinic
  service flags joined by address, used for ``offered`` (P1 problem 14).

Rules (census §6, D27):

* a census row is *active* when its ``flags`` carry none of ``closed``, ``likely_closed``,
  ``registry_only``, ``terminated``, ``remove`` (the census's own rule, ``final.py``);
* restricted sites (student / employee health, restricted programs) are left out;
* pediatric rows are kept with ``children_only: true`` (a name that says ADULT is not);
* active rows with two or more registries or a web check go to ``sites.yaml``; single-registry
  rows, registry-only rows and rows without coordinates go to ``to_verify.yaml`` (never quoted);
* TINs: org-level ``tins`` plus clinician billing TINs carried by >=25% of the site's clinicians
  (the census already applied the share); 10-digit TiC "TINs" are NPIs -> ``tin_npis``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.sites import billing as billing_mod
from app.sites.contracts import (
    BillingToVerify,
    Site,
    SitesFile,
    ToVerifyFile,
    check_npi,
    normalize_tin,
)

REPO = Path(__file__).resolve().parents[3]
SITES_DIR = REPO / "data" / "sites"
DEFAULT_CENSUS = SITES_DIR / "census" / "clinic-census-2026-10-24.csv"
INACTIVE = ("closed", "likely_closed", "registry_only", "terminated", "remove")
RESTRICTED = ("restricted_",)
SRC_COLS = ("src_web", "src_nppes", "src_cms_dac", "src_cms_pos", "src_dph_facility",
            "src_dph_uc2024", "src_hpc_rpo", "src_fhir_humana")  # fmt: skip
CATEGORY_AREAS = {"urgent_care": ["urgent_care"], "ortho": ["ortho"], "derm": ["skin"],
                  "gi": ["gi"], "asc_endo": ["gi"]}  # fmt: skip
SPEC_AREAS = {"ortho": "ortho", "derm": "skin", "gi": "gi", "sports": "ortho", "hand": "ortho",
              "colorectal": "gi"}  # fmt: skip
SYSTEMS = [
    (r"\bMGB\b|Mass General|BWH|MGH|Newton-Wellesley|Faulkner|Mass Eye", "mgb"),
    (r"BILH|BIDMC|Lahey|Beth Israel|Mount Auburn|Winchester|NEBH", "bilh"),
    (r"\bBMC\b|Boston Medical", "bmc"),
    (r"Tufts|MelroseWakefield", "tufts_medicine"),
    (r"\bCHA\b|Cambridge Health Alliance", "cha"),
    (r"South Shore Health", "south_shore_health"),
    (r"Children's", "boston_childrens"),
    (r"Dana-Farber", "dana_farber"),
]
# hospitals.yaml entity -> census hospital_mrf "local copy" file name stem
MRF_STEMS = {"mgh": "mgh", "brigham": "brigham", "faulkner": "faulkner", "bmc": "bmc",
             "bidmc": "bidmc", "cha": "cha", "mtauburn": "mtauburn", "tufts": "tufts",
             "childrens": "childrens"}  # fmt: skip
GENERIC_NAME = re.compile(r"^\(clinicians, no group name\)$", re.I)
NAME_NOISE = re.compile(r"\s*\((CMS-listed clinicians at this address)\)\s*", re.I)
CLIN_TIN = re.compile(r"(\d{9,10})\((\d+)/(\d+) \"([^\"]*)\"\)")


def slug(s: str, n: int = 48) -> str:
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:n].strip("_") or "site"


def _flags(r: dict[str, str]) -> list[str]:
    return [f for f in r["flags"].split(";") if f]


def is_active(r: dict[str, str]) -> bool:
    return not any(x in r["flags"] for x in INACTIVE)


def n_sources(r: dict[str, str]) -> int:
    return sum(r[c] == "1" for c in SRC_COLS)


def ownership(r: dict[str, str]) -> str:
    detail = f"{r['ownership_detail']} {r['operator_parent']}"
    if re.search(r"Atrius", detail):
        return "payer_owned"
    if re.search(r"community health center|FQHC", detail, re.I):
        return "community_health_center"
    if re.search(r"AFC Urgent Care|now AFC", detail):
        return "franchise"
    return r["ownership"] or "unknown"


def billing(r: dict[str, str], site_type: str) -> tuple[str, str]:
    b = r["billing_type"]
    if site_type == "ambulatory_surgery_center":
        return ("asc", "likely") if b.startswith("asc_") else ("unknown", "unknown")
    if b.startswith("hospital_outpatient"):
        return "hospital_outpatient", "likely" if b.endswith("_likely") else "stated"
    if b.startswith("asc_"):
        if site_type == "ambulatory_surgery_center":
            return "asc", "likely"
        return "unknown", "unknown"
    if b.startswith("office_visit"):
        if site_type == "hospital_outpatient":
            return "unknown", "unknown"
        return "office_visit", "likely" if b.endswith("_likely") else "stated"
    return "unknown", "unknown"


def site_type_of(r: dict[str, str]) -> str:
    cat = r["category"]
    if cat == "urgent_care":
        return "urgent_care"
    if cat == "asc_endo":
        return "ambulatory_surgery_center"
    if r["billing_type"].startswith("hospital_outpatient"):
        return "hospital_outpatient"
    return "specialist_office"


def service_areas(r: dict[str, str]) -> list[str]:
    if r["category"] in CATEGORY_AREAS:
        return CATEGORY_AREAS[r["category"]]
    areas = []
    for part in r["cms_specialty_counts"].split(";"):
        k = part.split(":")[0].strip()
        if SPEC_AREAS.get(k) and SPEC_AREAS[k] not in areas:
            areas.append(SPEC_AREAS[k])
    return areas or ["ortho", "skin", "gi"]


def system_id(r: dict[str, str]) -> str | None:
    if r["ownership"] != "hospital_system":
        return None
    detail = f"{r['ownership_detail']} {r['operator_parent']}"
    for rx, sid in SYSTEMS:
        if re.search(rx, detail):
            return sid
    return None


def hospital_entity(r: dict[str, str]) -> str | None:
    m = re.search(r"hospital_mrfs/([a-z_]+)_standardcharges", r["hospital_mrf"])
    if not m:
        return None
    return next((e for e, stem in MRF_STEMS.items() if stem == m.group(1)), None)


def tins_of(r: dict[str, str]) -> tuple[list[str], list[str], str | None]:
    eins: list[str] = []
    npis: list[str] = []
    notes = []
    for t in [x for x in r["tins"].split(";") if x]:
        eins.append(normalize_tin(t))
    if r["tins"]:
        notes.append(f"org: {r['tin_sources']}")
    clin = CLIN_TIN.findall(r["clinician_billing_tins_bcbs"])
    for tin, k, n, name in clin:
        if len(tin) == 10:
            try:
                check_npi(tin)
            except ValueError:
                continue
            if tin not in npis:
                npis.append(tin)
        elif tin not in eins:
            eins.append(normalize_tin(tin))
    if clin:
        notes.append(
            "clinician billing TINs in BCBS TiC (share of the site's CMS clinicians >= 25%): "
            + "; ".join(f"{t} {k}/{n} {nm}" for t, k, n, nm in clin)
        )
    src = f"clinic-census.csv {r['site_id']}: " + " | ".join(notes) if notes else None
    return eins, npis, src


def booking(r: dict[str, str]) -> list[dict[str, Any]]:
    url, kind = r["booking_url"], r["booking_kind"]
    if not url.startswith("https://"):
        return (
            [{"kind": "walk_in", "provider": "none", "label": "Walk in"}]
            if kind == "walk_in"
            else []
        )
    provider = {"solv_online": "solv", "epic_on_my_way": "on_my_way"}.get(kind, "operator_site")
    label = {"solv": "Reserve a spot", "on_my_way": "Save your spot"}.get(provider, "Book online")
    out = [{"kind": "deep_link", "provider": provider, "label": label, "url": url}]
    if kind == "walk_in":
        out.append({"kind": "walk_in", "provider": "none", "label": "Walk in"})
    return out


def clean_name(r: dict[str, str]) -> str:
    n = NAME_NOISE.sub("", r["name"]).strip()
    if GENERIC_NAME.match(n) or not n:
        n = f"Clinicians at {r['address'].title()}"
    return n


def _dph_services() -> dict[str, list[dict[str, Any]]]:
    p = SITES_DIR / "dph_services.yaml"
    return (yaml.safe_load(p.read_text()) or {}).get("by_site_key", {}) if p.exists() else {}


def dph_offered(
    r: dict[str, str], services: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """DPH service evidence at this address, only when the census matched THIS site to that DPH
    list (a licence in the building does not cover every tenant: census pitfall 4)."""
    out = []
    for e in services.get(r["site_key"], []):
        from_uc = e["source"].startswith("DPH/HPC urgent care")
        if (from_uc and r["src_dph_uc2024"] == "1") or (
            not from_uc and r["src_dph_facility"] == "1"
        ):
            if all(o["service"] != e["service"] for o in out):
                out.append(e)
    return out


def from_census(
    r: dict[str, str], as_of: date, services: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    st = site_type_of(r)
    bt, conf = billing(r, st)
    eins, npis, tsrc = tins_of(r)
    org_npis = []
    for n in [x for x in r["org_npis"].split(";") if x]:
        try:
            org_npis.append(check_npi(n))
        except ValueError:
            pass
    srcs = [c.removeprefix("src_") for c in SRC_COLS if r[c] == "1"]
    if "registry_only" in r["flags"]:
        listing = "registry_only"  # the census's own judgement wins over a source count
    elif r["src_web"] == "1":
        listing = "web_verified"
    elif len(srcs) >= 2:
        listing = "multi_registry"
    else:
        listing = "registry_only"
    he = hospital_entity(r) if bt in ("hospital_outpatient", "unknown") else None
    pediatric = (
        "pediatric" in _flags(r)
        and bool(re.search(r"PEDIATRIC|PEDIATIC|CHILDREN|\bKIDS", r["name"], re.I))
        and not re.search(r"\bADULT", r["name"], re.I)
    )
    offered = [
        {"service": "visit", "evidence": "census_category", "source": f"clinic-census.csv {r['site_id']} category {r['category']}",
         "checked_at": r["last_checked"] or as_of.isoformat()}
    ] if r["category"] != "asc_endo" else [
        {"service": "endoscopy", "evidence": "census_category", "source": f"clinic-census.csv {r['site_id']} category asc_endo",
         "checked_at": r["last_checked"] or as_of.isoformat()}
    ]  # fmt: skip
    site: dict[str, Any] = {
        "id": "",
        "census_id": r["site_id"],
        "name": clean_name(r),
        "site_type": st,
        "operator": (r["operator_parent"] or r["ownership_detail"] or clean_name(r))[:120],
        "system_id": system_id(r),
        "hospital_entity_id": he,
        "billing_type": bt,
        "billing_type_source": r["billing_evidence"]
        or f"clinic-census.csv {r['site_id']}: billing_type {r['billing_type']}",
        "billing_type_confidence": conf,
        "ownership": ownership(r),
        "ownership_detail": r["ownership_detail"] or None,
        "children_only": pediatric,
        "address": {"street": r["address"], "city": r["town"], "state": "MA", "zip": r["zip"]},
        "booking": booking(r),
        "service_areas": service_areas(r),
        "type_2_npis": org_npis,
        "tins": eins,
        "tins_source": tsrc,
        "tin_npis": npis,
        "listing_status": listing,
        "listing_checked_at": r["last_checked"] or as_of.isoformat(),
        "offered": offered
        + [
            o
            for o in dph_offered(r, services or {})
            if o["service"] not in {x["service"] for x in offered}
        ],
        "notes": f"registries: {', '.join(srcs) or 'none'}; flags: {r['flags'] or 'none'}",
    }
    if r["lat"] and r["lon"]:
        site["coords"] = {
            "lat": round(float(r["lat"]), 6),
            "lon": round(float(r["lon"]), 6),
            "geocoded_by": "census_batch" if "Census" in r["geocode_source"] else "operator_page",
            "geocoded_at": r["last_checked"] or as_of.isoformat(),
        }
    return site


def hospital_sites(as_of: date, data_dir: Path) -> list[dict[str, Any]]:
    from app.etl.config import load_sources
    from app.registries import all_hospitals

    addrs = yaml.safe_load((SITES_DIR / "hospital_addresses.yaml").read_text())["hospitals"]
    hospitals = all_hospitals()
    out = []
    for spec in load_sources().rate_row_sources:
        h = hospitals[spec.entity_id]
        a = addrs[spec.entity_id]
        m = re.match(r"^(\d{9})_", Path(spec.url or "").name) or re.search(
            r"/(\d{2}-?\d{7})_", spec.url or ""
        )
        tins = [normalize_tin(m.group(1))] if m else []
        children = h.name.lower().find("child") >= 0
        out.append(
            {
                "id": slug(h.name),
                "name": h.name,
                "site_type": "hospital_outpatient",
                "operator": h.system,
                "system_id": next((sid for rx, sid in SYSTEMS if re.search(rx, h.system + " " + h.name)), None),
                "hospital_entity_id": spec.entity_id,
                "billing_type": "hospital_outpatient",
                "billing_type_source": "hospital campus: hospital outpatient departments add a facility fee",
                "billing_type_confidence": "stated",
                "ownership": "hospital_system",
                "children_only": children,
                "address": a["address"],
                "coords": {"lat": h.lat, "lon": h.lng, "geocoded_by": "hospital_registry", "geocoded_at": as_of.isoformat()},
                "service_areas": ["ortho", "skin", "gi"],
                "type_2_npis": list(spec.npis),
                "tins": tins,
                "tins_source": f"EIN in the hospital's own price-file name ({Path(spec.url or '').name})" if tins else None,
                "listing_status": "web_verified",
                "listing_checked_at": as_of.isoformat(),
                "notes": f"address: {a['source']}",
            }
        )  # fmt: skip
    return out


POSTED_SERVICE = [(r"x-?ray", "xray"), (r"\bMRI\b", "mri"), (r"ultrasound", "ultrasound"),
                  (r"\bCT\b", "ct"), (r"injection", "joint_injection")]  # fmt: skip


def posted_offered(site: dict[str, Any]) -> list[dict[str, Any]]:
    """A posted self-pay price for X-rays is evidence the site does X-rays (P1 problem 14)."""
    out = []
    for p in site.get("cash_prices") or []:
        for rx, svc in POSTED_SERVICE:
            if re.search(rx, p["label"], re.I):
                out.append({"service": svc, "codes": p.get("codes") or [], "evidence": "posted_price",
                            "source": p["source_url"], "checked_at": p["checked_at"]})  # fmt: skip
    return out


def _merge(base: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in cur.items():
        if k in ("match_census_id", "match_hospital_entity_id") or v in (None, [], ""):
            continue  # an empty curated field never wipes a derived one
        out[k] = v
    out["offered"] = list(out.get("offered") or []) + posted_offered(out)
    return out


def apply_billing(s: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """billing_structure.yaml (``python -m app.sites.billing``) settles an unknown billing type
    from public structure (R7): DPH hospital licence, HPC RPO provider-based status, NPPES."""
    res = (doc.get("resolved") or {}).get(s.get("census_id") or "")
    if s.get("billing_type") != "unknown" or not res:
        return s
    s = dict(s)
    s["billing_type"] = res["billing_type"]
    s["billing_type_confidence"] = res["confidence"]
    s["billing_type_source"] = f"{'+'.join(res['rules'])}: {res['source']}"
    if (
        s["site_type"] == "ambulatory_surgery_center"
        and res["billing_type"] == "hospital_outpatient"
    ):
        # licensed as part of a hospital (DPH satellite), so it bills as a hospital outpatient
        # department, not as an ASC (contract: billing asc <=> site_type ASC)
        s["site_type"] = "hospital_outpatient"
        s["notes"] = (
            s.get("notes") or ""
        ) + "; site_type from billing_structure (hospital licence)"
    return s


def build(
    census: Path, as_of: date, data_dir: Path | None = None, *, use_billing: bool = True
) -> tuple[SitesFile, SitesFile, dict[str, Any]]:
    rows = list(csv.DictReader(census.open(newline="")))
    report: dict[str, Any] = {"census": census.name, "census_rows": len(rows)}
    active = [r for r in rows if is_active(r)]
    report["active"] = len(active)
    restricted = [r for r in active if any(x in r["flags"] for x in RESTRICTED)]
    report["restricted_left_out"] = sorted(r["site_id"] for r in restricted)
    inactive_registry = [
        r for r in rows if "registry_only" in r["flags"]
        and not any(x in r["flags"] for x in ("closed", "terminated", "remove"))
        and not any(x in r["flags"] for x in RESTRICTED)
    ]  # fmt: skip
    curated = yaml.safe_load((SITES_DIR / "curated.yaml").read_text()) or {}
    cur_by_census = {
        c["match_census_id"]: c for c in curated.get("sites", []) if c.get("match_census_id")
    }
    cur_by_hosp = {
        c["match_hospital_entity_id"]: c
        for c in curated.get("sites", [])
        if c.get("match_hospital_entity_id")
    }
    cands: list[dict[str, Any]] = []
    services = _dph_services()
    billing_doc = billing_mod.load() if use_billing else {}
    for r in [x for x in active if x not in restricted] + inactive_registry:
        s = from_census(r, as_of, services)
        s = apply_billing(s, billing_doc)
        if r["site_id"] in cur_by_census:
            s = _merge(s, cur_by_census[r["site_id"]])
        cands.append(s)
    for h in hospital_sites(as_of, data_dir or REPO / "data"):
        if h["hospital_entity_id"] in cur_by_hosp:
            h = _merge(h, cur_by_hosp[h["hospital_entity_id"]])
        cands.append(h)
    # ids: curated / hospital ids are fixed; census ids = name + town, de-duplicated by census number
    used: Counter[str] = Counter()
    for s in cands:
        if not s["id"]:
            base = slug(f"{s['name']} {s['address']['city']}", 56)
            s["id"] = base
        used[s["id"]] += 1
    for s in cands:
        if (
            used[s["id"]] > 1
            and s.get("census_id")
            and not s["id"].endswith(s["census_id"].lower())
        ):
            s["id"] = f"{s['id']}_{s['census_id'].lower()}"
    quotable, verify, reasons = [], [], Counter()
    for s in cands:
        why = []
        if s["listing_status"] == "registry_only":
            why.append("registry_only")
        if "coords" not in s:
            why.append("no_coordinates")
        if why:
            s["listing_status"] = "registry_only"
            s["notes"] = f"TO VERIFY ({', '.join(why)}); " + (s.get("notes") or "")
            reasons.update(why)
            if "coords" not in s:
                continue  # Site needs coordinates: listed in the report, not in the YAML
            verify.append(s)
        else:
            quotable.append(s)
    no_coords = [s["census_id"] for s in cands if "coords" not in s]
    sites = SitesFile(version=1, sites=[Site.model_validate(s) for s in quotable])
    by_census = {s.census_id: s for s in sites.sites if s.census_id}
    billing_todo = [
        BillingToVerify(census_id=cid, **{k: v for k, v in e.items() if k != "site_id"},
                        site_id=by_census[cid].id)
        for cid, e in sorted((billing_doc.get("to_verify") or {}).items())
        if cid in by_census and by_census[cid].billing_type == "unknown"
    ]  # fmt: skip
    todo = ToVerifyFile(
        version=1,
        sites=[Site.model_validate(s) for s in verify],
        billing_to_verify=billing_todo,
    )
    report |= {
        "sites_yaml": len(sites.sites),
        "to_verify_yaml": len(todo.sites),
        "to_verify_reasons": dict(reasons),
        "no_coordinates_not_written": no_coords,
        "hospital_sites": sum(1 for s in sites.sites if s.census_id is None),
        "by_site_type": dict(Counter(s.site_type for s in sites.sites)),
        "by_ownership": dict(Counter(s.ownership for s in sites.sites)),
        "by_billing_type": dict(Counter(s.billing_type for s in sites.sites)),
        "billing_resolved_by_structure": sum(
            1 for s in sites.sites if (s.census_id or "") in (billing_doc.get("resolved") or {})
        ),
        "billing_to_verify": len(todo.billing_to_verify),
        "children_only": sorted(s.id for s in sites.sites if s.children_only),
        "with_tins": sum(1 for s in sites.sites if s.tins),
        "with_tin_npis": sum(1 for s in sites.sites if s.tin_npis),
        "registry_only_flagged_rows_in_queue": len(inactive_registry),
        "offered_by_evidence": dict(Counter(o.evidence for x in sites.sites for o in x.offered)),
        "offered_by_service": dict(Counter(o.service for x in sites.sites for o in x.offered)),
    }
    return sites, todo, report


HEADER = """# GENERATED by `python -m app.sites.build` from {census} (+ curated.yaml, hospitals.yaml).
# Do not edit by hand: change data/sites/curated.yaml (hand-checked fields) and re-run.
# Contract: backend/app/sites/contracts.py (Site); docs/etl/sites.md.
"""


def dump(f: SitesFile, census: str) -> str:
    body = yaml.safe_dump(
        json.loads(f.model_dump_json(exclude_defaults=True)),
        sort_keys=False,
        allow_unicode=True,
        width=110,
    )
    return HEADER.format(census=census) + body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.sites.build")
    p.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    p.add_argument("--as-of", default="2026-10-24")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    a = p.parse_args(argv)
    sites, todo, report = build(a.census, date.fromisoformat(a.as_of))
    outs = {
        SITES_DIR / "sites.yaml": dump(sites, a.census.name),
        SITES_DIR / "to_verify.yaml": dump(todo, a.census.name),
        SITES_DIR / "build_report.json": json.dumps(report, indent=1, sort_keys=True) + "\n",
    }
    if a.check:
        stale = [str(k) for k, v in outs.items() if not k.exists() or k.read_text() != v]
        for s in stale:
            print(f"STALE {s}")
        return 1 if stale else 0
    for k, v in outs.items():
        k.write_text(v)
        print(k)
    print(
        json.dumps(
            {k: report[k] for k in ("census_rows", "active", "sites_yaml", "to_verify_yaml")}
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
