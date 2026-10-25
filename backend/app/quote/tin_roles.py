"""R3: whose TIN bills which line, per site, with where that came from.

An ambulatory surgery center bills its own facility fee on the professional claim form
(CMS-1500), so insurer (TiC) files list the center's fee under the center's TIN as
``billing_class: professional``. Read as a doctor's fee, that row priced MGB Endoscopy Braintree's
"doctor" line at $2,038 and summed MGB HP's $328-582 fee twice. The surgeon and the
anesthesiologist bill under their own groups' TINs.

Roles:

* ``facility``: the TIN's rows price the facility line only (an ASC's own TIN);
* ``professional``: the TIN's rows price the doctor line only (an office, a physician group);
* ``by_billing_class``: the row's own TiC billing_class decides (a hospital: facility rows are the
  hospital's fee, professional rows its doctors').

``data/quote/tin_roles.yaml`` is written from the data by

    uv run --frozen python -m app.quote.tin_roles --pack <quote_pack.sqlite>

Each entry is the site's billing-type rule (engine.yaml ``tin_role_by_billing``) unless the TiC
business names on the TIN's rows say otherwise (``source`` names which): a surgery-center name on
a TIN at a non-ASC site makes it ``facility``; a physician-group name at an ASC makes it
``professional``. The engine reads the file; a TIN it does not list takes the rule.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import yaml

from app.quote.store import REPO_ROOT

FACILITY_NAME = re.compile(
    r"ENDOSCOPY CENTER|SURGERY CENTER|SURGICAL CENTER|SURGICENTER|AMBULATORY SURG|\bASC\b",
)
PROFESSIONAL_NAME = re.compile(
    r"PHYSICIAN|ASSOCIATES|MEDICAL GROUP|GASTROENTEROLOG|ANESTHESI|FACULTY|\bP\.?C\.?$|\bMD\b",
)
HOSPITAL_NAME = re.compile(r"HOSPITAL")
ROLES = ("facility", "professional", "by_billing_class")


def effective_billing(site, unknown_as: str) -> str:
    """P9: unknown billing is priced as a hospital clinic; an ASC whose billing is unknown as an
    ASC (the Site contract ties asc to that site type)."""
    if site.billing_type != "unknown":
        return site.billing_type
    return "asc" if site.site_type == "ambulatory_surgery_center" else unknown_as


def load_roles(path: Path) -> dict[tuple[str, str], str]:
    """(site id, TIN) -> role, from the committed table (absent file = no entries)."""
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    out: dict[tuple[str, str], str] = {}
    for e in doc.get("roles") or []:
        if e["role"] not in ROLES:
            raise ValueError(f"tin_roles: bad role {e['role']!r} for {e['site_id']}")
        if not e.get("source"):
            raise ValueError(f"tin_roles: {e['site_id']} {e['tin']} needs its source")
        tin = e["tin"]
        if isinstance(tin, int):  # YAML 1.1 reads an unquoted 0-led 9-digit TIN as a number
            tin = f"{tin:09d}"
        out[(e["site_id"], str(tin))] = e["role"]
    return out


def derive(sites, names_by_tin: dict[str, set[str]], rule: dict[str, str],
           unknown_as: str) -> list[dict]:  # fmt: skip
    """One entry per (site, own TIN): the role and its source."""
    out = []
    for s in sorted(sites, key=lambda s: s.id):
        billing = effective_billing(s, unknown_as)
        base = rule[billing]
        for tin in dict.fromkeys([*s.tins, *s.tin_npis, *s.type_2_npis]):
            names = sorted(n for n in names_by_tin.get(tin, ()) if n)
            fac = [n for n in names if FACILITY_NAME.search(n.upper())]
            pro = [n for n in names if PROFESSIONAL_NAME.search(n.upper()) and n not in fac]
            role, source = base, f"billing_type_rule:{billing}"
            hosp = [n for n in names if HOSPITAL_NAME.search(n.upper())]
            if billing == "asc" and hosp:  # a hospital's TIN at its surgery center: the row says
                role, source = "by_billing_class", f"tic_business_name:{hosp[0]}"
            elif billing != "asc" and fac and not pro:
                role, source = "facility", f"tic_business_name:{fac[0]}"
            elif billing == "asc" and pro and not fac:
                role, source = "professional", f"tic_business_name:{pro[0]}"
            out.append({"site_id": s.id, "tin": tin, "role": role, "source": source,
                        "billing": billing})  # fmt: skip
    return out


def main() -> None:  # pragma: no cover - needs a real pack
    from app.quote.registry import ENGINE_CONFIG, Registry
    from app.quote.store import load_pack

    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    reg = Registry.load()
    cfg = yaml.safe_load(ENGINE_CONFIG.read_text())
    store = load_pack(a.pack, tins=reg.tins, census_ids=reg.census_ids)
    names: dict[str, set[str]] = defaultdict(set)
    for r in store.rows:
        if r.source_kind == "insurer_tic":
            names[r.tin].add(r.business_name)
    entries = derive(reg.sites.values(), names, cfg["tin_role_by_billing"],
                     cfg["unknown_billing_priced_as"])  # fmt: skip
    out = a.out or (REPO_ROOT / cfg["tin_roles_file"])
    doc = {
        "version": 1,
        "note": "Written by python -m app.quote.tin_roles from pack "
        f"{store.version.build_id}; do not edit by hand (fix the rule or the data).",
        "roles": entries,
    }
    for e in entries:
        e["tin"] = str(e["tin"])
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)
    out.write_text(re.sub(r"^  tin: ([0-9]+)$", r"  tin: '\1'", text, flags=re.M))
    changed = [e for e in entries if not e["source"].startswith("billing_type_rule")]
    print(f"{out}: {len(entries)} site TINs, {len(changed)} set by a TiC business name")


if __name__ == "__main__":  # pragma: no cover
    main()
