"""Build/check the CPT existence registry from the CMS 2026 PFS RVU file.

The registry stores only code -> PFS status (+ whether 26/TC professional/technical rows exist).
It deliberately stores no descriptors: CPT descriptions are AMA-copyrighted.

    python -m app.care_paths.cpt_registry --pfs ../data/raw/government/cms_pfs/PPRRVU2026_Jan_nonQPP.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.care_paths.loader import CARE_PATHS_DIR, REPO_ROOT, load_paths
from app.care_paths.models import CptEntry

DEFAULT_PFS_RELPATH = Path("data/raw/government/cms_pfs/PPRRVU2026_Jan_nonQPP.csv")
REGISTRY_FILE = CARE_PATHS_DIR / "cpt_registry_2026.json"

# Paraphrased from CMS RVU26AR.pdf Attachment A (status code values).
STATUS_LEGEND = {
    "A": "Active; separately paid under the PFS when covered",
    "B": "Bundled; payment is folded into other services",
    "C": "Contractor-priced case by case",
    "E": "Excluded from the PFS by regulation (e.g. many drugs); paid elsewhere if covered",
    "I": "Not valid for Medicare; Medicare uses another code",
    "J": "Anesthesia service; priced with anesthesia base units, not RVUs",
    "N": "Not covered by Medicare",
    "R": "Restricted coverage; contractor-priced if covered",
    "T": "Injection; paid only if nothing else PFS-payable is billed that day",
    "X": "Statutory exclusion (e.g. clinical lab tests); paid under another fee schedule",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_pfs(path: Path, codes: set[str]) -> dict[str, CptEntry]:
    status: dict[str, str] = {}
    mods: dict[str, set[str]] = {}
    with path.open(newline="", encoding="latin-1") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if row and row[0].strip() == "HCPCS":
                break
        for row in reader:
            if len(row) < 4:
                continue
            code, mod, st = row[0].strip(), row[1].strip(), row[3].strip()
            if code not in codes:
                continue
            if mod == "":
                status[code] = st
            else:
                status.setdefault(code, st)
                mods.setdefault(code, set()).add(mod)
    return {
        c: CptEntry(
            status=s, has_professional_technical_split=bool({"26", "TC"} & mods.get(c, set()))
        )
        for c, s in status.items()
    }


def used_codes() -> set[str]:
    return {c for p in load_paths().values() for s in p.steps for c in s.all_codes()}


def build(pfs: Path) -> dict:
    codes = used_codes()
    found = read_pfs(pfs, codes)
    missing = sorted(codes - set(found))
    if missing:
        raise SystemExit(f"codes not in {pfs.name}: {missing}")
    return {
        "source_file": pfs.name,
        "source_sha256": sha256_file(pfs),
        "release": "CMS PFS Relative Value File, 2026 January release (non-QPP), released 12/29/2025",
        "status_legend": STATUS_LEGEND,
        "codes": {c: found[c].model_dump() for c in sorted(found)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pfs", type=Path, default=REPO_ROOT / DEFAULT_PFS_RELPATH)
    ap.add_argument("--out", type=Path, default=REGISTRY_FILE)
    args = ap.parse_args()
    data = build(args.pfs)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(data['codes'])} codes to {args.out}")


if __name__ == "__main__":
    main()
