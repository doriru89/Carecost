"""Golden fixture 10 (TiC) -- contract for phase A2, which builds the TiC pipeline.

The slice is real BCBS MA rows (see MANIFEST.yaml). A2's parser must keep every case below
as its own row: modifier splits, percentage prices (dollar_basis=pct) and the BIDMC match via
the *file* NPI 1548202641 (the old registry NPI 1598922205 matched nothing).
"""

from __future__ import annotations

import json
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mrf" / "bcbs_tic_73030_bidmc.json"
DOC = json.loads(FIX.read_text())


def test_fixture_has_bidmc_by_file_npi():
    groups = [g for pr in DOC["provider_references"] for g in pr["provider_groups"]]
    assert any(1548202641 in (g.get("npi") or []) for g in groups)
    assert not any(1598922205 in (g.get("npi") or []) for g in groups)


def test_fixture_has_modifier_split_and_percentage_price():
    item = next(i for i in DOC["in_network"] if i["billing_code"] == "73030")
    prices = [p for r in item["negotiated_rates"] for p in r["negotiated_prices"]]
    mods = {tuple(p.get("billing_code_modifier") or ()) for p in prices}
    assert () in mods and ("52",) in mods  # BIDMC is facility-only here: the split is 52, not 26/TC
    pct = [p for i in DOC["in_network"] for r in i["negotiated_rates"] for p in r["negotiated_prices"]
           if p["negotiated_type"] == "percentage"]  # fmt: skip
    assert pct
