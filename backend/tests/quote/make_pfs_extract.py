"""Write the tiny committed Medicare PFS extract the quote tests use until A3's PFS reader lands.

    cd backend
    uv run --frozen python tests/quote/make_pfs_extract.py \\
        --pfs /Users/austin/carecost/data/raw/government/cms_pfs/PPRRVU2026_Jan_nonQPP.csv \\
        --gpci /Users/austin/carecost/data/raw/government/cms_pfs/GPCI2026.csv

Reads the CMS 2026 January RVU file (RVU26A, non-QPP) and the CY2026 GPCI addendum, and computes
the Metropolitan Boston (MAC 14212, locality 01) payment for every code a care path or the ETL
code list prices, for modifiers none / 26 / TC:

    payment = (work RVU x PW GPCI + PE RVU x PE GPCI + MP RVU x MP GPCI) x CF

with the facility PE RVU for ``plan_raw: facility`` and the non-facility PE RVU for
``plan_raw: non_facility`` (codes whose non-facility indicator is NA get no non-facility row).
Anchor (checked by tests/quote/test_engine.py): 99203 = $75.54 facility / $130.58 non-facility,
73030-26 = $9.75. Anesthesia codes (status J) have no RVUs and are left out (ANES reader, A3).

Output rows follow the RateRow columns the pack builder reads (``app.quote.pack.gov_rows``):
``source_kind: medicare_pfs``, ``billing_class: professional``, ``plan_raw`` = setting, ``row_ref``
= ``cms_pfs_rvu26a:<sha12>:<line number in the CSV>``. A3's reader replaces this file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import yaml

from app.quote.pack import priced_codes

FIX = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
SOURCE_ID = "cms_pfs_rvu26a"
LOCALITY = ("14212", "01")  # Metropolitan Boston


def _num(v: str) -> float:
    return float(v) if v.strip() else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pfs", type=Path, required=True)
    ap.add_argument("--gpci", type=Path, required=True)
    a = ap.parse_args()
    sha = hashlib.sha256(a.pfs.read_bytes()).hexdigest()
    gp = None
    with a.gpci.open() as f:
        for row in csv.reader(f):
            if len(row) > 7 and row[0].strip() == LOCALITY[0] and row[2].strip() == LOCALITY[1]:
                gp = (float(row[5]), float(row[6]), float(row[7]))  # PW (1.0 floor), PE, MP
    if gp is None:
        raise SystemExit("Metropolitan Boston GPCI not found")
    codes = priced_codes()
    out = []
    with a.pfs.open(newline="") as f:
        for line_no, row in enumerate(csv.reader(f), start=1):
            if line_no <= 10 or row[0] not in codes or row[1] not in ("", "26", "TC"):
                continue
            work, pe_nf, nf_na, pe_f, mp = row[5], row[6], row[7], row[8], row[10]
            cf = _num(row[25])
            if row[3] not in ("A", "R", "T") or cf == 0:
                continue  # not separately paid under the PFS (bundled, carrier-priced, anesthesia)
            for setting, pe in (("facility", pe_f), ("non_facility", pe_nf)):
                if setting == "non_facility" and nf_na.strip() == "NA":
                    continue
                pay = (_num(work) * gp[0] + _num(pe) * gp[1] + _num(mp) * gp[2]) * cf
                key = f"{row[0]}|{row[1]}|{setting}"
                out.append({
                    "row_ref": f"{SOURCE_ID}:{sha[:12]}:{line_no}",
                    "row_id": f"{hashlib.sha256(key.encode()).hexdigest()[:16]}:0",
                    "source_id": SOURCE_ID, "source_kind": "medicare_pfs", "row_kind": "payer_rate",
                    "code": row[0], "modifiers": row[1], "component": "professional",
                    "billing_class": "professional", "setting": "both", "rev_code": "",
                    "payer_id": "", "product": "", "line_of_business": "medicare",
                    "plan_raw": setting, "amount": f"{round(pay, 2):.2f}",
                    "amount_method": "stated", "negotiated_pct": "", "discounted_cash": "",
                    "gross": "", "stage_row": line_no,
                })  # fmt: skip
    csv_path = FIX / "gov_pfs_extract.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    doc = {
        "version": 2,
        "note": "CMS PFS 2026 RVU26A (January, non-QPP) x CY2026 GPCI, Metropolitan Boston. "
        "Written by tests/quote/make_pfs_extract.py; replaced by A3's PFS reader.",
        "sources": {
            SOURCE_ID: {
                "source_kind": "medicare_pfs",
                "publisher": "CMS (Medicare, Boston 2026)",
                "source_file": a.pfs.name,
                "source_sha256": sha,
                "source_date": "2026-01-01",
                "last_updated": "2026-01-01",
                "fetched_at": "2026-05-02",  # rvu26a.zip download date (file mtime)
                "source_rule": "fee_schedule_annual",
                "our_rule": "fee_schedule_per_release",
                "expected_by": "2027-01-01",
                "our_refresh_due": None,
                "payer_id": None,
                "product": "",
                "network_label": "",
                "line_of_business": "",
            }
        },
    }
    (FIX / "gov_pfs_extract.sources.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"{csv_path.name}: {len(out)} rows (sha {sha[:12]})")


if __name__ == "__main__":
    main()
