"""Write contracts/fixtures/rate_row_extract.csv from an ETL build (the build is gitignored).

    cd backend && uv run python -m tests.contracts.make_rate_row_extract <build>/rate_row.sqlite

The extract holds every hospital-MRF row a quote fixture cites, plus every row of the searched
file for the codes of each 'not published' / 'percent only' line, so
test_fixture_numbers_match_the_build can re-run the lookup without the build.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "contracts" / "fixtures"
OUT = FIX / "rate_row_extract.csv"
QUOTES = ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder")
COLUMNS = [
    "row_ref",
    "source_id",
    "code",
    "modifiers",
    "payer_id",
    "product",
    "line_of_business",
    "row_kind",
    "amount",
    "negotiated_pct",
    "discounted_cash",
    "gross",
    "excluded",
]


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def wanted(docs: list[dict]) -> tuple[set[str], set[tuple[str, str]]]:
    refs: set[str] = set()
    searched: set[tuple[str, str]] = set()
    for doc in docs:
        for node in _walk(doc):
            prov = node.get("prov")
            if isinstance(prov, dict) and prov.get("source_kind") == "hospital_mrf":
                refs.add(prov["row_ref"])
            if "codes" in node and isinstance(node.get("cell"), dict):
                s = node["cell"].get("searched")
                if s and s["source_id"].endswith("_mrf"):
                    searched |= {(s["source_id"], c) for c in node["codes"]}
    return refs, searched


def main(db_path: str) -> None:
    docs = [json.loads((FIX / f"{n}.json").read_text()) for n in QUOTES]
    refs, searched = wanted(docs)
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cols = ", ".join(COLUMNS)
    rows = {}
    for ref in refs:
        r = db.execute(f"select {cols} from rate_row where row_ref = ?", (ref,)).fetchone()
        if r is None:
            raise SystemExit(f"{ref} is not in {db_path}")
        rows[ref] = dict(r)
    for sid, code in searched:
        for r in db.execute(
            f"select {cols} from rate_row where source_id = ? and code = ?", (sid, code)
        ):
            rows[r["row_ref"]] = dict(r)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, COLUMNS, lineterminator="\n")
        w.writeheader()
        for ref in sorted(rows):
            w.writerow(rows[ref])
    print(f"{OUT.relative_to(REPO)}: {len(rows)} rows")


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1])
