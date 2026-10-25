"""P1 problem 6: which radiology groups read images at each hospital, and their billing TINs.

    python -m app.sites.radiology --dac DAC_NationalDownloadableFile.csv --tic-index idx_bcbs.json

Public sources only:

* CMS Doctors and Clinicians national file (data.cms.gov dataset mj5m-pzi6): one row per
  clinician x practice address, with primary specialty and the group (``Facility Name`` /
  ``org_pac_id``) the clinician bills through at that address.
* BCBS MA TiC provider references (the payer's own published file): NPI -> TIN (EIN) of every
  provider group the NPI appears in.

Method: radiologists (primary specialty diagnostic / interventional radiology, nuclear medicine)
whose DAC practice address is a hospital campus (same census address key as
``hospital_addresses.yaml``) -> group by DAC group -> map each radiologist's NPI to its TiC TINs
and keep a TIN carried by >= 25% of the group's radiologists (the census's clinician-TIN rule).
Output: ``data/sites/radiology_groups.yaml``. The engine (stream C) can then search the group's
TIN for -26 reading fees at a hospital site instead of only the hospital's own doctor groups.
Limits: DAC lists Medicare-enrolled clinicians only; TiC membership is not proof of a contract
rate for a code.
"""

from __future__ import annotations

import argparse
import csv
import json
import mmap
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from app.sites.address import akey
from app.sites.build import SITES_DIR

RAD_SPECS = {"DIAGNOSTIC RADIOLOGY", "INTERVENTIONAL RADIOLOGY", "NUCLEAR MEDICINE"}
MIN_SHARE = 0.25


def hospital_keys() -> dict[str, str]:
    addrs = yaml.safe_load((SITES_DIR / "hospital_addresses.yaml").read_text())["hospitals"]
    out = {}
    for ent, a in addrs.items():
        k = akey(a["address"]["street"], a["address"]["zip"])
        if k:
            out[k] = ent
    return out


def radiologists_at_hospitals(
    dac: Path, keys: dict[str, str]
) -> dict[tuple[str, str, str], set[str]]:
    """(entity, group name, org_pac_id) -> radiologist NPIs."""
    out: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    with dac.open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("State") != "MA" or r.get("pri_spec", "").upper() not in RAD_SPECS:
                continue
            k = akey(r.get("adr_ln_1"), r.get("ZIP Code"))
            if k in keys:
                out[
                    (keys[k], (r.get("Facility Name") or "").strip(), r.get("org_pac_id") or "")
                ].add(r["NPI"])
    return out


def tic_tins(index: Path, npis: set[str]) -> dict[str, list[tuple[str, str, str]]]:
    """NPI -> [(tin, tin_type, business_name)] from the TiC provider-reference index, read with a
    regex over the mapped file (it is ~600 MB of JSON)."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    with index.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for m in re.finditer(rb'"(\d{10})": (\[\[.*?\]\])', mm):
            npi = m.group(1).decode()
            if npi in npis:
                out[npi] = [(t, ty, bn) for t, ty, bn, _gid in json.loads(m.group(2))]
    return out


def build(dac: Path, index: Path, label: str) -> dict[str, Any]:
    keys = hospital_keys()
    groups = radiologists_at_hospitals(dac, keys)
    all_npis = set().union(*groups.values()) if groups else set()
    tins = tic_tins(index, all_npis)
    by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (ent, name, pac), npis in sorted(groups.items()):
        c: Counter[tuple[str, str]] = Counter()
        names: dict[str, str] = {}
        for n in npis:
            for t, ty, bn in {(t, ty, bn) for t, ty, bn in tins.get(n, [])}:
                if ty == "ein":
                    c[(t, ty)] += 1
                    names.setdefault(t, bn)
        keep = [
            {"tin": t, "radiologists": k, "share": round(k / len(npis), 2), "tic_business_name": names[t]}
            for (t, _ty), k in c.most_common() if k / len(npis) >= MIN_SHARE
        ]  # fmt: skip
        by_entity[ent].append({
            "group": name, "org_pac_id": pac, "radiologists": len(npis),
            "radiologists_in_tic": sum(1 for n in npis if n in tins), "tins": keep,
        })  # fmt: skip
    for ent in by_entity:
        by_entity[ent].sort(key=lambda g: -g["radiologists"])
    return {
        "version": 1,
        "method": "CMS DAC radiologists at the hospital's address key -> BCBS TiC NPI->TIN, TINs on >=25% of the group",
        "sources": {"dac": dac.name, "tic_index": label},
        "hospitals_with_radiologists": len(by_entity),
        "hospitals": dict(sorted(by_entity.items())),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.sites.radiology")
    p.add_argument("--dac", type=Path, required=True)
    p.add_argument("--tic-index", type=Path, required=True)
    p.add_argument(
        "--dac-label",
        default="CMS Doctors and Clinicians (data.cms.gov mj5m-pzi6, modified 2026-10-02)",
    )
    a = p.parse_args(argv)
    with a.tic_index.open() as f:
        head = f.read(300)
    label = re.search(r'"label": "([^"]+)"', head)
    out = build(a.dac, a.tic_index, label.group(1) if label else a.tic_index.name)
    out["sources"]["dac"] = a.dac_label
    (SITES_DIR / "radiology_groups.yaml").write_text(
        "# GENERATED by `python -m app.sites.radiology` (P1 problem 6). docs/etl/sites.md.\n"
        + yaml.safe_dump(out, sort_keys=False, width=110, allow_unicode=True)
    )
    print(json.dumps({k: out[k] for k in ("hospitals_with_radiologists",)}),
          {e: [(g["group"][:40], g["radiologists"], [t["tin"] for t in g["tins"]]) for g in v[:2]] for e, v in out["hospitals"].items()})  # fmt: skip
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
