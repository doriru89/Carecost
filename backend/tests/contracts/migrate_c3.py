"""C3 shape for a hand-made quote fixture (tests/contracts/handmade): the step summaries, headline
and totals fields the engine now emits, derived from the receipt lines the same way the engine
derives them (own prices only; no peers in a hand-made fixture). Used once to migrate the files
and by tests that build a quote by hand."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

KINDS = {
    "urgent_care": "urgent_care", "ortho_walk_in": "urgent_care", "specialist_office": "office",
    "primary_care_office": "office", "imaging_center": "office",
    "hospital_outpatient": "hospital_outpatient",
    "ambulatory_surgery_center": "ambulatory_surgery_center",
}  # fmt: skip


def _counts(ln: dict) -> bool:
    c, fee, un = ln["cell"], ln.get("doctor_fee"), ln.get("unusual")
    return bool(c) and c["kind"] == "money" and not (un and un["whole_line"]) and not (
        fee and (fee["rung"] or 0) >= 7)  # fmt: skip


def derive_site(sq: dict) -> None:
    """Fill steps / headline / totals extras of one site quote from its lines."""
    lines = sq["receipt"]["lines"] if sq.get("receipt") else []
    for ln in lines:
        ln.setdefault("estimate", None)
        ln.setdefault("unusual", None)
        ln.setdefault("anesthesia_time", None)
        ln.setdefault("chain_price_from", None)
        if "availability_reason" not in ln:
            ln["availability_reason"] = {
                "offered": None,
                "unknown": "no_evidence",
                "not_offered": "site_says_not_offered",
            }[ln["availability"]]
        if ln.get("doctor_fee"):
            ln["doctor_fee"].pop("multiple", None)
    groups: dict[str, list[dict]] = {}
    for ln in lines:
        groups.setdefault(ln["step_id"] or ",".join(ln["codes"]), []).append(ln)
    steps = []
    for key, lns in groups.items():
        first = lns[0]
        ai = all(ln["ai_suggested"] for ln in lns)
        avail = "offered" if first.get("at", "this_site") != "this_site" else first["availability"]
        priced = [ln for ln in lns if ln["unit"] == "once" and (ai or not ln["ai_suggested"])]
        expected = first["likelihood"] in ("certain", "likely") and not ai
        figure, low, high, rank = "none", None, None, None
        if avail == "offered" and priced and all(_counts(ln) for ln in priced):
            figure = "estimate" if any(ln["estimate"] for ln in priced) else "own"
            low = round(sum(ln["cell"]["low"] for ln in priced), 2)
            high = round(sum(ln["cell"]["high"] for ln in priced), 2)
            rank = round(sum((ln["cell"]["low"] + ln["cell"]["high"]) / 2 for ln in priced), 2)
        steps.append({
            "key": key, "step_id": first["step_id"], "likelihood": first["likelihood"],
            "availability": avail, "figure": figure, "low": low, "high": high,
            "rank_value": rank if expected and figure != "none" else None,
            "estimated": any(ln["estimate"] for ln in lns),
            "unusual": any(ln["unusual"] for ln in lns),
            "in_total": bool(priced) and all(ln["in_total"] for ln in priced),
            "missing": expected and figure == "none",
            "line_ids": [ln["line_id"] for ln in lns], "elsewhere": None, "_exp": expected,
        })  # fmt: skip
    ranked = [st["rank_value"] for st in steps if st["_exp"] and st["rank_value"] is not None]
    for st in steps:
        st.pop("_exp")
    sq["steps"] = steps
    sq.setdefault("distance_km", None)
    sq["site"].setdefault("kind", KINDS[sq["site"]["site_type"]])
    sq["site"].setdefault("chain_id", None)
    if sq.get("receipt"):
        t = sq["receipt"]["totals"]
        t["missing"] = sum(1 for st in steps if st["missing"])
        t["comparable"] = round(sum(ranked), 2) if ranked else None
        t["real_steps"] = sum(1 for st in steps if st["figure"] == "own" and st["rank_value"]
                              is not None)  # fmt: skip
        t.setdefault("might_add", None)
        sq["headline"] = {
            "likely_low": t["likely"]["low"] if t["likely"] else None,
            "likely_high": t["likely"]["high"] if t["likely"] else None,
            "includes_estimate": bool(t["likely"] and t["likely"]["includes_estimate"]),
            "complete": t["complete"], "missing": t["missing"], "comparable": t["comparable"],
            "real_steps": t["real_steps"], "might_add": t["might_add"],
        }  # fmt: skip


def rank_sort(doc: dict) -> None:
    doc["sites"].sort(key=lambda sq: (
        sq["headline"]["missing"],
        sq["headline"]["comparable"] if sq["headline"]["comparable"] is not None else math.inf,
    ))  # fmt: skip


def migrate(doc: dict) -> dict:
    doc.setdefault("payment_label", {"en": "test", "zh": "test"})
    for sq in doc["sites"]:
        derive_site(sq)
    doc.setdefault("ordering", "rank")
    doc.setdefault("origin", None)
    doc.setdefault("chain_spreads", [])
    # site order kept: the tests index sites by position
    return doc


if __name__ == "__main__":  # pragma: no cover
    for f in sys.argv[1:]:
        p = Path(f)
        d = json.loads(p.read_text())
        p.write_text(json.dumps(migrate(d), indent=2) + "\n")
