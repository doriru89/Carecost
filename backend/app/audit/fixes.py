"""Proposed source fixes, simulated on the built lines so each one's effect can be counted.

Each fix is the rule an ETL / engine stream would add (brief O item 4: "the proposed fix at the
source ... and how many outliers it removes"). Here a fix only filters or rescales rows of the
lines this audit built; no engine or ETL code changes. Fixes are applied cumulatively in
``ORDER`` and the outliers are recounted after each, so a count is the number of outliers that
disappear when that rule is added on top of the ones before it (peers move too).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from app.audit.causes import WRONG_PLAN
from app.audit.peers import Line
from app.quote.store import RateStore, Row

Fix = Callable[[list[Line], RateStore], list[Line]]


def _keep(lines: list[Line], pred: Callable[[Line, float, Row], bool]) -> list[Line]:
    out = []
    for ln in lines:
        rows = {u: (v, r) for u, (v, r) in ln.rows.items() if pred(ln, v, r)}
        if rows:
            ln2 = Line(ln.kind, ln.code, ln.mod, ln.component, ln.payer, ln.product, ln.network,
                       ln.group, ln.family, rows, ln.sites, ln.systems, ln.business)  # fmt: skip
            out.append(ln2)
    return out


def drop_placeholders(lines: list[Line], store: RateStore) -> list[Line]:
    """ETL (A5 normalize / A2 tic): a payer amount <= $1 or >= $99,999 is a placeholder, and a
    hospital payer amount equal to the row's own gross charge is the chargemaster price, not a
    negotiated rate: both -> excluded with a reason, never a price."""

    def ok(ln: Line, v: float, r: Row) -> bool:
        if v <= 1.0 or v >= 99999:
            return False
        if ln.family == "mrf" and r.gross and abs(v - r.gross) < 0.005:
            return False
        return True

    return _keep(lines, ok)


def plan_hygiene(lines: list[Line], store: RateStore) -> list[Line]:
    """ETL (A5 payers.py): a hospital row whose plan names Medicaid / Medicare / CMSP /
    non-contracted / out-of-network, or whose line of business is unknown, is never an
    insurance (commercial) rate."""

    def ok(ln: Line, v: float, r: Row) -> bool:
        if ln.family != "mrf" or ln.payer in ("MEDICARE", "MASSHEALTH"):
            return True
        return not (WRONG_PLAN.search(r.plan_raw) or r.line_of_business == "unknown")

    return _keep(lines, ok)


def site_pos(lines: list[Line], store: RateStore,
             kinds: tuple[str, ...] = ("office", "urgent_care")) -> list[Line]:  # fmt: skip
    """Engine (C3 engine.yaml place_of_service): price a line at the place of service the site
    bills: an office POS 11, an urgent care POS 20 (its rows listing 20 when the group has any for
    the line, else 11). Today office_visit = [11, 20] for both, so an office line also reads the
    payer's non-office rate that lists POS 20 among every POS except 11 (MGB Health Plan), and an
    urgent care line reads the office-only (POS 11) rate next to the payer's POS-20 rate."""
    out = []
    for ln in lines:
        if ln.component != "professional" or ln.family != "tic" or ln.mod == "26" or \
                ln.kind not in kinds:  # fmt: skip
            out.append(ln)
            continue
        want = "11" if ln.kind == "office" else "20"
        rows = {u: (v, r) for u, (v, r) in ln.rows.items() if want in r.pos()}
        if not rows and ln.kind == "urgent_care":
            rows = {u: (v, r) for u, (v, r) in ln.rows.items() if "11" in r.pos()}
        if rows:
            out.append(Line(ln.kind, ln.code, ln.mod, ln.component, ln.payer, ln.product,
                            ln.network, ln.group, ln.family, rows, ln.sites, ln.systems,
                            ln.business))  # fmt: skip
    return out


def main_contract(lines: list[Line], store: RateStore) -> list[Line]:
    """Engine (C3, D6): a TIN whose rows for one line come from several rate groups (different
    NPI subsets) is priced at the rate group covering the most NPIs (a packed row with no NPI list
    covers more than 25); the smaller groups are shown by doctor, not as the group's range."""

    def size(r: Row) -> int:
        return len(store.npi_sets.get(r.npi_set, ())) if r.npi_set else 26

    out = []
    for ln in lines:
        if ln.family != "tic" or len(ln.rows) < 2:
            out.append(ln)
            continue
        big = max(size(r) for _, r in ln.rows.values())
        rows = {u: (v, r) for u, (v, r) in ln.rows.items() if size(r) == big}
        out.append(Line(ln.kind, ln.code, ln.mod, ln.component, ln.payer, ln.product, ln.network,
                        ln.group, ln.family, rows, ln.sites, ln.systems, ln.business))  # fmt: skip
    return out


def children_apart(
    lines: list[Line], store: RateStore, children_only: frozenset[str] = frozenset()
) -> list[Line]:
    """Engine (C3 X2 peers): a line billed only at children-only sites is its own peer kind
    (``<kind>:children``); a pediatric hospital's rates are never the peers of an adult site."""
    out = []
    for ln in lines:
        if ln.sites and ln.sites <= children_only and not ln.kind.endswith(":children"):
            ln = Line(f"{ln.kind}:children", ln.code, ln.mod, ln.component, ln.payer, ln.product,
                      ln.network, ln.group, ln.family, ln.rows, ln.sites, ln.systems,
                      ln.business)  # fmt: skip
        out.append(ln)
    return out


ORDER: list[tuple[str, str, Fix]] = [
    ("F1", "drop placeholders and chargemaster-as-rate (A5/A2 normalize)", drop_placeholders),
    ("F2", "hospital plan hygiene: non-commercial / non-contracted / unknown-LOB rows (A5)",
     plan_hygiene),
    ("F3a", "office sites price at POS 11 only (C3 engine.yaml)",
     partial(site_pos, kinds=("office",))),
    ("F3b", "urgent care prices at POS 20 when the group lists it (C3 engine.yaml)",
     partial(site_pos, kinds=("urgent_care",))),
    ("F4", "children-only sites are their own peer kind (C3 X2 peers)", children_apart),
    ("F5", "one TIN, several rate groups: price at the largest NPI group (C3, D6)",
     main_contract),
]  # fmt: skip
