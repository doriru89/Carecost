"""Lines, X2 peer sets and outliers over a quote pack.

What a *line* is here (the unit the app can show one number for):

    (site kind, billing group, code, modifier, component, payer, plan product)

* **site kind** (X2): ``site_type`` grouped as urgent_care / office (specialist_office,
  primary_care_office) / hospital_outpatient / asc. ``ortho_walk_in`` counts as urgent_care and
  ``imaging_center`` as its own kind (neither is in the registry today).
* **billing group**: the billing TIN (or NPI) of a TiC row; a hospital file's rows are the
  hospital's own group ``mrf:<source_id>``. A TiC *facility* row at a hospital site is the
  hospital's own claim, so it joins the hospital's group (one group, not two, in a peer count).
* **payer, plan product**: an insurance request reads every network file of the payer and
  product into one range (``Registry.networks_for`` with no network), so the line does too. A
  hospital row with no product (or ``HMO/POS``) applies to every product it names (the engine's
  ``_hospital_rows``). Self-pay is payer ``SELF_PAY`` (the hospital file's discounted cash);
  Medicare / MassHealth are the hospital file's own rows for them.

Which rows a line holds follows the engine's own selection (``engine.py`` ``_site_lines``,
``_facility_cell3``, ``_doctor_cell``, ``_tic_rows``): a two-part site (hospital outpatient or ASC
billing) has a facility line plus a doctor / reading line (modifier 26 for PC/TC codes, any place
of service); an office site has one global line with the place-of-service filter of its billing
type. Rows of a census-linked TIN count only when they name the site.

A line's **peer median** is the median, over the *other* billing groups of the same peer key
(kind, code, modifier, component, payer, product), of each group's median price. A line is
**measured** when it has >= ``MIN_GROUPS`` other groups and is an **outlier** when its highest row
is above ``HIGH`` x the peer median or its lowest row below ``LOW`` x (P8).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.quote.registry import Registry
from app.quote.store import RateStore, Row
from app.sites.contracts import Site

MIN_GROUPS = 5
HIGH = 3.0
LOW = 1.0 / 3.0

KIND = {
    "urgent_care": "urgent_care",
    "ortho_walk_in": "urgent_care",
    "specialist_office": "office",
    "primary_care_office": "office",
    "hospital_outpatient": "hospital_outpatient",
    "ambulatory_surgery_center": "asc",
    "imaging_center": "imaging_center",
}
INSURANCE_LOBS = frozenset({"commercial", "connector", "unknown"})  # engine _facility_cell3
SELF_PAY = "SELF_PAY"
ANY_PRODUCT = "*"


@dataclass
class Line:
    kind: str
    code: str
    mod: str
    component: str  # facility | professional
    payer: str
    product: str
    network: str  # TiC network file id, or "hospital_file" (``product`` level: "*")
    group: str  # canonical billing group (TIN / NPI, or mrf:<source_id>)
    family: str  # tic | mrf | mrf_cash
    rows: dict[str, tuple[float, Row]] = field(default_factory=dict)  # uid -> (value, row)
    sites: set[str] = field(default_factory=set)
    systems: set[str] = field(default_factory=set)
    business: set[str] = field(default_factory=set)

    @property
    def peer_key(self) -> tuple[str, ...]:
        return (
            self.kind,
            self.code,
            self.mod,
            self.component,
            self.payer,
            self.product,
            self.network,
        )

    @property
    def values(self) -> list[float]:
        return [v for v, _ in self.rows.values()]

    @property
    def low(self) -> float:
        return min(self.values)

    @property
    def high(self) -> float:
        return max(self.values)


@dataclass
class Measured:
    line: Line
    peer_median: float
    peer_groups: int
    peer_p25: float
    peer_p75: float

    @property
    def ratio_high(self) -> float:
        return self.line.high / self.peer_median

    @property
    def ratio_low(self) -> float:
        return self.line.low / self.peer_median

    @property
    def outlier(self) -> str | None:
        if self.ratio_high > HIGH:
            return "high"
        if self.ratio_low < LOW:
            return "low"
        return None


def kind_of(site: Site) -> str:
    return KIND[site.site_type]


class LineBuilder:
    """Builds every line the registry's sites can show from a loaded pack."""

    def __init__(self, store: RateStore, reg: Registry, level: str = "network") -> None:
        if level not in ("network", "product"):
            raise ValueError(level)
        self.level = level
        self.store = store
        self.reg = reg
        cfg = reg.config
        self.pos = {k: frozenset(v) for k, v in cfg["place_of_service"].items()}
        self.office_pos = frozenset(reg.visit_map.pos_buckets.get("non_facility", ["11"]))
        self.facility_only = set(cfg["facility_only_codes"])
        self.mh_exclude = [w.upper() for w in cfg["masshealth_plan_exclude"]]
        self.pc_tc = reg.pc_tc_codes
        self.codes = sorted(store.codes)
        self.tic_sources = store.sources_of("insurer_tic")
        # payer -> products a request can carry (its TiC networks' products, plus the hospital
        # files' explicit products for payers we have no TiC file for)
        prods: dict[str, set[str]] = defaultdict(set)
        for sid in self.tic_sources:
            m = store.sources[sid]
            if m.payer_id and m.product:
                prods[m.payer_id].add(m.product)
        tic_payers = set(prods)
        for r in store.rows:
            if r.source_kind == "hospital_mrf" and r.payer_id and r.payer_id not in tic_payers:
                for p in r.product.split("/") if r.product else ():
                    prods[r.payer_id].add(p)
        self.payer_products = {k: frozenset(v) for k, v in prods.items()}
        self.lines: dict[tuple, Line] = {}

    # ------------------------------------------------------------------ helpers

    def _products(self, payer: str, product: str) -> Iterable[str]:
        if product:
            return product.split("/")
        return self.payer_products.get(payer) or (ANY_PRODUCT,)

    def _tic_products(self, payer: str, product: str) -> Iterable[str]:
        """network level: the network's own product (a network file is one plan); product level:
        every product a request can carry that reads this file (a file without a product, e.g.
        MGB ASO, is read for every MGB product: ``Registry.networks_for``)."""
        if self.level == "network":
            return (product or ANY_PRODUCT,)
        return self._products(payer, product)

    def _add(self, site: Site, kind: str, code: str, mod: str, comp: str, payer: str,
             product: str, group: str, family: str, value: float, row: Row) -> None:  # fmt: skip
        network = "*" if self.level == "product" else (
            row.source_id if row.source_kind == "insurer_tic" else "hospital_file")  # fmt: skip
        key = (kind, code, mod, comp, payer, product, network, group, family)
        ln = self.lines.get(key)
        if ln is None:
            ln = self.lines[key] = Line(kind, code, mod, comp, payer, product, network, group,
                                        family)  # fmt: skip
        ln.rows[row.uid] = (value, row)
        ln.sites.add(site.id)
        if site.system_id:
            ln.systems.add(site.system_id)
        if row.business_name:
            ln.business.add(row.business_name)

    def _hospital_source(self, site: Site) -> str | None:
        if not site.hospital_entity_id:
            return None
        src = self.reg.hospital_source.get(site.hospital_entity_id)
        return src if src in self.store.sources else None

    def _site_tins(self, site: Site) -> tuple[list[str], list[str]]:
        own = self.reg.site_tins(site)
        linked = sorted(self.store.census_tins.get(site.census_id or "", frozenset()) - set(own))
        return own, linked

    # ------------------------------------------------------------------ TiC

    def _tic(self, site: Site, kind: str, src: str | None) -> None:
        billing = site.billing_type
        two_part = billing in ("hospital_outpatient", "asc")
        pos = self.pos[billing]
        own, linked = self._site_tins(site)
        cid = site.census_id or ""
        for sid in self.tic_sources:
            meta = self.store.sources[sid]
            payer = meta.payer_id or ""
            for tins, need_name in ((own, False), (linked, True)):
                for tin in tins:
                    for code in self.codes:
                        rows = self.store.get("tic", (sid, tin, code))
                        if need_name:
                            rows = [r for r in rows if r.names_site(cid)]
                        if rows:
                            self._tic_rows(site, kind, two_part, pos, code, payer, meta.product,
                                           tin, src, rows)  # fmt: skip

    def _tic_rows(self, site: Site, kind: str, two_part: bool, pos: frozenset, code: str,
                  payer: str, net_product: str, tin: str, src: str | None,
                  rows: list[Row]) -> None:  # fmt: skip
        # facility side (two-part sites only), engine _facility_cell3: any POS, no percentage rows
        if two_part:
            fac = [r for r in rows if r.billing_class == "facility" and r.modifiers == ""
                   and r.amount is not None and r.negotiated_type != "percentage"]  # fmt: skip
            group = f"mrf:{src}" if src else tin
            for r in fac:
                for p in self._tic_products(payer, r.product or net_product):
                    self._add(site, kind, code, "", "facility", payer, p, group, "tic", r.amount, r)
            if code in self.facility_only:
                return
        # doctor side
        if two_part and code in self.pc_tc:
            mod, any_pos = "26", True
        else:
            mod, any_pos = "", False
        cands = [r for r in rows if r.billing_class == "professional" and r.modifiers == mod
                 and r.amount is not None and (any_pos or r.pos() & pos)]  # fmt: skip
        if not any_pos and two_part and not (pos & self.office_pos):
            fac_pos = [r for r in cands if not (r.pos() & self.office_pos)]
            cands = fac_pos or cands
        for r in cands:
            for p in self._tic_products(payer, r.product or net_product):
                self._add(site, kind, code, mod, "professional", payer, p, tin, "tic", r.amount, r)

    # ------------------------------------------------------------------ hospital file

    def _mrf(self, site: Site, kind: str, src: str) -> None:
        if site.billing_type not in ("hospital_outpatient", "asc"):
            return  # an office-billed site never reads the hospital file (engine _site_lines)
        group = f"mrf:{src}"
        for code in self.codes:
            for r in self.store.get("cash", (src, code)):
                if r.modifiers == "" and r.component in ("facility", "unknown") and \
                        r.discounted_cash is not None:  # fmt: skip
                    self._add(site, kind, code, "", "facility", SELF_PAY, ANY_PRODUCT, group,
                              "mrf_cash", r.discounted_cash, r)  # fmt: skip
            for r in self.store.get("by_code", (src, code)):
                if r.row_kind != "payer_rate" or not r.payer_id or r.amount is None:
                    continue
                if r.line_of_business in INSURANCE_LOBS:
                    payer = r.payer_id
                elif r.line_of_business == "medicare" and r.payer_id == "MEDICARE":
                    payer = "MEDICARE"
                elif r.line_of_business == "medicaid" and r.payer_id == "MASSHEALTH":
                    if any(w in r.plan_raw.upper() for w in self.mh_exclude):
                        continue
                    payer = "MASSHEALTH"
                else:
                    continue
                prods = ([ANY_PRODUCT] if payer in ("MEDICARE", "MASSHEALTH")
                         else list(self._products(payer, r.product)))  # fmt: skip
                if r.component in ("facility", "unknown") and r.modifiers == "":
                    for p in prods:
                        self._add(site, kind, code, "", "facility", payer, p, group, "mrf",
                                  r.amount, r)  # fmt: skip
                elif r.component == "professional" and payer not in ("MEDICARE", "MASSHEALTH"):
                    if code in self.facility_only:
                        continue
                    mod = "26" if code in self.pc_tc else ""
                    if r.modifiers != mod:
                        continue
                    for p in prods:
                        self._add(site, kind, code, mod, "professional", payer, p, group, "mrf",
                                  r.amount, r)  # fmt: skip

    # ------------------------------------------------------------------ build

    def build(self) -> list[Line]:
        for site in self.reg.sites.values():
            kind = kind_of(site)
            src = self._hospital_source(site)
            self._tic(site, kind, src)
            if src:
                self._mrf(site, kind, src)
        return list(self.lines.values())


