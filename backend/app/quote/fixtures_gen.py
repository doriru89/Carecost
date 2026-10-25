"""Regenerate the golden quote fixtures from the P1 engine on REAL data, plus the committed extract.

    cd backend
    uv run --frozen --extra etl python -m app.quote.fixtures_gen \\
        --hospital-build /path/to/data/build/20261024-10d8a893 \\
        --tic-root /path/to/data/intermediate/tic --as-of 2026-10-24

Writes
  contracts/fixtures/quote_bcbs_hmo_shoulder.json   engine output for quote_request_bcbs_hmo_shoulder
  contracts/fixtures/quote_cash_shoulder.json       engine output for quote_request_cash_shoulder
  contracts/fixtures/rate_row_extract.csv           every row the two quotes looked at, every row
                                                    the (hand-made) Medicare fixture cites, and every
                                                    row of a file a 'not published' claim searched
  contracts/fixtures/rate_row_extract.sources.yaml  freshness inputs of those sources

then reloads the extract and checks the engine reproduces both fixtures byte for byte, so the
CI end-to-end test (tests/quote/test_p1_slice.py) runs on the same numbers without the 1 GB build.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.quote.contracts import QuoteRequest
from app.quote.engine import Engine
from app.quote.slice_data import (
    EXTRACT_CSV,
    EXTRACT_SOURCES,
    REPO_ROOT,
    Recorder,
    load_from_extract,
    write_extract,
)

FIX = REPO_ROOT / "contracts" / "fixtures"
GENERATED = {"bcbs_hmo": "quote_bcbs_hmo_shoulder", "cash": "quote_cash_shoulder"}
KEPT = ("quote_medicare_shoulder",)  # hand-made until A3 loads Medicare PFS; its rows stay checked
EXTRA_HOSPITAL_SOURCES = ("brigham_mrf",)  # cited by the Medicare fixture


def request(name: str) -> QuoteRequest:
    doc = json.loads((FIX / f"quote_request_{name}_shoulder.json").read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return QuoteRequest.model_validate(doc)


def fixture_text(resp_json: dict[str, Any]) -> str:
    return json.dumps({"_fixture": True, "_schema": "QuoteResponse", **resp_json}, indent=2) + "\n"


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def cited_and_searched(docs: list[dict]) -> tuple[set[str], set[tuple[str, str]]]:
    """Hospital-MRF row refs a fixture cites, and (source, code) of each not-published claim."""
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hospital-build", type=Path, required=True)
    ap.add_argument("--tic-root", type=Path, required=True)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    a = ap.parse_args()

    data = Engine.load_real(a.hospital_build, a.tic_root, EXTRA_HOSPITAL_SOURCES)
    data.recorder = Recorder()
    engine = Engine(data)
    texts = {}
    for req_name, fx in GENERATED.items():
        resp = engine.quote(request(req_name), a.as_of)
        texts[fx] = fixture_text(resp.model_dump(mode="json"))

    docs = [json.loads(t) for t in texts.values()]
    docs += [json.loads((FIX / f"{n}.json").read_text()) for n in KEPT]
    refs, searched = cited_and_searched(docs)
    missing = refs - {r.row_ref for r in data.rows.values()}
    if missing:
        raise SystemExit(f"cited rows not in the build: {sorted(missing)[:5]}")
    keep = set(data.recorder.refs)
    keep |= {r.uid for r in data.rows.values() if r.row_ref in refs}
    keep |= {r.uid for r in data.rows.values() if (r.source_id, r.code) in searched}
    n = write_extract(data, keep, EXTRACT_CSV, EXTRACT_SOURCES)
    for fx, text in texts.items():
        (FIX / f"{fx}.json").write_text(text)

    # the committed extract must reproduce the committed fixtures exactly
    replay = Engine(load_from_extract())
    for req_name, fx in GENERATED.items():
        again = fixture_text(replay.quote(request(req_name), a.as_of).model_dump(mode="json"))
        if again != texts[fx]:
            raise SystemExit(f"{fx}: the extract does not reproduce the build's quote")
    print(f"{EXTRACT_CSV.relative_to(REPO_ROOT)}: {n} rows; fixtures {sorted(texts)} reproduced")


if __name__ == "__main__":  # pragma: no cover
    main()
