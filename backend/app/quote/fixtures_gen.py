"""Regenerate the golden quote fixtures from the engine on REAL data, plus the committed extract.

    cd backend
    # 1. a real pack (hospital build + TiC + A3's government fee schedules)
    uv run --frozen --extra etl python -m app.quote.pack \\
        --hospital-build /path/to/data/build/20261024-336340ed \\
        --tic-root /path/to/data/intermediate/tic \\
        --gov-root /path/to/data/intermediate/gov --out /tmp/quote_pack.sqlite
    # 2. fixtures + extract from it (registry: data/sites/sites.yaml)
    uv run --frozen python -m app.quote.fixtures_gen --pack /tmp/quote_pack.sqlite --as-of 2026-10-25

Writes
  contracts/fixtures/quote_<name>.json             engine output for each quote_request_<name>.json
  contracts/fixtures/rate_row_extract.csv           every row any of the recorded quotes looked at
                                                    (golden requests + every care path x the
                                                    payments in RECORDED, on the fixture sites),
                                                    and every row of a hospital file a 'not
                                                    published' claim searched
  contracts/fixtures/rate_row_extract.sources.yaml  freshness inputs of those sources

then rebuilds a pack from the extract and checks the engine reproduces every golden fixture byte for
byte, so CI (tests/quote) runs on the same numbers without the 1 GB of data.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.quote.contracts import QuoteRequest
from app.quote.engine import Engine
from app.quote.registry import Registry
from app.quote.store import (
    EXTRACT_CSV,
    EXTRACT_SOURCES,
    REPO_ROOT,
    Recorder,
    load_pack,
    store_from_extract,
    write_extract,
)

FIX = REPO_ROOT / "contracts" / "fixtures"
GOLDEN = {
    "bcbs_hmo_shoulder": "quote_bcbs_hmo_shoulder",
    "cash_shoulder": "quote_cash_shoulder",
    "medicare_shoulder": "quote_medicare_shoulder",
    "masshealth_manual": "quote_masshealth_manual",
}
RECORDED: list[dict[str, Any]] = [
    {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None},
    {"kind": "insurance", "payer_id": "BCBS_MA", "product": "PPO", "network": None},
    {"kind": "cash"},
    {"kind": "medicare"},
    {"kind": "masshealth"},
]
NEAR = {"lat": 42.3736, "lon": -71.119}
"""Harvard Square, Cambridge: the point the golden and recorded requests quote from (the 12
closest sites; a no-point request prices every site, which the extract cannot hold)."""
"""Payments recorded for every care path, so the end-to-end and property tests in CI run on real
rows for all ten paths (and BCBS PPO shows a second network family)."""


def request(name: str) -> QuoteRequest:
    doc = json.loads((FIX / f"quote_request_{name}.json").read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return QuoteRequest.model_validate(doc)


def fixture_text(resp_json: dict[str, Any]) -> str:
    return json.dumps({"_fixture": True, "_schema": "QuoteResponse", **resp_json}, indent=2) + "\n"


KEY_SITES = [
    "afc_watertown", "bilh_urgent_care_watertown", "brigham_and_womens_hospital",
    "franciscan_childrens", "mount_auburn_hospital", "tufts_medical_center",
]  # fmt: skip
"""The six P1 sites (contracts/fixtures/sites.json), recorded by name for every path and payment,
so tests/quote can check named numbers (Tufts, Mount Auburn ...) on the extract."""


def recorded_requests(reg: Registry) -> list[QuoteRequest]:
    out = []
    for pid in sorted(reg.paths):
        for pay in RECORDED:
            for answers in ({}, {"Q14": ["hmo_referral_required"]}):
                for where in ({"site_ids": None, "near": NEAR}, {"site_ids": KEY_SITES}):
                    out.append(QuoteRequest.model_validate({
                        "payment": pay, "care_path_id": pid, "answers": answers,
                        "service_codes": [], "picked_by": "person", **where,
                    }))  # fmt: skip
    for pay in RECORDED:  # manual picks at the key sites (the MassHealth golden's codes)
        out.append(QuoteRequest.model_validate({
            "payment": pay, "care_path_id": None, "answers": {},
            "service_codes": ["73030", "73221"], "picked_by": "person", "site_ids": KEY_SITES,
        }))  # fmt: skip
    return out


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def searched_files(docs: list[dict]) -> set[tuple[str, str]]:
    """(hospital source, code) of each not-published claim, so a test can re-run the lookup."""
    out: set[tuple[str, str]] = set()
    for doc in docs:
        for node in _walk(doc):
            if "codes" in node and isinstance(node.get("cell"), dict):
                s = node["cell"].get("searched")
                if s and s["source_id"].endswith("_mrf"):
                    out |= {(s["source_id"], c) for c in node["codes"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    a = ap.parse_args()

    reg = Registry.load()
    store = load_pack(a.pack, tins=reg.tins, census_ids=reg.census_ids)
    store.recorder = Recorder()
    engine = Engine(store, reg)
    texts = {fx: fixture_text(engine.quote(request(n), a.as_of).model_dump(mode="json"))
             for n, fx in GOLDEN.items()}  # fmt: skip
    docs = [json.loads(t) for t in texts.values()]
    for req in recorded_requests(reg):
        docs.append(engine.quote(req, a.as_of).model_dump(mode="json"))
    keep = set(store.recorder.refs)
    searched = searched_files(docs)
    keep |= {r.uid for r in store.rows if (r.source_id, r.code) in searched}
    n = write_extract(store, keep, EXTRACT_CSV, EXTRACT_SOURCES)
    for fx, text in texts.items():
        (FIX / f"{fx}.json").write_text(text)

    # the committed extract must reproduce the committed fixtures exactly
    replay = Engine(store_from_extract(), reg)
    for name, fx in GOLDEN.items():
        again = fixture_text(replay.quote(request(name), a.as_of).model_dump(mode="json"))
        if again != texts[fx]:
            raise SystemExit(f"{fx}: the extract does not reproduce the pack's quote")
    size = EXTRACT_CSV.stat().st_size / 1e6
    print(f"{EXTRACT_CSV.relative_to(REPO_ROOT)}: {n} rows ({size:.2f} MB); "
          f"fixtures {sorted(texts)} reproduced")  # fmt: skip


if __name__ == "__main__":  # pragma: no cover
    main()
