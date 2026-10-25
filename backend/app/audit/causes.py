"""Cause classes for an outlier line (brief O item 3), decided mechanically from the rows.

Each rule looks at the line's *outlying rows* (rows outside the 1/3x-3x band) and at the same
group's other rows and codes. The first rule that matches names the cause; ``unexplained`` is what
is left. A rule is a test anyone can re-run on the source row, never a judgement call.

| cause | test |
|---|---|
| placeholder | an outlying value <= $1.00 or >= $99,999 |
| not_dollars | hospital row: the "dollar" is under 1% of the row's own gross charge (CHA's CASE-45378 colonoscopy at $5.04 of a $3,510.55 charge: a weight or unit count, not dollars) |
| chargemaster_as_rate | hospital row: the payer amount equals the row's gross charge to the cent |
| percent_as_dollars | hospital row: the amount equals the stated percentage (a 35% read as $35) |
| per_diem_or_case_rate | hospital row: plan, item description or methodology in the raw row says per diem / half day / case rate (a program or episode charge carrying a CPT code) |
| wrong_plan | hospital row: plan text names a non-commercial or non-contracted plan, or the payer and plan disagree, or the line of business is unknown |
| facility_professional_mixup | the value sits inside 1/3x-3x of the *other* component's peer median (a facility line priced like a doctor's fee, or the reverse), and the two medians are > 3x apart |
| anesthesia_per_unit | 008xx code and the group has the same amount on another 008xx code with different CMS base units (a conversion factor per unit, not a case price) |
| pos_facility_rate_at_office | office site, every outlying TiC row omits POS 11 (it matched on POS 20 only: the payer's facility / non-office rate) |
| pos_office_rate_at_hospital | hospital line, every outlying TiC row lists POS 11 and neither 19 nor 22 |
| pos_office_rate_at_urgent_care | urgent care site, every outlying TiC row omits POS 20 while the group has a row for this line that lists POS 20 (the payer's rate at an urgent care facility) |
| flat_rate | the group has this exact amount on >= 2 other codes of the same code family in the same network (one rate for several levels) |
| ambiguous_multi_rate | an in-band row of the same group has the same NPI set and the same POS list: the file lists two prices for the same doctors and place of service |
| peers_flat_rate | most peer groups (> 50%) charge one amount across >= 3 codes of the family: the peer median is a flat visit rate, not this code's price (e.g. MGB urgent cares at $150 for any E/M level vs 99211's $7-$10) |
| rate_group_within_tin | the group's other rows for this line are inside the band: the outlying number is one rate group (a subset of NPIs) of a TIN with several contracts |
| children_only_contract | contract_level, and every site of the line is children-only (``Site.children_only``): a pediatric hospital's rates compared with adult peers |
| contract_level | the group is at >= 2x (or <= 0.5x) its peers, median over >= 5 other codes in the same network and kind: a consistent contract level (genuine variation) |
| unexplained | none of the above |
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass

from app.audit.peers import HIGH, LOW, MIN_GROUPS, Line, Measured, group_medians

CAUSES = [
    "placeholder",
    "not_dollars",
    "chargemaster_as_rate",
    "percent_as_dollars",
    "per_diem_or_case_rate",
    "wrong_plan",
    "facility_professional_mixup",
    "anesthesia_per_unit",
    "pos_facility_rate_at_office",
    "pos_office_rate_at_hospital",
    "pos_office_rate_at_urgent_care",
    "flat_rate",
    "peers_flat_rate",
    "ambiguous_multi_rate",
    "rate_group_within_tin",
    "children_only_contract",
    "contract_level",
    "unexplained",
]

# CMS 2026 anesthesia base units (ANES2026.csv): 00811 = 4, 00812 = 3, 00813 = 5
ANES_BASE_UNITS = {"00811": 4, "00812": 3, "00813": 5}

FAMILIES = [
    ["99202", "99203", "99204", "99205"],
    ["99211", "99212", "99213", "99214", "99215"],
    ["11300", "11301", "11302", "11303", "11305", "11306", "11307", "11308", "11310", "11311",
     "11312", "11313"],
    ["11102", "11104"],
    ["17000", "17110"],
    ["20610", "20611"],
    ["97161", "97162", "97163"],
    ["73221", "73222"],
    ["76881", "76882"],
    ["43239", "45378", "45380", "45385"],
    ["29826", "29827"],
    ["00811", "00812", "00813"],
    ["99051", "S9083", "S9088"],
]  # fmt: skip
FAMILY = {c: tuple(f) for f in FAMILIES for c in f}

WRONG_PLAN = re.compile(
    r"MEDICAID|MASSHEALTH|CMSP|MEDICARE|SENIOR|ADVANTAGE|\bDUAL|\bSCO\b|ONE ?CARE|"
    r"NON[- ]?CONTRACT|OUT OF NETWORK|\bOON\b|WORKERS|WORK COMP|AUTO|LIMITED",
    re.I,
)
PER_DIEM = re.compile(r"per[_ ]?diem|half[ -]day|per day|case[_ ]?rate", re.I)
NOT_DOLLARS_SHARE = 0.01


@dataclass
class Verdict:
    cause: str
    detail: str


def outlying(m: Measured) -> list:
    """(value, row) of the line outside the band, most extreme first."""
    med = m.peer_median
    bad = [(v, r) for v, r in m.line.rows.values() if v / med > HIGH or v / med < LOW]
    return sorted(bad, key=lambda t: -abs(_log_ratio(t[0], m.peer_median)))


def _log_ratio(v: float, med: float) -> float:
    import math

    return math.log(max(v, 0.005) / med)


class Classifier:
    def __init__(self, lines: list[Line], measured: list[Measured],
                 children_only: frozenset[str] = frozenset()) -> None:  # fmt: skip
        self.children_only = children_only
        # (network, kind, group, mod, component) -> code -> set of amounts
        self.amounts: dict[tuple, dict[str, set[float]]] = defaultdict(lambda: defaultdict(set))
        for ln in lines:
            k = (ln.network, ln.kind, ln.group, ln.payer, ln.product)
            self.amounts[k][ln.code] |= {round(v, 2) for v in ln.values}
        # flat groups: (network, kind, group, payer, product, component, family) with one
        # amount on >= 3 codes of the family
        self.flat: set[tuple] = set()
        med_by: dict[tuple, dict[str, float]] = defaultdict(dict)
        for ln in lines:
            fam = FAMILY.get(ln.code)
            if fam:
                med_by[(ln.network, ln.kind, ln.group, ln.payer, ln.product, ln.component, fam)][
                    ln.code] = round(statistics.median(ln.values), 2)  # fmt: skip
        for k, codes in med_by.items():
            c = defaultdict(int)
            for v in codes.values():
                c[v] += 1
            if c and max(c.values()) >= 3:
                self.flat.add(k)
        self.gm = group_medians(lines)
        # (network, kind, group, payer, product) -> code -> median ratio to peers
        self.ratios: dict[tuple, dict[str, float]] = defaultdict(dict)
        for m in measured:
            ln = m.line
            k = (ln.network, ln.kind, ln.group, ln.payer, ln.product)
            self.ratios[k][f"{ln.code}-{ln.mod}-{ln.component}"] = (
                statistics.median(ln.values) / m.peer_median)  # fmt: skip

    def _other_component_median(self, ln: Line) -> float | None:
        comp = "professional" if ln.component == "facility" else "facility"
        mods = ("", "26") if comp == "professional" else ("",)
        for mod in mods:
            k = (ln.kind, ln.code, mod, comp, ln.payer, ln.product, ln.network)
            vals = [m for g, (m, _) in self.gm.get(k, {}).items() if g != ln.group]
            if len(vals) >= MIN_GROUPS:
                return statistics.median(vals)
        return None

    def _peers_flat_share(self, m: Measured) -> float:
        ln = m.line
        fam = FAMILY.get(ln.code)
        if not fam:
            return 0.0
        groups = [g for g in self.gm.get(ln.peer_key, {}) if g != ln.group]
        if not groups:
            return 0.0
        flat = sum((ln.network, ln.kind, g, ln.payer, ln.product, ln.component, fam) in self.flat
                   for g in groups)  # fmt: skip
        return flat / len(groups)

    def classify(self, m: Measured, quote: str = "") -> Verdict:
        """``quote``: the traced raw text of the line's most extreme row (item description,
        methodology), when the caller has it."""
        ln = m.line
        bad = outlying(m)
        vals = [v for v, _ in bad]
        rows = [r for _, r in bad]
        key = (ln.network, ln.kind, ln.group, ln.payer, ln.product)
        if any(v <= 1.0 or v >= 99999 for v in vals):
            return Verdict("placeholder", f"value {min(vals) if min(vals) <= 1 else max(vals)}")
        hosp = [r for r in rows if r.source_kind == "hospital_mrf"]
        if hosp and ln.family in ("mrf", "mrf_cash"):
            if all(r.gross and r.gross > 100 and v < NOT_DOLLARS_SHARE * r.gross
                   for v, r in bad):  # fmt: skip
                v, r = bad[0]
                return Verdict("not_dollars", f"{v} is {v / r.gross:.2%} of the gross {r.gross}")
            if PER_DIEM.search(quote) or all(PER_DIEM.search(r.plan_raw) for r in hosp):
                hit = PER_DIEM.search(quote) or PER_DIEM.search(hosp[0].plan_raw)
                return Verdict("per_diem_or_case_rate", f"raw text {hit.group(0)!r}")
        if hosp and ln.family == "mrf":
            if all(r.gross and abs(r.amount - r.gross) < 0.005 for r in hosp):
                return Verdict("chargemaster_as_rate", f"amount {hosp[0].amount} = gross "
                                                      f"{hosp[0].gross}")  # fmt: skip
            if all(r.negotiated_pct is not None and abs(r.amount - r.negotiated_pct) < 0.01
                   for r in hosp):  # fmt: skip
                return Verdict("percent_as_dollars", f"amount {hosp[0].amount} = "
                                                    f"{hosp[0].negotiated_pct}%")  # fmt: skip
            bad_plan = [r for r in hosp if WRONG_PLAN.search(r.plan_raw)
                        or r.line_of_business == "unknown"]  # fmt: skip
            if len(bad_plan) == len(hosp) and ln.payer not in ("MEDICARE", "MASSHEALTH"):
                r = bad_plan[0]
                return Verdict("wrong_plan", f"plan {r.plan_raw!r} lob {r.line_of_business}")
        other = self._other_component_median(ln)
        if other and (other / m.peer_median > HIGH or other / m.peer_median < LOW) and \
                all(LOW <= v / other <= HIGH for v in vals):  # fmt: skip
            return Verdict("facility_professional_mixup",
                           f"{vals[0]} vs {('professional' if ln.component == 'facility' else 'facility')}"
                           f" peers {other:.2f}, {ln.component} peers {m.peer_median:.2f}")  # fmt: skip
        if ln.code in ANES_BASE_UNITS:
            same = [c for c in ANES_BASE_UNITS if c != ln.code
                    and set(round(v, 2) for v in vals) & self.amounts[key].get(c, set())]  # fmt: skip
            if same:
                return Verdict("anesthesia_per_unit", f"same amount on {', '.join(same)}")
        tic = [r for r in rows if r.source_kind == "insurer_tic"]
        if tic and len(tic) == len(rows):
            if ln.kind in ("office",) and ln.component == "professional" and \
                    all("11" not in r.pos() for r in tic):  # fmt: skip
                return Verdict("pos_facility_rate_at_office", f"POS {tic[0].service_codes[:40]}")
            if ln.kind == "hospital_outpatient" and ln.component == "professional" and \
                    ln.mod == "" and all("11" in r.pos() and not (r.pos() & {"19", "22"})
                                         for r in tic):  # fmt: skip
                return Verdict("pos_office_rate_at_hospital", f"POS {tic[0].service_codes[:40]}")
            if ln.kind == "urgent_care" and ln.component == "professional" and \
                    all("20" not in r.pos() for r in tic) and \
                    any("20" in r.pos() for _, r in ln.rows.values()):  # fmt: skip
                return Verdict("pos_office_rate_at_urgent_care",
                               f"POS {tic[0].service_codes[:40]}")  # fmt: skip
        fam = FAMILY.get(ln.code, ())
        flat = [c for c in fam if c != ln.code
                and {round(v, 2) for v in vals} & self.amounts[key].get(c, set())]  # fmt: skip
        if len(flat) >= 2:
            return Verdict("flat_rate", f"same amount on {', '.join(flat)}")
        share = self._peers_flat_share(m)
        if share > 0.5:
            return Verdict("peers_flat_rate", f"{share:.0%} of peer groups are flat across "
                                              f"{'/'.join(FAMILY[ln.code])}")  # fmt: skip
        inside = [v for v, _ in ln.rows.values() if LOW <= v / m.peer_median <= HIGH]
        if inside:
            ok = [r for v, r in ln.rows.values() if LOW <= v / m.peer_median <= HIGH]
            twin = [r for r in ok for b in rows
                    if r.source_id == b.source_id and r.npi_set and r.npi_set == b.npi_set
                    and r.service_codes == b.service_codes]  # fmt: skip
            if twin:
                return Verdict("ambiguous_multi_rate",
                               f"same NPIs + POS as stage_row {twin[0].stage_row} "
                               f"({ln.rows[twin[0].uid][0]:.2f})")  # fmt: skip
            return Verdict("rate_group_within_tin",
                           f"{len(inside)} of {len(ln.rows)} rows in range "
                           f"({min(inside):.2f}-{max(inside):.2f})")  # fmt: skip
        own = f"{ln.code}-{ln.mod}-{ln.component}"
        others = [r for c, r in self.ratios[key].items() if c != own]
        if len(others) >= 5:
            med = statistics.median(others)
            side = m.outlier
            if (side == "high" and med >= 2.0) or (side == "low" and med <= 0.5):
                if ln.sites and ln.sites <= self.children_only:
                    return Verdict("children_only_contract", f"median ratio {med:.2f} over "
                                                             f"{len(others)} other codes")  # fmt: skip
                return Verdict("contract_level", f"median ratio {med:.2f} over {len(others)} "
                                                 "other codes")  # fmt: skip
        return Verdict("unexplained", "")
