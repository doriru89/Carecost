"""MassHealth (EOHHS) physician fee schedules: 101 CMR 316.00 (surgery + anesthesia),
317.00 (medicine), 318.00 (radiology).

The rates are tables inside the regulation itself, published by EOHHS on mass.gov as PDF (and
for some versions DOCX). We read the PDF with poppler's ``pdftotext -layout`` (CI installs
``poppler-utils``) and accept only lines that match the table shape exactly::

    <code>[*]  <NFAC>  <FAC>  <Global>  <PC>  <TC>      each "-", "$12.34" or "I.C."
    <anesthesia code 00100-01999>  <base units>         (316.00 anesthesia table)

A line that starts like a code row but does not match is counted as ``unparsed`` and fails the
read, so a layout change can never silently drop prices. Columns -> rows:

=========  ==================  =========================================
column     ``plan_raw``        ``modifiers``
=========  ==================  =========================================
NFAC       ``non_facility``    ""
FAC        ``facility``        ""
Global     ``global``          ""
PC         ``professional``    ``26``
TC         ``technical``       ``TC``
anesthesia ``anesthesia_base`` ""  (base units x the regulation's per-unit fee; time not included)
=========  ==================  =========================================

The effective date is read from the regulation's own "Applicable Dates of Service" clause.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.etl.contracts import SourceKind
from app.etl.gov.common import GovReadError, ReadResult, make_row, money_str

TOKEN_RE = re.compile(r"(?<!\S)(-|\$[\d,]+(?:\.\d{2})?|I\.?\s?C\.?)(?!\S)")
CODE_ROW = re.compile(
    r"^\s*([0-9]{4}[0-9A-Z]|[A-Z][0-9]{4})(\*?)(?: ([A-Z0-9]{2}))?(?=\s{2,}|\s*$)"
)
HEADER_RE = re.compile(r"^\s*Code\s+(?:Units|NFAC)\b")
COLUMN_NAMES = {"NFAC": ("non_facility", ""), "FAC": ("facility", ""), "Global": ("global", ""),
                "PC": ("professional", "26"), "TC": ("technical", "TC")}  # fmt: skip
FRAG_HEAD = re.compile(r"\$[\d,]+\.?\d*")
FRAG_TAIL = re.compile(r"\d+")
ANES_RE = re.compile(r"^\s*(0[01][0-9]{3})\s+([0-9]{1,2})\s*$")
EFFECTIVE_RE = re.compile(
    r"apply\s+for\s+dates\s+of\s+service\s+on\s+or\s+after\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.S
)
ANES_FEE_RE = re.compile(
    r"\$(\d+\.\d{2})\s+per\s+base\s+anesthesia\s+unit\s+and\s+\$(\d+\.\d{2})\s+per\s+one\s+minute"
)


def pdf_text(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise GovReadError(
            "pdftotext not found: install poppler (brew install poppler / apt poppler-utils)"
        )
    res = subprocess.run(
        [exe, "-layout", str(path), "-"], capture_output=True, check=True, timeout=300
    )
    return res.stdout.decode("utf-8", "replace")


def effective_date(text: str) -> date:
    m = EFFECTIVE_RE.search(re.sub(r"\s+", " ", text))
    if not m:
        raise GovReadError("no 'apply for dates of service on or after <date>' clause")
    return datetime.strptime(m.group(1), "%B %d, %Y").date()


def _only(rx: re.Pattern[str], line: str) -> list[tuple[int, str]] | None:
    """All matches of rx with their x position, if the line holds nothing else."""
    hits = [(m.start(), m.group(0)) for m in rx.finditer(line)]
    rest = rx.sub("", line).strip()
    return hits if hits and not rest else None


@dataclass
class FeeLine:
    line: int
    code: str
    modifier: str
    asterisk: bool
    cells: dict[str, str]  # column name (NFAC ...) -> token
    repaired: bool = False


STAR_LINE = re.compile(r"^\s*\*((?:\s+\d+)*)\s*$")
SECTION_RE = re.compile(
    r"^\s*\(([a-z])\)\s+(Surgical Services|Anesthesia Services|[A-Z][a-z]+ Services)\b(.*)$"
)
MAX_UNPARSED = 5
"""More unparsed code rows than this fails the read; fewer are listed in the manifest (loud)."""
SKIP_SECTIONS = ("Facial Feminization",)
"""316.05(4)(c): rates that apply only when the codes are billed as part of facial feminization
surgery. Counted, not loaded (a consumer price for these codes is the (4)(b) rate)."""


def _cells(line: str, start: int = 0) -> tuple[list[tuple[int, str]], list[tuple[int, str]], str]:
    """-> (whole tokens, wrapped-amount heads like '$1,288.8', anything else left over)."""
    part = line[start:]
    toks = [(start + t.start(), t.group(1)) for t in TOKEN_RE.finditer(part)]
    rest = TOKEN_RE.sub(lambda m: " " * len(m.group(0)), part)
    heads = [
        (start + h.start(), h.group(0)) for h in re.finditer(r"(?<!\S)\$[\d,]+\.?\d?(?!\S)", rest)
    ]
    rest = re.sub(r"(?<!\S)\$[\d,]+\.?\d?(?!\S)", " ", rest).strip()
    return toks, heads, rest


def parse_tables(
    text: str,
) -> tuple[list[FeeLine], list[tuple[int, str, int]], list[str], dict[str, int]]:
    """Position-aware: each table's columns come from its own ``Code NFAC FAC ...`` header line.

    Two pdftotext layouts are repaired by column position, never guessed:
    * a wrapped amount: ``$1,103.7`` on the line above the row and ``2`` on the line below;
    * a stacked asterisk row: the code alone (or with a wrapped head), its amounts on the next
      line(s), then a line holding ``*`` and the wrapped tails.
    Anything else that starts like a code row and does not fill exactly its table's columns is
    returned as unparsed (the read then fails)."""
    lines = text.splitlines()
    fees: list[FeeLine] = []
    anes: list[tuple[int, str, int]] = []
    bad: list[str] = []
    skipped: dict[str, int] = {}
    cols: list[str] | None = None
    section = ""
    i = 0
    while i < len(lines):
        ln, no = lines[i], i + 1
        i += 1
        sec = SECTION_RE.match(ln)
        if sec:
            section = sec.group(2) + sec.group(3)
            continue
        if HEADER_RE.match(ln):
            words = ln.split()
            cols = ["Units"] if words[1] == "Units" else [w for w in words[1:] if w in COLUMN_NAMES]
            continue
        a = ANES_RE.match(ln)
        if a and cols == ["Units"]:
            anes.append((no, a.group(1), int(a.group(2))))
            continue
        m = CODE_ROW.match(ln)
        if not m or cols is None or cols == ["Units"]:
            continue
        toks, heads, rest = _cells(ln, m.end())
        if rest and not toks and not heads:
            continue  # prose that happens to start with a number
        tails: list[tuple[int, str]] = []
        star = bool(m.group(2))
        repaired = False
        if len(toks) + len(heads) < len(cols) or heads:
            # stacked asterisk row: amounts below, then the '*' line with the tails
            j = i
            while j < len(lines) and j < i + 4:
                st = STAR_LINE.match(lines[j])
                if st:
                    tails = [(t.start(), t.group(0)) for t in re.finditer(r"\d+", lines[j])]
                    star, repaired, i = True, True, j + 1
                    break
                t2, h2, r2 = _cells(lines[j])
                if r2 or not (t2 or h2):
                    break
                toks += t2
                heads += h2
                j += 1
            else:
                pass
            if not repaired:
                heads, toks = heads, toks
        if not repaired and len(toks) < len(cols) and not heads and i - 2 >= 0 and i < len(lines):
            above = _only(FRAG_HEAD, lines[i - 2])
            below = _only(FRAG_TAIL, lines[i])
            if above and below and len(above) == len(below):
                heads, tails, repaired = above, below, True
        if heads or tails:
            if len(heads) != len(tails):
                bad.append(f"line {no}: {ln.strip()[:100]} (wrapped amounts do not pair up)")
                continue
            toks += [
                (hx, h + t) for (hx, h), (_tx, t) in zip(sorted(heads), sorted(tails), strict=True)
            ]
        toks.sort()
        if rest or len(toks) != len(cols) or not all(TOKEN_RE.fullmatch(t) for _x, t in toks):
            bad.append(f"line {no}: {ln.strip()[:100]}")
            continue
        if any(k in section for k in SKIP_SECTIONS):
            skipped[section.strip()[:60]] = skipped.get(section.strip()[:60], 0) + 1
            continue
        fees.append(
            FeeLine(
                no,
                m.group(1),
                m.group(3) or "",
                star,
                dict(zip(cols, (t for _x, t in toks), strict=True)),
                repaired,
            )  # fmt: skip
        )
    return fees, anes, bad, skipped


def read_masshealth(
    path: Path, *, source_id: str, sha: str, regulation: str, text: str | None = None
) -> ReadResult:
    text = pdf_text(path) if text is None else text
    eff = effective_date(text)
    fees, anes, bad, skipped = parse_tables(text)
    if len(bad) > MAX_UNPARSED:
        raise GovReadError(f"{path.name}: {len(bad)} table lines did not parse, e.g. {bad[:3]}")
    if not fees:
        raise GovReadError(f"{path.name}: no fee table rows found")
    payer_raw = f"MassHealth {regulation}"
    out: list[dict[str, Any]] = []
    counts: dict[str, int] = {"table_lines": len(fees), "ic_or_dash_cells": 0}
    counts.update({f"skipped: {k}": v for k, v in skipped.items()})
    counts["repaired_wrapped_cells"] = sum(f.repaired for f in fees)
    for f in fees:
        for col, tok in f.cells.items():
            variant, col_mod = COLUMN_NAMES[col]
            amt = money_str(tok)
            if amt is None:
                counts["ic_or_dash_cells"] += 1
                continue
            mods = "|".join(sorted(x for x in (f.modifier, col_mod) if x))
            out.append(
                make_row(
                    source_id=source_id,
                    kind=SourceKind.masshealth_fs,
                    sha=sha,
                    source_file=path.name,
                    source_date=eff,
                    entity_id="masshealth",
                    payer_id="MASSHEALTH",
                    payer_raw=payer_raw,
                    line=f.line,
                    variant=variant,
                    code=f.code,
                    modifiers=mods,
                    description="",
                    amount=amt,
                    lob="medicaid",
                    algorithm=f"{regulation} maximum allowable fee, {col} column",
                    notes="asterisk code: see the regulation's rule for this code"
                    if f.asterisk
                    else "",
                )  # fmt: skip
            )
    if anes:
        m = ANES_FEE_RE.search(re.sub(r"\s+", " ", text))
        if not m:
            raise GovReadError(f"{path.name}: anesthesia table but no per-unit fee clause")
        per_unit, per_min = float(m.group(1)), float(m.group(2))
        counts["anesthesia_codes"] = len(anes)
        for line, code, units in anes:
            out.append(
                make_row(
                    source_id=source_id,
                    kind=SourceKind.masshealth_fs,
                    sha=sha,
                    source_file=path.name,
                    source_date=eff,
                    entity_id="masshealth",
                    payer_id="MASSHEALTH",
                    payer_raw=payer_raw,
                    line=line,
                    variant="anesthesia_base",
                    code=code,
                    modifiers="",
                    description="",
                    amount=round(units * per_unit, 2),
                    lob="medicaid",
                    algorithm=(
                        f"{units} base units * ${per_unit:.2f} per base unit; PLUS "
                        f"${per_min:.2f} per minute of anesthesia time, not included"
                    ),
                    notes="base units only; anesthesia time is billed on top",
                )  # fmt: skip
            )
    counts["rows"] = len(out)
    counts["unparsed_lines"] = len(bad)
    notes = [f"effective {eff}"] + [f"NOT LOADED (layout): {b}" for b in bad]
    return ReadResult(rows=out, effective_date=eff, counts=counts, notes=notes)
