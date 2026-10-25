"""MA DPH registries for the monthly site check (D28, census §8 inputs 2).

    python -m app.sites.dph fetch [--headless]    plain headed browser clicks mass.gov's own links
    python -m app.sites.dph check [--as-of D]     parse, count, anchor, diff -> data/sites/dph_check.json
                                                  + data/sites/dph_services.yaml (offered, P1 #14)

What exists (looked for first, D28, 2026-10-24):

* The DPH "Urgent care and retail clinics" dashboard is an ArcGIS Instant App (item
  f8e64de306674887ab98451a9cbe0091, owner WebEOC_MDPH_OPEM). Its web map's clinic layer
  (``HPC_Retail_and_Urgent_Care_Clinics_Dataset_June_2024_v5``, item f5f461b3...) answers
  "Item does not exist or is inaccessible": **no public API for the clinic data**. Only its
  "Acute Care Hospitals" layer (``HOSPITALS_PT``, 72 features) is public.
* The facility list and the licensed-clinic services list have no API: XLSX downloads only.

So the three files are fetched with ``app.etl.gov.browser`` (real UA, headed, no fingerprint
changes, no stealth). A 403 or captcha stops the run; then the files go in
``<data>/raw/manual/dph/`` by hand and ``check`` reads them from there (``access: manual``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.etl.config import Paths
from app.sites.address import akey, in_scope, z5

REPO = Path(__file__).resolve().parents[3]
SITES_DIR = REPO / "data" / "sites"
ALLOWED = ["mass.gov"]
FACILITIES_PAGE = "https://www.mass.gov/info-details/find-information-about-licensed-or-certified-health-care-facilities"
UC_PAGE = "https://www.mass.gov/info-details/urgent-care-and-retail-clinics-in-massachusetts"


@dataclass(frozen=True)
class DphFile:
    name: str
    landing_url: str
    link_href: str
    cadence: str


FILES = (
    DphFile("facilities", FACILITIES_PAGE,
            "/doc/list-of-health-care-facilities-licensed-or-certified-by-the-division/download", "monthly"),
    DphFile("clinic_services", FACILITIES_PAGE, "/doc/list-of-licensed-clinics-and-services-provided/download", "monthly"),
    DphFile("uc_retail", UC_PAGE, "/doc/urgent-care-and-retail-clinics-data/download", "irregular (data 2024-07)"),
)  # fmt: skip

# Census §8 step 7 anchors and baselines (2026-10-24 census run, Sept 2026 files)
ANCHOR_IDS = {"2ED8": "BIDMC Chelsea (MEDICAL CARE CENTER NORTH), hospital satellite"}
BASELINE_IN_SCOPE = {"Hospital Satellite": 169, "Clinic": 166, "Clinic Satellite": 132,
                     "Ambulatory Surgical Ctr.": 17, "Acute Hospital": 21}  # fmt: skip
MAX_COUNT_CHANGE = 0.15


def dph_dir(paths: Paths) -> Path:
    return paths.data / "raw" / "dph"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _store(paths: Paths, f: DphFile, src: Path, rec: dict[str, Any]) -> dict[str, Any]:
    sha = _sha(src)
    dest = dph_dir(paths) / f.name / f"{sha}{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    status = "unchanged" if dest.exists() else "new"
    if status == "new":
        shutil.copy2(src, dest)
    rec |= {"name": f.name, "sha256": sha, "bytes": src.stat().st_size, "filename": src.name,
            "relpath": str(dest.relative_to(dph_dir(paths))), "status": status}  # fmt: skip
    with (dph_dir(paths) / "manifest.jsonl").open("a") as m:
        m.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def cmd_fetch(a: argparse.Namespace, paths: Paths) -> int:
    from app.etl.gov.browser import BrowserBlocked, download_via_page

    errors = 0
    for f in FILES:
        with tempfile.TemporaryDirectory(prefix=f"dph-{f.name}-") as tmp:
            try:
                dl = download_via_page(
                    f.landing_url, f.link_href, Path(tmp), ALLOWED, headless=a.headless
                )
            except BrowserBlocked as e:
                print(f"BLOCKED {f.name}: {e}. Stop; download it by hand into "
                      f"{dph_dir(paths).parent / 'manual' / 'dph'} (access: manual).")  # fmt: skip
                errors += 1
                continue
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rec = _store(paths, f, dl.path, {
                "method": "browser", "fetched_at": now, "landing_url": dl.landing_url,
                "link_url": dl.link_url, "final_url": dl.final_url, "user_agent": dl.user_agent,
                "landing_status": dl.landing_status,
            })  # fmt: skip
            print(
                f"{rec['status'].upper():6} {f.name}: {rec['filename']} {rec['sha256'][:12]} {rec['bytes']:,} bytes"
            )
    return 1 if errors else 0


def current(paths: Paths, name: str) -> tuple[Path, dict[str, Any]] | None:
    """Newest stored copy (browser), else a hand download in raw/manual/dph/<name>*.xlsx."""
    man = dph_dir(paths) / "manifest.jsonl"
    recs = (
        [json.loads(x) for x in man.read_text().splitlines() if x.strip()] if man.exists() else []
    )
    recs = [r for r in recs if r["name"] == name]
    if recs:
        return dph_dir(paths) / recs[-1]["relpath"], recs[-1]
    manual = sorted((paths.data / "raw" / "manual" / "dph").glob(f"{name}*.xlsx"))
    if manual:
        p = manual[-1]
        return p, {"method": "manual", "filename": p.name, "sha256": _sha(p),
                   "fetched_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}  # fmt: skip
    return None


def _rows(path: Path, sheet: int = 0) -> list[tuple[Any, ...]]:
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[sheet]
    return [tuple(r) for r in ws.iter_rows(values_only=True)]


def _header_index(rows: list[tuple[Any, ...]], first: str) -> int:
    for i, r in enumerate(rows):
        if r and str(r[0] or "").strip() == first:
            return i
    raise ValueError(f"no header row starting with {first!r}")


def parse_facilities(path: Path) -> tuple[list[dict[str, str]], date | None]:
    rows = _rows(path)
    as_of = next((r[0].date() for r in rows[:12] if isinstance(r[0], datetime)), None)
    h = _header_index(
        rows, "Facility"
    )  # two-line header: "Type of / Facility", "DPH Facility / ID Number"
    out = []
    for r in rows[h + 1 :]:
        if not r or not r[0] or not r[1]:
            continue
        out.append({"type": str(r[0]).strip(), "id": str(r[1]).strip(), "name": str(r[2] or "").strip(),
                    "street": str(r[3] or "").strip(), "city": str(r[4] or "").strip(), "zip": z5(r[5])})  # fmt: skip
    return out, as_of


SERVICE_COLS = {"Physical Rehab": "physical_therapy", "Surgical": None, "Radiology (MRI)": "mri",
                "Medical": "visit"}  # fmt: skip


def parse_clinic_services(path: Path) -> list[dict[str, Any]]:
    rows = _rows(path)
    h = _header_index(rows, "Clinic Name")
    cols = [str(c or "").strip() for c in rows[h]]
    out = []
    for r in rows[h + 1 :]:
        if not r or not r[0]:
            continue
        d = dict(zip(cols, r, strict=False))
        out.append({"name": str(d["Clinic Name"]).strip(), "street": str(d.get("Street") or ""),
                    "zip": z5(d.get("Zip Code")),
                    "yes": [c for c in SERVICE_COLS if str(d.get(c) or "").strip().lower() == "yes"]})  # fmt: skip
    return out


def parse_uc(path: Path) -> list[dict[str, Any]]:
    rows = _rows(path, sheet=1)
    cols = [str(c or "").strip() for c in rows[0]]
    out = []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        d = dict(zip(cols, r, strict=False))
        out.append({"name": str(d["Facility Name"]).strip(), "type": str(d.get("Type") or ""),
                    "street": str(d.get("Street Address") or ""), "zip": z5(d.get("Zip")),
                    "imaging": str(d.get("Imaging") or "").strip().lower() == "yes",
                    "lab": str(d.get("Onsite Lab") or "").strip().lower() == "yes"})  # fmt: skip
    return out


def check(
    paths: Paths, as_of: date, previous: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """-> (dph_check.json, dph_services.yaml). Loud: problems are listed and fail the command."""
    problems: list[str] = []
    report: dict[str, Any] = {"as_of": as_of.isoformat(), "files": {}}
    services: dict[str, list[dict[str, Any]]] = {}
    got = {f.name: current(paths, f.name) for f in FILES}
    for name, g in got.items():
        if g is None:
            problems.append(f"{name}: no copy (run fetch, or put it in raw/manual/dph/)")
        else:
            report["files"][name] = {
                k: g[1].get(k)
                for k in ("method", "filename", "sha256", "fetched_at", "landing_url", "final_url")
            }
    if got["facilities"]:
        fac, file_date = parse_facilities(got["facilities"][0])
        scope = [r for r in fac if in_scope(r["zip"])]
        counts = Counter(r["type"] for r in scope)
        report["facilities"] = {"rows": len(fac), "file_date": file_date and file_date.isoformat(),
                                "in_scope": len(scope), "in_scope_by_type": dict(counts.most_common())}  # fmt: skip
        ids = {r["id"] for r in fac}
        for aid, what in ANCHOR_IDS.items():
            if aid not in ids:
                problems.append(f"anchor DPH {aid} ({what}) missing from the facility list")
        base = (previous or {}).get("facilities", {}).get("in_scope_by_type") or BASELINE_IN_SCOPE
        for t, n0 in base.items():
            if t in BASELINE_IN_SCOPE and n0 and abs(counts.get(t, 0) - n0) > MAX_COUNT_CHANGE * n0:
                problems.append(
                    f"{t}: {counts.get(t, 0)} in scope vs {n0} last time (> 15% change)"
                )
        if previous and previous.get("facility_ids"):
            prev_ids = set(previous["facility_ids"])
            cur_ids = {r["id"] for r in scope}
            report["diff"] = {"new": sorted(cur_ids - prev_ids), "gone": sorted(prev_ids - cur_ids)}
        report["facility_ids"] = sorted(r["id"] for r in scope)
    if got["clinic_services"]:
        cs = parse_clinic_services(got["clinic_services"][0])
        report["clinic_services"] = {
            "rows": len(cs),
            "in_scope": sum(in_scope(r["zip"]) for r in cs),
        }
        for r in cs:
            k = akey(r["street"], r["zip"])
            if not k or not in_scope(r["zip"]):
                continue
            for col in r["yes"]:
                svc = SERVICE_COLS[col]
                if svc:
                    services.setdefault(k, []).append({"service": svc, "evidence": "dph_license",
                        "source": f"DPH licensed clinics list ({report['files']['clinic_services']['filename']}): {r['name']} '{col}' = Yes",
                        "checked_at": as_of.isoformat()})  # fmt: skip
    if got["uc_retail"]:
        uc = parse_uc(got["uc_retail"][0])
        report["uc_retail"] = {"rows": len(uc), "in_scope": sum(in_scope(r["zip"]) for r in uc)}
        for r in uc:
            k = akey(r["street"], r["zip"])
            if not k or not in_scope(r["zip"]):
                continue
            for flag, svc in (("imaging", "imaging"), ("lab", "lab")):
                if r[flag]:
                    services.setdefault(k, []).append({"service": svc, "evidence": "dph_license",
                        "source": f"DPH/HPC urgent care and retail clinics data (2024-07, self-reported): {r['name']} {flag} = Yes",
                        "checked_at": as_of.isoformat()})  # fmt: skip
    report["problems"] = problems
    return report, {"version": 1, "by_site_key": dict(sorted(services.items()))}


def cmd_check(a: argparse.Namespace, paths: Paths) -> int:
    prev_p = SITES_DIR / "dph_check.json"
    prev = json.loads(prev_p.read_text()) if prev_p.exists() else None
    report, services = check(paths, date.fromisoformat(a.as_of) if a.as_of else date.today(), prev)
    prev_p.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    (SITES_DIR / "dph_services.yaml").write_text(
        "# GENERATED by `python -m app.sites.dph check`: service evidence by census site_key.\n"
        + yaml.safe_dump(services, sort_keys=False, width=110)
    )
    for p in report["problems"]:
        print(f"FAIL   {p}")
    f = report.get("facilities", {})
    print(f"DPH    facilities {f.get('rows')} rows ({f.get('in_scope')} in scope, file date {f.get('file_date')}); "
          f"{len(services['by_site_key'])} site keys with service evidence")  # fmt: skip
    return 1 if report["problems"] else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.sites.dph")
    p.add_argument("--data-dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--headless", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--as-of", default=None)
    a = p.parse_args(argv)
    paths = Paths.resolve(a.data_dir)
    return {"fetch": cmd_fetch, "check": cmd_check}[a.cmd](a, paths)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
