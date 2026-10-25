"""Medicare hospital outpatient (OPPS Addendum B) and ambulatory surgery center (ASC Addenda AA/BB).

Both publish a **national unadjusted** payment rate per HCPCS code each quarter. The amount here
is that rate, exactly as printed (``method stated``). What a Boston facility is actually paid is
the rate wage-adjusted for its CBSA (OPPS: 60% labor share; ASC: 50%); the wage index is not
applied here, and ``negotiated_algorithm`` says so, so no one mistakes it for a local price.

* OPPS: ``plan_raw = opps``; G0463 (hospital outpatient clinic visit) is the facility fee of a
  hospital-based clinic visit (plan P9).
* ASC: ``plan_raw = asc``; AA = covered surgical procedures, BB = covered ancillary services.
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
from app.etl.gov.common import GovReadError, ReadResult, make_row, money_str

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]  # fmt: skip
CODE_RE = re.compile(r"^[0-9A-Z]{4}[0-9A-Z]$")


def _month_in(name: str) -> int | None:
    low = name.lower()
    for i, m in enumerate(MONTHS, start=1):
        if m in low or re.search(rf"(^|[^a-z]){m[:3]}([^a-z]|$)", low):
            return i
    return None


def _check_quarter(name: str, effective: date) -> None:
    m = _month_in(name)
    if m != effective.month:
        raise GovReadError(f"{name}: names month {m}, but the source says effective {effective}")


def read_opps(path: Path, *, source_id: str, sha: str, effective: date) -> ReadResult:
    with zipfile.ZipFile(path) as zf:
        txt = [n for n in zf.namelist() if n.lower().endswith(".txt") and "addendum_b" in n.lower()]
        if len(txt) != 1:
            raise GovReadError(f"OPPS zip: expected one Addendum B .txt, found {zf.namelist()}")
        name = txt[0]
        lines = zf.read(name).decode("cp1252", "replace").splitlines()
    _check_quarter(Path(name).name, effective)
    hdr = next((i for i, ln in enumerate(lines) if ln.startswith("HCPCS Code\t")), None)
    if hdr is None:
        raise GovReadError(f"{name}: no 'HCPCS Code' header row")
    cols = [c.strip() for c in lines[hdr].split("\t")]
    want = ["HCPCS Code", "Short Descriptor", "SI", "APC", "Relative Weight", "Payment Rate",
            "National Unadjusted Copayment"]  # fmt: skip
    if cols[: len(want)] != want:
        raise GovReadError(f"{name}: header changed: {cols[:8]}")
    out: list[dict[str, Any]] = []
    counts = {"lines": 0, "rows": 0, "no_payment_rate": 0}
    for i, ln in enumerate(lines[hdr + 1 :], start=hdr + 2):
        f = next(csv.reader(io.StringIO(ln), delimiter="\t"), [])
        if not f or not CODE_RE.match(f[0].strip()):
            continue
        counts["lines"] += 1
        f = f + [""] * 8
        rate = money_str(f[5])
        if rate is None:
            counts["no_payment_rate"] += 1
            continue
        code, si, apc, rw = f[0].strip(), f[2].strip(), f[3].strip(), f[4].strip()
        out.append(
            make_row(
                source_id=source_id,
                kind=SourceKind.medicare_opps,
                sha=sha,
                source_file=path.name,
                source_date=effective,
                entity_id="medicare_national",
                payer_id="MEDICARE",
                payer_raw="Medicare OPPS (national unadjusted)",
                line=i,
                variant="opps",
                code=code,
                modifiers="",
                description=f[1].strip(),
                amount=rate,
                algorithm=(
                    f"APC {apc} (SI {si}, relative weight {rw}) national unadjusted rate; a Boston "
                    "hospital is paid rate * (0.6 * its wage index + 0.4), wage index not applied"
                ),
                notes=f"SI {si}; national unadjusted copayment {f[6].strip() or '-'}",
            )
        )
        counts["rows"] += 1
    return ReadResult(rows=out, effective_date=effective, counts=counts, notes=[Path(name).name])


def _asc_table(zf: zipfile.ZipFile, letters: str) -> tuple[str, list[list[str]]]:
    names = [n for n in zf.namelist() if re.search(rf"ASC-{letters}\.csv$", n, re.I)]
    if len(names) != 1:
        raise GovReadError(f"ASC zip: expected one Addendum {letters} csv, found {names}")
    text = zf.read(names[0]).decode("utf-8-sig", "replace")
    return names[0], list(csv.reader(io.StringIO(text)))


def read_asc(path: Path, *, source_id: str, sha: str, effective: date) -> ReadResult:
    out: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    notes = []
    with zipfile.ZipFile(path) as zf:
        for letters in ("AA", "BB"):
            name, rows = _asc_table(zf, letters)
            _check_quarter(Path(name).name, effective)
            notes.append(Path(name).name)
            hdr = next((i for i, r in enumerate(rows) if r and r[0].strip() == "HCPCS Code"), None)
            if hdr is None:
                raise GovReadError(f"{name}: no header row")
            h = [c.strip() for c in rows[hdr]]
            try:
                j_rate = next(j for j, c in enumerate(h) if c.endswith("Payment Rate"))
                j_pi = next(j for j, c in enumerate(h) if c.endswith("Payment Indicator"))
            except StopIteration as e:
                raise GovReadError(f"{name}: header changed: {h}") from e
            n_lines = n_rows = 0
            for i, r in enumerate(rows[hdr + 1 :], start=hdr + 2):
                if not r or not CODE_RE.match(r[0].strip()):
                    continue
                n_lines += 1
                rate = money_str(r[j_rate]) if len(r) > j_rate else None
                if rate is None:
                    continue
                pi = r[j_pi].strip()
                out.append(
                    make_row(
                        source_id=source_id,
                        kind=SourceKind.medicare_asc,
                        sha=sha,
                        source_file=path.name,
                        source_date=effective,
                        entity_id="medicare_national",
                        payer_id="MEDICARE",
                        payer_raw="Medicare ASC (national unadjusted)",
                        line=i,
                        variant="asc",
                        code=r[0].strip(),
                        modifiers="",
                        description=r[2].strip(),
                        amount=rate,
                        algorithm=(
                            f"Addendum {letters}, payment indicator {pi}; national unadjusted rate; "
                            "an ASC is paid rate * (0.5 * its wage index + 0.5), wage index not applied"
                        ),
                        notes=f"Addendum {letters}; PI {pi}",
                    )
                    | {"row_ref": f"{source_id}:{sha[:12]}:{letters}{i}:asc"}
                )
                n_rows += 1
            counts[f"{letters}_lines"] = n_lines
            counts[f"{letters}_rows"] = n_rows
    counts["rows"] = len(out)
    return ReadResult(rows=out, effective_date=effective, counts=counts, notes=notes)
