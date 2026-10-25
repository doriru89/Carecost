"""C4b item 3a: which codes have a separate doctor's (professional) fee, from CMS itself.

The CMS Physician Fee Schedule relative value file (``PPRRVU<year>_<release>_nonQPP.csv`` in the
RVU zip) has a ``PCTC IND`` column per code. The engine reads the global row's value (no modifier):

* ``0`` physician service; ``2`` professional only; ``5`` incident-to; ``6`` / ``8`` physician
  interpretation: a doctor's fee, billed as the code itself;
* ``1`` diagnostic test with a professional / technical split (imaging, surgical pathology): at a
  hospital the doctor's part is the reading, modifier 26;
* ``3`` technical component only; ``4`` global test only; ``7`` physical therapy;
  ``9`` concept does not apply (clinical lab codes, PFS status X): **no separate professional
  fee**. At a hospital such a code is the facility's line only; no "doctor's fee not published"
  line is invented for it.

    uv run --frozen python -m app.quote.pctc --rvu-zip <RVU26D zip>

writes ``data/quote/pctc.yaml`` for every code a quote can price. The engine reads that file;
a code not in it keeps the engine's older rule (registry ``pc_tc_codes``).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path

import yaml

from app.quote.store import REPO_ROOT

PCTC_FILE = REPO_ROOT / "data" / "quote" / "pctc.yaml"
NO_PROFESSIONAL_FEE = frozenset({"3", "4", "7", "9"})
"""PC/TC indicators with no separate doctor's fee on top of the facility's line."""
READING = frozenset({"1"})


def read_rvu(zpath: Path) -> tuple[dict[str, str], str]:
    """-> ({code: PCTC IND of the global row}, member name)."""
    with zipfile.ZipFile(zpath) as z:
        member = next(n for n in sorted(z.namelist())
                      if re.match(r"PPRRVU\d{4}.*nonQPP\.csv$", n, re.I))  # fmt: skip
        text = z.read(member).decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    head = next(i for i, r in enumerate(rows) if r[:2] == ["HCPCS", "MOD"])
    # the header spans several lines: "PCTC" on the line above "IND"
    col = next(i for i, v in enumerate(rows[head]) if v == "IND" and rows[head - 1][i] == "PCTC")
    out: dict[str, str] = {}
    for r in rows[head + 1 :]:
        if len(r) > col and r[0] and not r[1]:
            out.setdefault(r[0].strip(), r[col].strip())
    return out, member


def load_pctc(path: Path = PCTC_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return {str(k).zfill(5) if isinstance(k, int) else str(k): str(v)
            for k, v in (doc.get("codes") or {}).items()}  # fmt: skip


def main() -> None:  # pragma: no cover - run by hand on the RVU zip
    from app.quote.pack import priced_codes

    ap = argparse.ArgumentParser()
    ap.add_argument("--rvu-zip", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=PCTC_FILE)
    a = ap.parse_args()
    ind, member = read_rvu(a.rvu_zip)
    codes = sorted(c for c in priced_codes() if c in ind)
    doc = {
        "version": 1,
        "note": "CMS PFS PC/TC indicator per code (global row). Written by python -m "
        "app.quote.pctc; do not edit by hand.",
        "source": {
            "file": a.rvu_zip.name,
            "member": member,
            "sha256": hashlib.sha256(a.rvu_zip.read_bytes()).hexdigest(),
            "column": "PCTC IND",
        },
        "codes": {c: ind[c] for c in codes},
    }
    a.out.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"{a.out}: {len(codes)} codes")


if __name__ == "__main__":  # pragma: no cover
    main()
