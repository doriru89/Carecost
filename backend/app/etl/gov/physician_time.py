"""CMS physician time for the care-path procedures (C3 item 12: anesthesia "with typical time").

    cd backend
    uv run --frozen --extra etl python -m app.etl.gov.physician_time [--zip FILE]
        -> data/etl/physician_time.yaml (committed; small: only care-path codes)

Source: CMS, CY 2026 PFS final rule (CMS-1832-F) download "Physician Work Time - Updated
01/08/2026" (``CY 2026 Efficiency Adjusted Work Times.csv``). For a procedure code the file gives
the median intra-service time (the procedure itself, minutes) and the total time; for an
anesthesia code (00100-01999) only ``Total_time`` is filled, which is CMS's typical anesthesia
time for that code. The quote engine uses the anesthesia time to say "with typical time, about
$Y" (base units + time units, 15 minutes per unit); it never sums it.

Without ``--zip`` the file is downloaded once over https from www.cms.gov (allowlist, size cap).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.etl.config import CONFIG_DIR

URL = "https://www.cms.gov/files/zip/cy-2026-pfs-final-rule-physician-work-time-updated-01-08-2026.zip"
LANDING = "https://www.cms.gov/medicare/payment/fee-schedules/physician/federal-regulation-notices/cms-1832-f"
RELEASE = "CY 2026 PFS final rule (CMS-1832-F), Physician Work Time, updated 2026-01-08"
OUT = CONFIG_DIR / "physician_time.yaml"
MAX_BYTES = 50_000_000


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_anesthesia(code: str) -> bool:
    return code.isdigit() and len(code) == 5 and "00100" <= code <= "01999"


def read_zip(data: bytes) -> tuple[str, dict[str, dict[str, Any]]]:
    """-> (csv member name, code -> {intra_min, total_min})."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in the zip, found {names}")
        text = z.read(names[0]).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    need = {"cpt_code", "Median_Intra_Service_Time", "Total_time"}
    if not rows or not need <= set(rows[0]):
        raise ValueError(f"{names[0]}: columns {sorted(need)} not found")
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = (r["cpt_code"] or "").strip().upper()
        if code:
            out[code] = {
                "intra_min": _num(r["Median_Intra_Service_Time"]),
                "total_min": _num(r["Total_time"]),
            }
    if len(out) < 5000:
        raise ValueError(f"{names[0]}: only {len(out)} codes parsed")
    return names[0], out


def build(
    data: bytes, codes: set[str], fetched_at: str, http_last_modified: str | None
) -> dict[str, Any]:
    member, table = read_zip(data)
    times: dict[str, dict[str, Any]] = {}
    missing = []
    for c in sorted(codes):
        t = table.get(c)
        if t is None:
            missing.append(c)
            continue
        if is_anesthesia(c):
            times[c] = {"kind": "anesthesia", "typical_anesthesia_min": t["total_min"]}
        else:
            times[c] = {"kind": "procedure", "intra_service_min": t["intra_min"],
                        "total_min": t["total_min"]}  # fmt: skip
    return {
        "version": 1,
        "source": {
            "publisher": "CMS",
            "release": RELEASE,
            "url": URL,
            "landing_url": LANDING,
            "member": member,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "http_last_modified": http_last_modified,
            "fetched_at": fetched_at,
            "codes_in_file": len(table),
        },
        "note": "anesthesia codes: Total_time = CMS typical anesthesia time (minutes); "
        "procedures: Median_Intra_Service_Time and Total_time (minutes)",
        "times": times,
        "not_in_file": missing,
    }


def main(argv: list[str] | None = None) -> int:
    from app.etl.config import load_codes

    p = argparse.ArgumentParser(prog="python -m app.etl.gov.physician_time")
    p.add_argument("--zip", type=Path, default=None, help="a local copy instead of downloading")
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    lm = None
    if a.zip:
        data = a.zip.read_bytes()
        fetched = datetime.fromtimestamp(a.zip.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds"
        )
    else:
        from app.etl.fetch import http_get_bytes

        data, _final, h = http_get_bytes(URL, ["www.cms.gov"], MAX_BYTES)
        lm = h.get("last-modified")
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    codes = set(load_codes().path_codes)  # every care-path code (R9)
    doc = build(data, codes, fetched, lm)
    head = (
        "# GENERATED by `python -m app.etl.gov.physician_time` (CMS physician time, C3 item 12).\n"
    )
    a.out.write_text(head + yaml.safe_dump(doc, sort_keys=False, width=110))
    n = len(doc["times"])
    print(f"PTIME  {a.out}: {n} care-path codes, not in file: {doc['not_in_file']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
