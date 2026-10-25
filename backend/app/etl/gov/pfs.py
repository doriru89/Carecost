"""Medicare Physician Fee Schedule (PFS) and anesthesia, Massachusetts localities.

Input: the CMS ``RVUxxY`` zip (``PPRRVU<year>_<Mon>_nonQPP.csv``, ``GPCI<year>.csv``,
``ANES<year>.csv``) and, for anesthesia, the CMS anesthesia base-unit file.

Price of one code in one locality (CMS PFS formula, non-QP conversion factor)::

    non-facility = (work RVU x PW GPCI + non-facility PE RVU x PE GPCI + MP RVU x MP GPCI) x CF
    facility     = (work RVU x PW GPCI +     facility PE RVU x PE GPCI + MP RVU x MP GPCI) x CF

rounded to the cent. A setting whose "NA indicator" is ``NA`` is not priced there (e.g. the global
X-ray in a hospital: the hospital bills the technical part, the radiologist bills -26).
Only status codes A / R / T are paid on the PFS; every other status is counted, not priced.

Anesthesia: ``base units x locality anesthesia CF`` (``plan_raw = anesthesia_base``). The time
part, one unit per 15 minutes x the same CF, depends on the case and is NOT in the amount; the
formula in ``negotiated_algorithm`` says so.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from app.etl.contracts import SourceKind
from app.etl.gov.common import GovReadError, ReadResult, make_row

MA_LOCALITIES = {"01": "medicare_ma_01", "99": "medicare_ma_99"}
MA_CARRIER = "14212"  # NGS, Massachusetts
PAID_STATUS = {"A", "R", "T"}

# PPRRVU column positions (the header has duplicate names, so positions are the contract).
C_HCPCS, C_MOD, C_DESC, C_STATUS = 0, 1, 2, 3
C_WORK, C_PE_NF, C_NA_NF, C_PE_F, C_NA_F, C_MP = 5, 6, 7, 8, 9, 10
C_CF = 25
EXPECTED_HEADER = ["HCPCS", "MOD", "DESCRIPTION", "CODE", "PAYMENT", "RVU", "PE RVU"]


def _member(zf: zipfile.ZipFile, pattern: str) -> str:
    names = [n for n in zf.namelist() if re.fullmatch(pattern, Path(n).name, re.I)]
    if len(names) != 1:
        raise GovReadError(f"expected one file matching {pattern!r}, found {names}")
    return names[0]


def _csv_rows(zf: zipfile.ZipFile, name: str) -> list[list[str]]:
    text = zf.read(name).decode("latin-1")
    return list(csv.reader(io.StringIO(text)))


def _f(s: str) -> float:
    s = (s or "").strip()
    return float(s) if s else 0.0


def read_gpci(zf: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    """MA locality -> {pw, pe, mp, name, line}."""
    rows = _csv_rows(zf, _member(zf, r"GPCI\d{4}\.csv"))
    out: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(rows, start=1):
        if len(r) >= 7 and r[0].strip() == MA_CARRIER and r[1].strip() == "MA":
            loc = r[2].strip()
            if loc in MA_LOCALITIES:
                out[loc] = {
                    "name": r[3].strip(),
                    "pw": float(r[4]),
                    "pe": float(r[5]),
                    "mp": float(r[6]),
                    "line": i,
                }
    if set(out) != set(MA_LOCALITIES):
        raise GovReadError(
            f"GPCI file: MA localities {sorted(out)}, expected {sorted(MA_LOCALITIES)}"
        )
    return out


def read_anes_cf(zf: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    """MA locality -> {cf (non-QP), line}. Header names the non-QP national CF."""
    rows = _csv_rows(zf, _member(zf, r"ANES\d{4}\.csv"))
    head = [c.lower() for c in rows[0]]
    nonqp = [i for i, c in enumerate(head) if "non-qualifying" in c]
    if len(nonqp) != 1:
        raise GovReadError(f"ANES file: no single non-qualifying CF column in {rows[0]}")
    j = nonqp[0]
    out: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(rows[1:], start=2):
        if len(r) > j and r[0].strip() == MA_CARRIER and r[1].strip() in MA_LOCALITIES:
            out[r[1].strip()] = {"cf": float(r[j]), "line": i, "name": r[2].strip()}
    if set(out) != set(MA_LOCALITIES):
        raise GovReadError(f"ANES file: MA localities {sorted(out)}")
    return out


def pfs_price(rvu: dict[str, float], g: dict[str, Any], cf: float, facility: bool) -> float:
    pe = rvu["pe_f"] if facility else rvu["pe_nf"]
    return round((rvu["work"] * g["pw"] + pe * g["pe"] + rvu["mp"] * g["mp"]) * cf, 2)


def read_pfs(path: Path, *, source_id: str, sha: str, effective: date) -> ReadResult:
    with zipfile.ZipFile(path) as zf:
        rvu_name = _member(zf, r"PPRRVU\d{4}_[A-Za-z]+_nonQPP\.csv")
        rows = _csv_rows(zf, rvu_name)
        gpci = read_gpci(zf)
    title = " ".join(c for r in rows[:6] for c in r if c)
    m = re.search(r"RELEASED (\d{2})/(\d{2})/(\d{4})", title)
    if not m:
        raise GovReadError(f"{rvu_name}: no 'RELEASED mm/dd/yyyy' line in the header")
    released = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    hdr = next((i for i, r in enumerate(rows) if r[:2] == ["HCPCS", "MOD"]), None)
    if hdr is None or rows[hdr][: len(EXPECTED_HEADER)] != EXPECTED_HEADER:
        raise GovReadError(f"{rvu_name}: column header not found / changed")
    counts: dict[str, int] = {"lines": 0, "priced_codes": 0, "rows": 0}
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows[hdr + 1 :], start=hdr + 2):
        if len(r) <= C_CF or not r[C_HCPCS].strip():
            continue
        counts["lines"] += 1
        status = r[C_STATUS].strip()
        if status not in PAID_STATUS:
            counts[f"status_{status or 'blank'}_not_priced"] = (
                counts.get(f"status_{status or 'blank'}_not_priced", 0) + 1
            )
            continue
        rvu = {
            "work": _f(r[C_WORK]),
            "pe_nf": _f(r[C_PE_NF]),
            "pe_f": _f(r[C_PE_F]),
            "mp": _f(r[C_MP]),
        }
        cf = float(r[C_CF])
        code, mod = r[C_HCPCS].strip(), r[C_MOD].strip()
        desc = r[C_DESC].strip()
        priced = False
        for facility, na_col, variant in (
            (False, C_NA_NF, "non_facility"),
            (True, C_NA_F, "facility"),
        ):
            if r[na_col].strip().upper() == "NA":
                counts[f"{variant}_na"] = counts.get(f"{variant}_na", 0) + 1
                continue
            pe = rvu["pe_f"] if facility else rvu["pe_nf"]
            if rvu["work"] + pe + rvu["mp"] <= 0:
                continue
            for loc, entity in MA_LOCALITIES.items():
                g = gpci[loc]
                amt = pfs_price(rvu, g, cf, facility)
                algo = (
                    f"({rvu['work']:.2f}*{g['pw']:.3f} + {pe:.2f}*{g['pe']:.3f} + "
                    f"{rvu['mp']:.2f}*{g['mp']:.3f}) * {cf:.4f}"
                    f" [work RVU*PW GPCI + {'facility' if facility else 'non-facility'} PE RVU*PE GPCI"
                    f" + MP RVU*MP GPCI] * non-QP CF; GPCI {g['name']} (GPCI file line {g['line']})"
                )
                out.append(
                    make_row(
                        source_id=source_id,
                        kind=SourceKind.medicare_pfs,
                        sha=sha,
                        source_file=path.name,
                        source_date=effective,
                        entity_id=entity,
                        payer_id="MEDICARE",
                        payer_raw="Medicare Physician Fee Schedule",
                        line=i,
                        variant=variant,
                        code=code,
                        modifiers=mod,
                        description=desc,
                        amount=amt,
                        algorithm=algo,
                        notes=f"status {status}; {rvu_name} released {released.isoformat()}",
                    )
                    | {"row_ref": f"{source_id}:{sha[:12]}:{i}:{variant}:{loc}"}
                )
                counts["rows"] += 1
                priced = True
        counts["priced_codes"] += int(priced)
    return ReadResult(
        rows=out,
        effective_date=effective,
        counts=counts,
        notes=[f"{rvu_name} released {released.isoformat()}", "conversion factor: non-QP"],
    )


def read_base_units(path: Path) -> dict[str, tuple[int, int]]:
    """CMS anesthesia base-unit zip -> code -> (base units, line). Reads the 508 text file."""
    with zipfile.ZipFile(path) as zf:
        txt = [
            n for n in zf.namelist() if n.lower().endswith(".txt") and "__macosx" not in n.lower()
        ]
        if len(txt) != 1:
            raise GovReadError(f"base units zip: expected one .txt, found {txt}")
        lines = zf.read(txt[0]).decode("latin-1").splitlines()
    out: dict[str, tuple[int, int]] = {}
    for i, ln in enumerate(lines, start=1):
        m = re.fullmatch(r"\s*(0[0-1]\d{3})\s+(\d{1,2})\s*", ln)
        if m:
            out[m.group(1)] = (int(m.group(2)), i)
    if len(out) < 200:
        raise GovReadError(f"base units file: only {len(out)} codes parsed")
    return out


def read_anesthesia(
    base_units_path: Path, rvu_zip: Path, rvu_sha: str, *, source_id: str, sha: str, effective: date
) -> ReadResult:
    units = read_base_units(base_units_path)
    with zipfile.ZipFile(rvu_zip) as zf:
        cfs = read_anes_cf(zf)
    out: list[dict[str, Any]] = []
    for code, (bu, line) in sorted(units.items()):
        for loc, entity in MA_LOCALITIES.items():
            cf = cfs[loc]["cf"]
            out.append(
                make_row(
                    source_id=source_id,
                    kind=SourceKind.medicare_pfs,
                    sha=sha,
                    source_file=base_units_path.name,
                    source_date=effective,
                    entity_id=entity,
                    payer_id="MEDICARE",
                    payer_raw="Medicare anesthesia (PFS)",
                    line=line,
                    variant="anesthesia_base",
                    code=code,
                    modifiers="",
                    description="",
                    amount=round(bu * cf, 2),
                    algorithm=(
                        f"{bu} base units * {cf:.2f} (MA locality {loc} anesthesia CF, non-QP, "
                        f"{rvu_zip.name} sha {rvu_sha[:12]} ANES line {cfs[loc]['line']}); "
                        f"PLUS time units (1 per 15 min) * {cf:.2f}, not included"
                    ),
                    notes="base units only; anesthesia time is billed on top",
                )
                | {"row_ref": f"{source_id}:{sha[:12]}:{line}:anesthesia_base:{loc}"}
            )
    return ReadResult(
        rows=out,
        effective_date=effective,
        counts={"codes": len(units), "rows": len(out)},
        notes=[f"anesthesia CF from {rvu_zip.name}", "amount = base units only (no time)"],
    )
