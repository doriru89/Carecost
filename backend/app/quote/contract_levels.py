"""Austin 2026-10-25 / O ``contract_level``: which billing groups price consistently far from
their peers (a contract level, not a data error), written from the data once per pack.

    uv run --frozen python -m app.quote.contract_levels --pack <quote_pack.sqlite>

For every payment the engine quotes (each insurer payer x product with a loaded network, plus
self-pay, Medicare and MassHealth) and every site, each billing group's ratio to its peer median
(same code, modifier, component, network and kind of site) on every code it prices there. A group
is kept when its median ratio is >= 1.5x or <= 0.67x over >= 3 codes, so engine.yaml
``outliers.contract_level`` (default: >= 2x / <= 0.5x on >= 5 OTHER codes) can be tightened
without rewriting the table. The engine reads the table at startup (no request prices every code).
"""

from __future__ import annotations

import argparse
import statistics
import time
from datetime import date
from pathlib import Path

import yaml

from app.quote.store import REPO_ROOT

KEEP_HIGH, KEEP_LOW, KEEP_MIN = 1.5, 0.67, 3


def payments(reg, store) -> list[dict]:
    out: list[dict] = [{"kind": "cash"}, {"kind": "medicare"}, {"kind": "masshealth"}]
    for payer in sorted(reg.payer_labels):
        for product in sorted(reg.products):
            nets = [n for n in reg.networks_for(payer, product, None) if n in store.sources]
            if nets:
                out.append({"kind": "insurance", "payer_id": payer, "product": product,
                            "network": None})  # fmt: skip
    return out


def main() -> None:  # pragma: no cover - needs a real pack
    from app.quote.contracts import QuoteRequest
    from app.quote.engine import Engine
    from app.quote.registry import ENGINE_CONFIG, Registry
    from app.quote.store import load_pack

    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, required=True)
    a = ap.parse_args()
    reg = Registry.load()
    cfg = yaml.safe_load(ENGINE_CONFIG.read_text())
    store = load_pack(a.pack, tins=reg.tins, census_ids=reg.census_ids)
    eng = Engine(store, reg)
    groups: dict[str, dict[str, float]] = {}
    t0 = time.perf_counter()
    for pay in payments(reg, store):
        q = eng._context(QuoteRequest.model_validate({
            "payment": pay, "care_path_id": None, "answers": {}, "service_codes": ["99203"],
            "picked_by": "person", "site_ids": None}), date.today())  # fmt: skip
        seen: set[tuple[str, str]] = set()
        for c in sorted(store.codes):
            for sid, per in eng._line_stats(c, q).items():
                for ents in per.values():
                    seen |= {(sid, g) for _, g, _ in ents if not g.startswith(("fs:", "posted:"))}
        for sid, g in sorted(seen):
            site = reg.sites[sid]
            ratios = eng.contract_ratios(site, g, q)
            if len(ratios) < KEEP_MIN:
                continue
            m = statistics.median(ratios.values())
            if m >= KEEP_HIGH or m <= KEEP_LOW:
                groups[eng.contract_key(site, g, q)] = dict(sorted(ratios.items()))
        print(f"{pay}: {len(seen)} groups, {len(groups)} kept so far, "
              f"{time.perf_counter() - t0:.0f} s", flush=True)
    out = REPO_ROOT / cfg["contract_levels_file"]
    doc = {"version": 1,
           "note": f"Written by python -m app.quote.contract_levels from pack "
                   f"{store.version.build_id}; key = site|group|payment kind|payer|product; value "
                   "= the group's ratio to its peer median per code-modifier-component.",
           "groups": dict(sorted(groups.items()))}  # fmt: skip
    out.write_text(yaml.safe_dump(doc, sort_keys=False, width=120))
    print(f"{out}: {len(groups)} groups")


if __name__ == "__main__":  # pragma: no cover
    main()