def group_medians(lines: Iterable[Line]) -> dict[tuple, dict[str, tuple[float, set[str]]]]:
    """peer key -> {group: (median of every row of that group across families, its systems)}."""
    vals: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    systems: dict[tuple, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for ln in lines:
        vals[ln.peer_key][ln.group].extend(ln.values)
        systems[ln.peer_key][ln.group] |= ln.systems
    return {
        k: {g: (statistics.median(v), systems[k][g]) for g, v in groups.items()}
        for k, groups in vals.items()
    }


def quartiles(vals: list[float]) -> tuple[float, float]:
    if len(vals) < 2:
        return vals[0], vals[0]
    q = statistics.quantiles(vals, n=4, method="inclusive")
    return q[0], q[2]


def measure(lines: list[Line], min_groups: int = MIN_GROUPS) -> list[Measured]:
    """Every line with >= min_groups other groups in its peer set (same_kind, X2)."""
    gm = group_medians(lines)
    out: list[Measured] = []
    for ln in lines:
        others = [m for g, (m, _) in gm[ln.peer_key].items() if g != ln.group]
        if len(others) < min_groups:
            continue
        med = statistics.median(others)
        if med <= 0:
            continue
        p25, p75 = quartiles(others)
        out.append(Measured(ln, med, len(others), p25, p75))
    return out
