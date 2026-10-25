"""The quote engine: care path (or manual codes) x payment x sites -> ``QuoteResponse``.

care path steps -> codes -> rate rows (in-memory ``RateStore``) -> receipt lines, validated by the
contract exactly once. Every dollar is a rate row's number (``prov`` / ``prov_high``); every
missing number is a typed Gap from a real lookup that found nothing:

* ``not_published``: we searched the named file for this code / payer / modifier and it has no
  dollar row (``searched`` names the file);
* ``percent_only``: the file has only "X% of charges" for it;
* ``not_loaded``: a source exists but we do not read it yet (a code outside the ETL code list, an
  insurer network we have no TiC file for, a site whose doctor groups are not linked to billing
  TINs, a clinic's self-pay page, a government fee schedule A3 has not loaded);
* ``no_source``: no public source exists (a doctor's self-pay fee);
* ``conflict`` (D20): two dollar amounts for the same line that do not overlap and are more than
  10% apart (a stated dollar vs a %-of-charges amount, or the hospital file vs the insurer's TiC
  file). Both are shown, neither is summed.

Lines per step and code, by how the site bills:

* hospital outpatient / ASC: the facility's fee and the doctor's fee. Imaging and pathology have
  a professional/technical split: the doctor's part is the reading (modifier 26). Therapy codes
  have no separate doctor's fee; anesthesia has only the anesthesiologist's fee.
* office visit: one global fee (insurer TiC, office place of service).

The doctor's fee follows the ladder of plan §2.4 (D5, D6): rung 2 the group's TiC rate (by doctor
when the NPIs are known and prices differ), rung 3 the hospital file's professional line, rung 4
MassHealth, rung 5 Medicare, rung 6 the peer estimate (C3, below), rung 7 Medicare as a reference
floor (shown, never summed). Self-pay doctor fees have no public source.

C3 (wave-2 review R1-R12, Austin's rulings P1-P9), at the source:

* **Offer evidence** (R1, P6): a site offers a step only when its own hospital file lists the
  code, it (or its chain) posts a price, a sites.yaml ``offered`` entry covers it, or site facts
  (X1) say so. A TiC row is a contract term, never evidence. Not offered = never summed (R2).
* **Admission** (R8): a site enters a path when it offers the entry visit or the core procedure.
* **TIN roles** (R3): an ASC's own TINs price its facility line, never the doctor's.
* **Peers** (R4, P5, X2): a missing line of an offered step is estimated from the same line's real
  prices at >= 5 billing groups of the same kind of site, same payer and product (p25-p75, cited
  rows). Peers are drawn from every admitted site, never from the response, so the answer does
  not depend on which sites the person sees.
* **Unusual** (R17, P8): rows outside 1/3x-3x of the peer median are set aside, never summed.
* **Steps** (P1, P3, P4): each site gets a step summary; a step it does not do shows the p25-p75
  at sites that do. Ranking compares missing steps, then own prices + estimates and elsewhere
  steps at their neutral peer median. No location (P7): every admitted site, grouped by kind,
  by distance from Boston City Hall.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.care_paths.models import CarePath
from app.etl.contracts import Method, PriceBasis
from app.quote.facts import SiteFacts, load_site_facts
from app.quote.tin_roles import effective_billing, load_roles
from app.quote.contracts import (
    KIND_ORDER,
    CashPayment,
    InsurancePayment,
    MassHealthPayment,
    MedicarePayment,
    QuoteRequest,
    QuoteResponse,
    tier_basis_for_rating,
)
from app.quote.registry import Registry, posted_source
from app.quote.store import (
    DEFAULT_RULES,
    FEE_SCHEDULE_KINDS,
    REPO_ROOT,
    RateStore,
    Row,
    SourceMeta,
)
from app.sites.contracts import Freshness, Site

Json = dict[str, Any]
NO_NUMBER = ("not_published", "not_loaded", "no_source")
COPY_KEYS = ["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"]
GFE_ASK = (
    "Ask for a Good Faith Estimate (No Surprises Act). In Massachusetts the office must tell you "
    "the price within 2 business days (c.111 §228)."
)


def _km(near: Any, site: Site) -> float:
    """Great-circle distance (km) from the request's point to a site (haversine)."""
    la1, lo1 = math.radians(near.lat), math.radians(near.lon)
    la2, lo2 = math.radians(site.coords.lat), math.radians(site.coords.lon)
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 12742.0 * math.asin(math.sqrt(h))


class _P:
    """A point (lat / lon) for ``_km``."""

    def __init__(self, lat: float, lon: float) -> None:
        self.lat, self.lon = lat, lon


def _rank_pos(n: int, pct: float) -> int:
    """Nearest-rank percentile index into a sorted list of n values (so it is a real value)."""
    return min(n - 1, max(0, math.ceil(pct / 100 * n) - 1))


def _lower_median(vals: list[float]) -> float:
    v = sorted(vals)
    return v[(len(v) - 1) // 2]


def yaml_load(path: Any) -> Any:
    import yaml

    return yaml.safe_load(path.read_text())


def _slug(text: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", text.lower()))[:60] or "chain"


def _public(o: Any) -> Any:
    """The response without the engine's private keys (``_m`` rows, ``_item`` ...)."""
    if isinstance(o, dict):
        return {k: _public(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [_public(v) for v in o]
    return o


def _matches(when: dict[str, list[str]], answers: dict[str, list[str]]) -> bool:
    return all(set(vals) & set(answers.get(q, [])) for q, vals in when.items())


def _searched(store: RateStore, sid: str) -> Json:
    return {"source_id": sid, "source_sha256": store.sources[sid].source_sha256}


def _not_published(store: RateStore, sid: str, what: str, ask: str) -> Json:
    return {"kind": "not_published", "what": what, "ask": ask, "searched": _searched(store, sid)}


def _not_loaded(what: str, eta: str | None = None) -> Json:
    return {"kind": "not_loaded", "what": what, "eta": eta}


def _no_source(what: str, ask: str = GFE_ASK) -> Json:
    return {"kind": "no_source", "what": what, "ask": ask}


def code_class(code: str) -> str:
    if code[:1] == "J":
        return "drug"
    if code[:3] == "992" or code in ("S9083", "G0463"):
        return "visit"
    if code[:2] in ("00", "01") and code.isdigit():
        return "anesthesia"
    if code.startswith("97"):
        return "therapy"
    if code[:1] == "7" and code.isdigit():
        return "imaging"
    if code[:1] == "8" and code.isdigit():
        return "lab"
    return "procedure"


@dataclass
class Item:
    """One code to price for one step (or one manual pick)."""

    stem: str
    code: str
    unit: str
    plain: str
    tech: str
    why: str | None
    likelihood: str
    tier_basis: str
    step_id: str | None
    gloss: list[str]
    learn: list[Json]
    ai: bool = False
    at: str = "this_site"
    display_mod: str | None = None
    path_id: str | None = None
    step_codes: tuple[str, ...] = ()  # the step's primary + alternative codes (offer evidence)
    step_kind: str | None = None


@dataclass
class Req:
    """Per-request state. The shared engine never stores anything request-specific (P1 #20)."""

    req: QuoteRequest
    kind: str
    payer: str | None
    product: str
    networks: list[str]
    as_of: date
    posted: dict[str, SourceMeta] = field(default_factory=dict)


class Engine:
    def __init__(self, store: RateStore, registry: Registry | None = None) -> None:
        self.store = store
        self.reg = registry or Registry.load()
        cfg = self.reg.config
        self.cfg = cfg
        self.pos = {k: frozenset(v) for k, v in cfg["place_of_service"].items()}
        self.office_pos = frozenset(self.reg.visit_map.pos_buckets.get("non_facility", ["11"]))
        self.fs_setting = cfg["fee_schedule_setting"]
        self.facility_only = set(cfg["facility_only_codes"])
        self.per15 = set(cfg["per_15_minutes"])
        self.neutral_mods = set(cfg["pricing_neutral_modifiers"])
        self.threshold = float(cfg["conflict_threshold"])
        own_posted = {s.id: m for s in self.reg.sites.values() if (m := posted_source(s))}
        self.posted_by_source = {m.source_id: m for m in own_posted.values()}
        # R12: a chain's posted price list applies at every location of the chain
        self.chain_of: dict[str, str] = {}
        self.posted_site: dict[str, Site] = {}  # site id -> the site whose cash_prices apply
        self.posted: dict[str, SourceMeta] = dict(own_posted)
        for cid, ch in (cfg.get("chains") or {}).items():
            src_site = self.reg.sites.get(ch.get("posted_price_site", ""))
            for s in self.reg.sites.values():
                if s.operator == ch["operator"]:
                    self.chain_of[s.id] = cid
                    if (
                        s.id not in own_posted
                        and src_site is not None
                        and src_site.id in own_posted
                    ):
                        self.posted[s.id] = own_posted[src_site.id]
                        self.posted_site[s.id] = src_site
        for s in self.reg.sites.values():
            self.posted_site.setdefault(s.id, s)
        self.uc_types = frozenset(cfg["urgent_care_site_types"])
        self.kind_by_billing: dict[str, str] = cfg["kind_by_billing"]
        self.unknown_as: str = cfg["unknown_billing_priced_as"]
        self.peer_cfg = cfg["peers"]
        self.out_cfg = cfg["outliers"]
        self.role_rule: dict[str, str] = cfg["tin_role_by_billing"]
        self.roles = load_roles(REPO_ROOT / cfg["tin_roles_file"])
        self.facts: SiteFacts = load_site_facts()
        bdoc = REPO_ROOT / cfg["anesthesia_time_file"]
        self.anes_base: dict[str, float] = {
            str(k).zfill(5): float(v)
            for k, v in ((yaml_load(bdoc) or {}).get("base_units") or {}).items()
        } if bdoc.exists() else {}  # fmt: skip
        self.anes_time = self._load_anesthesia_time(
            REPO_ROOT / cfg["physician_time_file"], REPO_ROOT / cfg["anesthesia_time_file"]
        )
        o = cfg["no_location_origin"]
        self.origin = _P(float(o["lat"]), float(o["lon"]))
        # caches over data that never changes after startup (no request state, P1 #20)
        self._code_offer: dict[tuple[str, str], bool] = {}
        self._stats: dict[tuple, dict] = {}
        self._peer_cache: dict[tuple, tuple[list, str]] = {}
        self._admitted_cache: dict[tuple, list[str]] = {}
        self._universe: dict[tuple, Json] = {}
        # fee schedules: every loaded file of a kind (Medicare PFS = RVU file + anesthesia file;
        # MassHealth = 101 CMR 316 / 317 / 318). One release per file id.
        self.pfs = self.store.sources_of("medicare_pfs")
        self.opps = self.store.sources_of("medicare_opps")
        self.asc = self.store.sources_of("medicare_asc")
        self.mh = self.store.sources_of("masshealth_fs")
        self.tic_sources = self.store.sources_of("insurer_tic")

    # ------------------------------------------------------------------ money from rows

    def _money(self, rows: list[Row], value: Callable[[Row], float | None], basis: PriceBasis,
               method: Method | None = None) -> Json | None:  # fmt: skip
        """Money over the values of ``rows``: low cites the lowest row (first in source order),
        high cites the highest row (P1 #2)."""
        vals = [(v, i, r) for i, r in enumerate(rows) if (v := value(r)) is not None]
        if not vals:
            return None
        lo = min(vals, key=lambda t: (t[0], t[1]))
        hi = max(vals, key=lambda t: (t[0], -t[1]))
        out: Json = {
            "kind": "money",
            "low": lo[0],
            "high": hi[0],
            "basis": basis.value,
            "prov": self.store.prov_dict(lo[2], basis, method=method),
        }
        if hi[0] > lo[0]:
            out["prov_high"] = self.store.prov_dict(hi[2], basis, method=method)
        # private (stripped before validation): the rows behind it, for peers and the P8 check
        out["_m"] = ([(v, r) for v, _, r in vals], value, basis, method)
        return out

    def _far(self, a: Json, b: Json) -> bool:
        """D20: the two ranges do not overlap and the gap is more than the threshold."""
        lo, hi = (a, b) if a["high"] <= b["high"] else (b, a)
        if hi["low"] <= lo["high"]:
            return False
        return (hi["low"] - lo["high"]) > self.threshold * max(lo["high"], 0.01)

    def _combine(self, first: Json | None, second: Json | None) -> Json | None:
        if first and second and self._far(first, second):
            return {"kind": "conflict", "a": first, "b": second}
        return first or second

    # ------------------------------------------------------------------ facility side

    def _hospital_rows(self, src: str, codes: list[str], payer: str, lobs: set[str],
                       product: str | None, component=("facility", "unknown"),
                       mods=("",)) -> list[Row]:  # fmt: skip
        out = []
        for code in codes:
            for r in self.store.get("hospital", (src, code, payer)):
                if (
                    r.row_kind == "payer_rate"
                    and r.payer_id == payer
                    and r.line_of_business in lobs
                    and (product is None or r.product == "" or product in r.product.split("/"))
                    and r.modifiers in mods
                    and r.component in component
                ):
                    out.append(r)
        return out

    def _dollar_or_pct(self, rows: list[Row], src: str) -> tuple[Json | None, Json | None]:
        """D20 inside one file: a stated dollar wins over a %-of-charges amount; far apart -> a
        conflict. Returns (cell, percent_only gap)."""
        stated = self._money(
            [r for r in rows if r.amount_method == "stated"], lambda r: r.amount,
            PriceBasis.negotiated,
        )  # fmt: skip
        derived = self._money(
            [r for r in rows if r.amount_method == "derived_pct_x_gross"], lambda r: r.amount,
            PriceBasis.negotiated,
        )  # fmt: skip
        cell = self._combine(stated, derived) if stated else derived
        pct = sorted((r.negotiated_pct, r.stage_row) for r in rows if r.negotiated_pct is not None)
        po = None
        if pct:
            po = {
                "kind": "percent_only",
                "pct": pct[0][0],
                "of": "the hospital's full charge for this line, which its file does not list",
                "searched": _searched(self.store, src),
            }
        return cell, po

    def _site_tins(self, site: Site) -> tuple[list[str], list[str]]:
        """(the site's own billing TINs / NPIs, TINs the TiC matcher linked to its census id that
        it does not list). Rows of a linked TIN count only when they name the site."""
        own = self.reg.site_tins(site)
        linked = sorted(self.store.census_tins.get(site.census_id or "", frozenset()) - set(own))
        return own, linked

    def _billing(self, site: Site) -> str:
        """How the engine prices the site (P9: unknown -> hospital clinic, ASC site -> asc)."""
        return effective_billing(site, self.unknown_as)

    def _pos(self, site: Site) -> frozenset[str]:
        """Place-of-service codes a site's own professional rows must list. O F3a: an office reads
        POS 11 rows only (a POS-20 urgent-care rate or a facility rate is not its price)."""
        billing = self._billing(site)
        if billing == "office_visit" and self._kind(site) == "office":
            return self.pos["office_kind"]
        return self.pos[billing]

    def _kind(self, site: Site) -> str:
        """X2: urgent care by site type, every other kind by the effective billing type."""
        if site.site_type in self.uc_types:
            return "urgent_care"
        return self.kind_by_billing[self._billing(site)]

    def _role(self, site: Site, tin: str) -> str:
        """R3: tin_roles.yaml, else the site's billing-type rule."""
        return self.roles.get((site.id, tin)) or self.role_rule[self._billing(site)]

    def _site_tic(self, q: Req, site: Site, codes: list[str], mod: str, pos: frozenset,
                  billing_class: str, *, any_pos: bool = False,
                  networks: list[str] | None = None) -> list[Row]:  # fmt: skip
        """The site's TiC rows for one line. R3: a TIN with role ``facility`` (an ASC's own TIN)
        prices only the facility line, from its rows of either billing class (an ASC bills its
        fee on the professional form); a ``professional`` TIN only the doctor line;
        ``by_billing_class`` follows the row."""
        own, linked = self._site_tins(site)
        cid = site.census_id or ""
        rows: list[Row] = []
        for tins, named_only in ((own, False), (linked, True)):
            if not tins:
                continue
            roles = {t: self._role(site, t) for t in tins}
            if billing_class == "facility":
                part = self._tic_rows(q, [t for t in tins if roles[t] != "professional"], codes,
                                      mod, pos, "facility", any_pos=any_pos, networks=networks)  # fmt: skip
                fac = [t for t in tins if roles[t] == "facility"]
                if fac:
                    part += self._tic_rows(q, fac, codes, mod, self.pos["asc"], "professional",
                                           networks=networks)  # fmt: skip
            else:
                part = self._tic_rows(q, [t for t in tins if roles[t] != "facility"], codes, mod,
                                      pos, billing_class, any_pos=any_pos, networks=networks)  # fmt: skip
            rows += [r for r in part if not named_only or r.names_site(cid)]
        return rows

    def _tic_rows(self, q: Req, tins: Iterable[str], codes: list[str], mod: str, pos: frozenset,
                  billing_class: str, *, any_pos: bool = False,
                  networks: list[str] | None = None) -> list[Row]:  # fmt: skip
        rows: list[Row] = []
        for sid in q.networks if networks is None else networks:
            for tin in tins:
                for code in codes:
                    rows += self.store.get("tic", (sid, tin, code))
        cands = [
            r
            for r in rows
            if r.billing_class == billing_class
            and r.modifiers == mod
            and (any_pos or billing_class == "facility" or r.pos() & pos)
        ]
        if not any_pos and billing_class == "professional" and not (pos & self.office_pos):
            # a facility-side line: drop the non-facility rate when a facility one exists
            fac = [r for r in cands if not (r.pos() & self.office_pos)]
            cands = fac or cands
        return cands

    def _facility_cell3(self, site: Site, code: str, q: Req, cls: str):
        """Cash / insurance -> (cell, component_confirmed, list_price)."""
        src = self._site_hospital_source(site)
        codes = [code]
        if cls == "visit":
            codes += self.cfg["hospital_visit_facility_codes"]
        loaded = [c for c in codes if c in self.store.codes]
        list_price = self._list_price(src, code) if src else None
        what = "the facility's own fee for this item"
        if cls == "visit":
            what = "the hospital's clinic facility fee (HCPCS G0463 / revenue code 051x)"

        if q.kind == "cash":
            if src is None:
                return _no_source(f"{what} for a self-pay patient"), True, None
            if not loaded:
                return (
                    _not_loaded(f"{what}: we do not read this code from price files yet"),
                    True,
                    None,
                )
            rows = [r for c in loaded for r in self._cash_rows(src, c)]
            m = self._money(rows, lambda r: r.discounted_cash, PriceBasis.discounted_cash)
            if m:
                return m, all(r.component == "facility" for r in rows), list_price
            return _not_published(self.store, src,
                                  f"a self-pay (no insurance) price for {what}",
                                  "Ask the hospital for its self-pay (no insurance) price or a "
                                  "Good Faith Estimate."), True, list_price  # fmt: skip

        if q.kind == "insurance":
            first = pct = None
            confirmed = True
            if src and loaded:
                rows = self._hospital_rows(src, loaded, q.payer or "",
                                           {"commercial", "connector", "unknown"}, q.product)  # fmt: skip
                if not rows:
                    rows = self._hospital_rows(src, loaded, q.payer or "",
                                               {"commercial", "connector", "unknown"}, q.product,
                                               mods=("TC",))  # fmt: skip
                first, pct = self._dollar_or_pct(rows, src)
                confirmed = all(r.component == "facility" for r in rows if r.amount is not None)
            tic = None
            if q.networks and loaded:
                trows = self._site_tic(q, site, loaded, "", frozenset(), "facility")
                tic = self._money(
                    [r for r in trows if r.amount is not None and r.negotiated_type != "percentage"],
                    lambda r: r.amount, PriceBasis.negotiated,
                )  # fmt: skip
            cell = self._combine(first, tic) if first and first["kind"] == "money" else first or tic
            if cell:
                return cell, confirmed, list_price
            if pct:
                return pct, confirmed, list_price
            if not loaded:
                return (
                    _not_loaded(f"{what}: we do not read this code from price files yet"),
                    True,
                    list_price,
                )
            if src:
                return _not_published(self.store, src, f"this insurer's rate for {what} here",
                                      "Ask the billing office for a Good Faith Estimate for your "
                                      "plan."), True, list_price  # fmt: skip
            if q.networks:
                if site.billing_type == "unknown":  # P9
                    what = ("a hospital facility fee this place may also charge (we could not "
                            "confirm how it bills)")  # fmt: skip
                return _not_published(self.store, q.networks[0], f"this insurer's rate for {what}",
                                      "Ask the center what your plan pays for its facility fee."), \
                    True, list_price  # fmt: skip
            return _not_loaded(f"this insurer's rate for {what}: we have no price file for "
                               "your plan yet"), True, list_price  # fmt: skip

        raise AssertionError(q.kind)  # government payments: _gov_facility_cell

    def _facility_cell(self, site: Site, code: str, q: Req, cls: str):
        """-> (cell, component_confirmed, list_price, extra) where extra may carry
        ``price_notes`` and the ``codes`` the number was found under."""
        if q.kind in ("medicare", "masshealth"):
            return self._gov_facility_cell(site, code, q, cls)
        cell, confirmed, lp = self._facility_cell3(site, code, q, cls)
        return cell, confirmed, lp, {}

    def _gov_facility_cell(self, site: Site, code: str, q: Req, cls: str):
        """Medicare / MassHealth facility fee. The hospital file's own row for that payer wins (it
        is what this hospital is paid). Else Medicare's national schedule: OPPS for a hospital,
        ASC for a surgery center (national unadjusted: a Boston facility is paid it times a wage
        adjustment we have not loaded; the line says so). MassHealth's hospital outpatient
        payment (APAD / PAPE) is not loaded: not_loaded."""
        src = self._site_hospital_source(site)
        codes = [code]
        if cls == "visit":
            codes += self.cfg["hospital_visit_facility_codes"]
        loaded = [c for c in codes if c in self.store.codes]
        list_price = self._list_price(src, code) if src else None
        what = "the facility's own fee for this item"
        if cls == "visit":
            what = "the hospital's clinic facility fee (HCPCS G0463 / revenue code 051x)"
        label = {"medicare": "Medicare", "masshealth": "MassHealth"}[q.kind]
        own = None
        if src and loaded:
            lobs = {"medicare"} if q.kind == "medicare" else {"medicaid"}
            rows = self._hospital_rows(src, loaded, q.payer or "", lobs, None)
            if q.kind == "masshealth":  # not the standard MassHealth plan (engine.yaml)
                bad = [w.upper() for w in self.cfg["masshealth_plan_exclude"]]
                rows = [r for r in rows if not any(w in r.plan_raw.upper() for w in bad)]
            own, _ = self._dollar_or_pct(rows, src)
        if own:
            return own, True, list_price, {}
        if q.kind == "masshealth":
            return _not_loaded(f"MassHealth's hospital outpatient payment for {what} (APAD; not "
                               "loaded yet)"), True, list_price, {}  # fmt: skip
        fs_srcs = self.asc if self._billing(site) == "asc" else self.opps
        rows = [
            r for s in fs_srcs for c in codes for r in self.store.get("by_code", (s, c))
            if r.modifiers in ("", "TC") and r.billing_class in ("facility", "unknown")
        ]  # fmt: skip
        fs = self._money(rows, lambda r: r.amount, PriceBasis.fee_schedule)
        if fs:
            priced = sorted({r.code for r in rows if r.amount is not None},
                            key=codes.index)  # fmt: skip
            return fs, True, list_price, {
                "price_notes": ["price.national_unadjusted"],
                "codes": list(dict.fromkeys([code, *priced])),
            }  # fmt: skip
        if fs_srcs:
            return _not_published(self.store, self._fs_cite(fs_srcs, codes),
                                  f"{label}'s rate for {what}",
                                  "Ask the billing office what Medicare pays here."), \
                True, list_price, {}  # fmt: skip
        return (
            _not_loaded(f"{label}'s facility fee schedule for {what} (not loaded yet)"),
            True,
            list_price,
            {},
        )

    def _fs_cite(self, srcs: list[str], codes: list[str]) -> str:
        """The file a 'not published' fee-schedule claim names: the first that lists the code at
        all (another variant), else the first of the kind."""
        for s in srcs:
            if any(self.store.get("by_code", (s, c)) for c in codes):
                return s
        return srcs[0]

    def _cash_rows(self, src: str, code: str) -> list[Row]:
        return [
            r
            for r in self.store.get("cash", (src, code))
            if r.modifiers == "" and r.component in ("facility", "unknown")
        ]

    def _list_price(self, src: str, code: str) -> Json | None:
        if code not in self.store.codes:
            return None
        cands = [r for r in self._cash_rows(src, code) if r.gross is not None]
        if len({r.gross for r in cands}) != 1:
            return None  # several list prices for one line: not shown
        return self._money(cands[:1], lambda r: r.gross, PriceBasis.gross)

    def _site_hospital_source(self, site: Site) -> str | None:
        if not site.hospital_entity_id:
            return None
        src = self.reg.hospital_source.get(site.hospital_entity_id)
        return src if src in self.store.sources else None

    # ------------------------------------------------------------------ doctor side (ladder)

    def _areas(self, site: Site | None) -> frozenset[str]:
        """Fee-schedule price areas that apply at a site: its Medicare PFS locality, the national
        OPPS / ASC rates, MassHealth's statewide schedule."""
        loc = self.reg.medicare_locality(site) if site else self.cfg["medicare_locality"]["default"]
        return frozenset({f"medicare_ma_{loc}", "medicare_national", "masshealth"})

    def _fs_rows(self, srcs: list[str], code: str, mod: str, setting: str,
                 site: Site | None) -> list[Row]:  # fmt: skip
        """Doctor's-fee rows of a fee schedule: this modifier, this place of service (a rate not
        split by place of service counts at any), this site's price area."""
        areas = self._areas(site)
        return [
            r
            for src in srcs
            for r in self.store.get("by_code", (src, code))
            if r.modifiers == mod and r.place_of_service in (setting, "")
            and r.billing_class in ("professional", "unknown") and r.entity_id in areas
        ]  # fmt: skip

    def _fee_schedule_fee(self, srcs: list[str], code: str, mod: str, setting: str, rung: int,
                          label: str, site: Site | None):  # fmt: skip
        rows = self._fs_rows(srcs, code, mod, setting, site)
        m = self._money(rows, lambda r: r.amount, PriceBasis.fee_schedule)
        fee = {"rung": rung, "explanation_key": f"fee.rung_{rung}_" + (
            {4: "masshealth", 5: "medicare", 7: "medicare_reference"}[rung])}  # fmt: skip
        if m:
            return m, fee
        if srcs:
            return _not_published(
                self.store,
                self._fs_cite(srcs, [code]),
                f"{label}'s rate for this doctor's fee",
                "Ask the office what it bills for this service.",
            ), None
        if code_class(code) == "anesthesia":
            return _not_loaded(f"{label}'s anesthesia fee (base units x time x the anesthesia "
                               "conversion factor; not loaded yet)"), None  # fmt: skip
        return _not_loaded(f"{label}'s physician fee schedule (not loaded yet)"), None

    def _group_rate(self, rows: list[Row], code: str = "") -> tuple[Json, Json] | None:
        dollars = [r for r in rows if r.amount is not None and r.negotiated_type != "percentage"]
        value: Callable[[Row], float | None] = lambda r: r.amount  # noqa: E731
        method = None
        if code_class(code) == "anesthesia":
            dollars, value, method = self._anesthesia_units(dollars, code)
        money = self._money(dollars, value, PriceBasis.negotiated, method)
        if money is None:
            return None
        names = {r.business_name for r in dollars}
        gtins = {r.tin for r in dollars if r.tin_type != "npi"}
        tin = next(iter(gtins)) if len(gtins) == 1 else None
        fee: Json = {
            "rung": 2,
            "explanation_key": "fee.rung_2_group",
            "group_name": next(iter(names)) if len(names) == 1 and names != {""} else None,
            "group_tin": f"{tin[:2]}-{tin[2:]}" if tin and len(tin) == 9 else None,
        }
        by_npi = self._by_npi(dollars) if method is None else None
        if by_npi:
            fee["by_npi"] = by_npi
            fee["npi_count"] = len(by_npi)
        return money, fee

    def _anesthesia_units(self, rows: list[Row], code: str):
        """O audit: MGB and Fallon list an anesthesia group's 008xx codes at one per-unit rate
        (the same amount on codes with different CMS base units). Such a row is a conversion
        factor, not a fee: for an anesthesia group it prices the base units (rate x base units,
        method per_unit_x_base_units); for any other group (dermatology, health centers,
        surgicalists at a $20-30 default) it is not a fee and is left out."""
        bases = self.anes_base
        mine = bases.get(code)
        full, units = [], []
        for r in rows:
            twin = None
            for other, b in bases.items():
                if other == code or b == mine:
                    continue
                twin = next((x for x in self.store.tic.get((r.source_id, r.tin, other), ())
                             if x.amount == r.amount), None)  # fmt: skip
                if twin:
                    break
            if twin is None:
                full.append(r)
                continue
            if self.store.recorder is not None:
                self.store.recorder.add([twin])
            if mine and "ANESTH" in r.business_name.upper():
                units.append(r)
        if full or not units:
            return full, (lambda r: r.amount), None
        return units, (lambda r: round(r.amount * mine, 2)), Method.per_unit_x_base_units

    def _by_npi(self, dollars: list[Row]) -> list[Json] | None:
        """D6: per doctor, when the NPIs of every priced provider group are known and prices
        differ; otherwise the line shows the group range."""
        per: dict[str, list[Row]] = defaultdict(list)
        for r in dollars:
            npis = self.store.npis(r) if r.tin_type != "npi" else (r.tin,)
            if not npis:
                return None
            for n in npis:
                per[n].append(r)
        if not per or len(per) > self.cfg["ladder"]["max_by_npi"]:
            return None
        out = []
        for npi in sorted(per):
            m = self._money(per[npi], lambda r: r.amount, PriceBasis.negotiated)
            out.append({"npi": npi, "display_name": None, "money": m})
        if len({(p["money"]["low"], p["money"]["high"]) for p in out}) < 2:
            return None
        return out

    def _doctor_cell(self, site: Site, item: Item, code: str, mod: str, q: Req, *,
                     hospital_line: bool):  # fmt: skip
        """-> (cell, doctor_fee or None, codes shown on the line)."""
        billing = self._billing(site)
        setting = self.fs_setting[billing]
        pos = self._pos(site)
        if q.kind == "cash":
            posted = q.posted.get(site.id)
            if not hospital_line and site.hospital_entity_id is None:
                if posted:
                    return self._posted_cell(self.posted_site[site.id], posted, code), None, [code]
                return _not_loaded("this clinic's self-pay price: we have not read a posted "
                                   "self-pay price list for it"), None, [code]  # fmt: skip
            return _no_source("the doctor's own fee for a self-pay patient"), {
                "rung": None, "explanation_key": "fee.self_pay_no_source"}, [code]  # fmt: skip
        if q.kind == "medicare":
            cell, fee = self._fee_schedule_fee(self.pfs, code, mod, setting, 5, "Medicare", site)
            return cell, fee, [code]
        if q.kind == "masshealth":
            cell, fee = self._fee_schedule_fee(self.mh, code, mod, setting, 4, "MassHealth", site)
            if cell["kind"] != "money" and self.pfs:
                ref, rfee = self._fee_schedule_fee(self.pfs, code, mod, setting, 7, "Medicare",
                                                   site)  # fmt: skip
                if ref["kind"] == "money":
                    return ref, rfee, [code]
            return cell, fee, [code]

        # insurance
        codes = [code]
        if (
            code_class(code) == "visit"
            and not hospital_line
            and site.site_type in ("urgent_care", "ortho_walk_in")
        ):
            shape, vcodes = self.reg.visit_map.visit_codes(q.payer or "")
            if shape == "global_code":
                codes = vcodes  # Aetna: one urgent-care global code (S9083), no E/M rows
        if not any(c in self.store.codes for c in codes):
            return _not_loaded("this code's price: we do not read it from insurer files yet"), \
                None, codes  # fmt: skip
        if not q.networks:
            return _not_loaded("this insurer's rates for your plan: we have no price file for "
                               "this plan yet"), None, codes  # fmt: skip
        own, linked = self._site_tins(site)
        rad = (
            self.reg.radiology_tins.get(site.hospital_entity_id or "", [])
            if mod == "26" and hospital_line else []
        )  # fmt: skip
        if not own and not linked and not rad:
            return _not_loaded("the doctor's fee here: the insurer publishes it per billing "
                               "group, and we have not linked this site's doctor groups yet"), \
                None, codes  # fmt: skip
        # Austin 2026-10-24 (P1 #6): a professional reading (modifier 26) uses the group's TiC rate
        # even when the group lists it only at office place of service 11. Medicare pays the PC
        # of a diagnostic test the same in either setting: "For the professional component (PC)
        # of diagnostic tests, the facility and nonfacility payment rates are the same -
        # irrespective of the POS code on the claim." (Medicare Claims Processing Manual, Pub.
        # 100-04, chapter 12, §20.4.2 Site of Service Payment Differential,
        # https://www.cms.gov/Regulations-and-Guidance/Guidance/Manuals/downloads/clm104c12.pdf,
        # read 2026-10-24). Every other professional line keeps the place-of-service filter.
        # C2 (P1 #6): a hospital's reading (-26) is billed by the radiologists' group that reads
        # there (radiology_groups.yaml: CMS Doctors & Clinicians at the hospital's address -> TiC
        # NPI -> TIN); that group's rate first, the site's own billing groups only when it has none.
        rows: list[Row] = []
        got = None
        if rad:
            rows = self._tic_rows(q, rad, codes, mod, pos, "professional", any_pos=True)
            got = self._group_rate(rows, code)
        if got is None:
            rows = self._site_tic(q, site, codes, mod, pos, "professional", any_pos=(mod == "26"))
            got = self._group_rate(rows, code)
        if got:
            return got[0], got[1], codes
        src = self._site_hospital_source(site)
        if hospital_line and src:
            prof = self._hospital_rows(src, [code], q.payer or "",
                                       {"commercial", "connector", "unknown"}, q.product,
                                       component=("professional",), mods=(mod,))  # fmt: skip
            m = self._money([r for r in prof if r.amount is not None], lambda r: r.amount,
                            PriceBasis.negotiated)  # fmt: skip
            if m:
                return m, {"rung": 3, "explanation_key": "fee.rung_3_hospital_file"}, codes
        # a published "% of charges" term beats any estimate (security-gate F4): it is what the
        # contract says; the peer estimate (rung 6) is filled after every site is priced
        pct = sorted((r.negotiated_pct, r.stage_row) for r in rows if r.negotiated_pct is not None)
        if pct:
            return (
                {
                    "kind": "percent_only",
                    "pct": pct[0][0],
                    "of": "the doctor group's billed charge",
                    "searched": _searched(self.store, q.networks[0]),
                },
                None,
                codes,
            )
        if self.pfs:
            ref = self._money(self._fs_rows(self.pfs, code, mod, setting, site), lambda r: r.amount,
                              PriceBasis.fee_schedule)  # fmt: skip
            if ref:
                return ref, {"rung": 7, "explanation_key": "fee.rung_7_medicare_reference"}, codes
        return _not_published(self.store, q.networks[0],
                              "this insurer's rate for this doctor group and item",
                              "Ask the office which doctor group bills for it and what your "
                              "plan pays."), None, codes  # fmt: skip

    def _posted_cell(self, site: Site, meta: SourceMeta, code: str) -> Json:
        hits = [p for p in site.cash_prices if code in p.codes]
        if not hits:
            return {
                "kind": "not_published",
                "what": "a posted self-pay price for this item at this clinic",
                "ask": "Call the clinic and ask for its self-pay price.",
                "searched": {"source_id": meta.source_id, "source_sha256": meta.source_sha256},
            }
        p = min(hits, key=lambda p: (p.amount, p.item_id))
        prov: Json = {
            "source_id": meta.source_id,
            "source_kind": "clinic_posted",
            "source_file": meta.source_file,
            "source_sha256": meta.source_sha256,
            "source_date": None,
            "method": "stated",
            "row_ref": f"{meta.source_id}:{meta.source_sha256[:12]}:{p.item_id}",
            "payer_id": None,
            "row_id": None,
        }
        return {"kind": "money", "low": p.amount, "high": p.amount, "basis": "posted_self_pay",
                "prov": prov, "_posted": (p.amount, f"posted:{meta.source_id}", prov)}  # fmt: skip

    def _referral_cell(self, item: Item, q: Req):
        """P1 #15: the HMO referral visit happens at the person's own primary care office."""
        code = item.code
        if q.kind == "cash":
            return _no_source("your primary care office's self-pay fee"), {
                "rung": None, "explanation_key": "fee.self_pay_no_source"}  # fmt: skip
        if q.kind == "medicare":
            return self._fee_schedule_fee(self.pfs, code, "", "non_facility", 5, "Medicare", None)
        if q.kind == "masshealth":
            return self._fee_schedule_fee(self.mh, code, "", "non_facility", 4, "MassHealth",
                                          None)  # fmt: skip
        pcp = [
            t
            for s in self.reg.sites.values()
            if s.site_type == "primary_care_office" and s.listing_status != "registry_only"
            for t in s.tins
        ]
        if not pcp or not q.networks or code not in self.store.codes:
            return _not_loaded("your primary care office's fee for the referral visit: we do not "
                               "know which office you use, and no primary care offices are in "
                               "our list yet"), None  # fmt: skip
        got = self._group_rate(self._tic_rows(q, pcp, [code], "", self.pos["office_visit"],
                                              "professional"))  # fmt: skip
        if got:
            money, fee = got
            fee.update(group_name=None, group_tin=None)
            fee.pop("by_npi", None)
            fee.pop("npi_count", None)
            return money, fee
        return _not_published(
            self.store,
            q.networks[0],
            "this insurer's rate for a primary care visit",
            "Ask your primary care office what your plan pays for a visit.",
        ), None

    # ------------------------------------------------------------------ items

    def _path_items(self, path: CarePath, q: Req) -> list[Item]:
        answers = q.req.answers
        scope_ok = {"medicare": ("all", "medicare")}.get(q.kind, ("all", "commercial"))
        out: list[Item] = []
        for st in path.steps:
            if st.condition and not _matches(st.condition, answers):
                continue
            tier, rating = st.likelihood_tier, st.appropriateness.rating
            for m in path.tier_modifiers:  # P1 #19: the modified step is the one shown
                if m.step == st.id and _matches(m.when, answers):
                    tier = m.tier
                    if m.appropriateness is not None:
                        rating = m.appropriateness.rating
            if st.no_price:
                continue
            base = {
                "why": st.plain.why,
                "likelihood": tier,
                "tier_basis": tier_basis_for_rating(rating),
                "step_id": st.id,
                "gloss": [g for g in st.glossary if g in self.reg.glossary],
                "learn": [{"label": lm.label, "url": lm.url} for lm in st.learn_more],
                "at": "your_primary_care" if st.layer == 0 and st.kind == "referral"
                else "this_site",
                "path_id": path.id,
                "step_codes": tuple(c.code for c in st.cpts if c.role in ("primary", "alternative")),
                "step_kind": st.kind,
            }  # fmt: skip
            cpts = [c for c in st.cpts if c.payer_scope in scope_ok]
            primaries = 0
            for c in cpts:
                if c.role == "primary":
                    # two primary codes in one step under the same payment (Chat2): the second
                    # gets its own line id instead of colliding on the step id
                    stem = st.id if primaries == 0 else f"{st.id}_{c.code.lower()}"
                    primaries += 1
                    out.append(Item(stem=stem, code=c.code, unit="once", plain=st.plain.name,
                                    tech=st.plain.technical_name, display_mod=c.modifier,
                                    **base))  # fmt: skip
                elif c.role in ("add_on", "guidance"):
                    if c.code in self.per15:
                        out.append(Item(stem=f"{st.id}_sessions", code=c.code,
                                        unit="per_15_minutes",
                                        plain="Later exercise sessions (each 15 minutes)",
                                        tech="Therapeutic exercise", **base))  # fmt: skip
                    else:
                        desc = self.reg.describe(c.code) or c.note or st.plain.technical_name
                        out.append(Item(stem=f"{st.id}_{c.code.lower()}", code=c.code, unit="once",
                                        plain=f"{st.plain.name}: an extra part ({desc})",
                                        tech=desc, **base))  # fmt: skip
            for ai in st.ai_potential:
                for c in ai.cpts:
                    stem = (
                        f"{st.id}_drug_ai" if c.role == "drug" else f"{st.id}_{c.code.lower()}_ai"
                    )
                    out.append(Item(stem=stem, code=c.code, unit="once",
                                    plain="The medicine in the shot" if c.role == "drug"
                                    else "A part the assistant suggests",
                                    tech="Injected medicine (billed as a drug)" if c.role == "drug"
                                    else (self.reg.describe(c.code) or c.code),
                                    ai=True, **{**base, "why": ai.text}))  # fmt: skip
        return out

    def _code_items(self, q: Req) -> list[Item]:
        out = []
        for code in q.req.service_codes:
            svc = self._catalog_names().get(code)
            plain = svc[0] if svc else (self.reg.describe(code) or code)
            tech = svc[1] if svc else (self.reg.describe(code) or code)
            out.append(Item(stem=f"svc_{code.lower()}", code=code, unit="per_15_minutes"
                            if code in self.per15 else "once", plain=plain, tech=tech, why=None,
                            likelihood="certain", tier_basis="picked", step_id=None, gloss=[],
                            learn=[], ai=q.req.picked_by == "assistant"))  # fmt: skip
        return out

    def _catalog_names(self) -> dict[str, tuple[str, str]]:
        from app.quote.catalog import build_catalog

        if not hasattr(self, "_names"):
            names: dict[str, tuple[str, str]] = {}
            for s in build_catalog(self.reg).services:
                for c in s.codes:
                    names.setdefault(c.code, (s.plain_name, s.technical_name))
            self._names = names
        return self._names

    # ------------------------------------------------------------------ lines

    def _line(self, item: Item, line_id: str, codes: list[str], mod: str | None, plain: str,
              tech: str, component: str, confirmed: bool, cell: Json, *, extra_gloss=(),
              list_price: Json | None = None, doctor_fee: Json | None = None,
              price_notes: list[str] | None = None) -> Json:  # fmt: skip
        return {
            "line_id": line_id,
            "tier": "",
            "likelihood": item.likelihood,
            "step_id": item.step_id,
            "codes": codes,
            "modifier": mod or None,
            "plain_name": plain,
            "technical_name": tech,
            "why": item.why,
            "glossary_keys": [
                *item.gloss,
                *[g for g in extra_gloss if g in self.reg.glossary and g not in item.gloss],
            ],  # fmt: skip
            "component": component,
            "component_confirmed": confirmed,
            "unit": item.unit,
            "availability": "offered",
            "cell": cell,
            "list_price": list_price,
            "tier_basis": item.tier_basis,
            "doctor_fee": doctor_fee,
            "ai_suggested": item.ai,
            "in_total": False,
            "elsewhere": [],
            "learn_more": item.learn,
            "price_notes": list(price_notes or []),
            "at": item.at,
            "availability_reason": None,
            "estimate": None,
            "unusual": None,
            "anesthesia_time": None,
            "chain_price_from": None,
            "_item": item,
        }

    def _site_lines(self, site: Site, items: list[Item], q: Req) -> list[Json]:
        lines: list[Json] = []
        billing = self._billing(site)
        two_part = billing in ("hospital_outpatient", "asc")
        for it in items:
            code = it.code
            cls = code_class(code)
            shown = it.display_mod if it.display_mod not in (None, "") else None
            if it.at == "your_primary_care":
                cell, fee = self._referral_cell(it, q)
                lines.append(self._line(
                    it, it.stem, [code], shown, f"{it.plain} (at your primary care office)",
                    it.tech, "professional", True, cell, doctor_fee=fee))  # fmt: skip
                continue
            if cls == "drug":  # the medicine itself: one line, billed by whoever gives it
                if code not in self.store.codes:
                    cell: Json = _not_loaded("the price of the medicine itself (we do not read "
                                             "drug codes from the price files yet)")  # fmt: skip
                elif two_part:
                    cell = self._facility_cell(site, code, q, cls)[0]
                else:
                    cell = self._doctor_cell(site, it, code, "", q, hospital_line=False)[0]
                lines.append(self._line(it, it.stem, [code], shown, it.plain, it.tech, "drug",
                                        False, cell))  # fmt: skip
                continue
            if two_part and cls != "anesthesia":
                cell, confirmed, lp, extra = self._facility_cell(site, code, q, cls)
                who = (
                    "the hospital's fee" if billing == "hospital_outpatient" else "the center's fee"
                )
                lines.append(self._line(
                    it, f"{it.stem}_facility", extra.get("codes", [code]), shown,
                    f"{it.plain}: {who}", f"{it.tech} (facility fee)", "facility", confirmed, cell,
                    extra_gloss=["facility_fee"], list_price=lp,
                    price_notes=extra.get("price_notes", [])))  # fmt: skip
            if two_part and code in self.facility_only:
                continue
            if two_part:
                reading = code in self.reg.pc_tc_codes
                mod = "26" if reading else ""
                line_id = f"{it.stem}_reading" if reading else f"{it.stem}_doctor"
                if cls == "anesthesia":
                    line_id, plain = it.stem, it.plain
                else:
                    plain = f"{it.plain}: the doctor's " + ("reading" if reading else "fee")
                cell, fee, codes = self._doctor_cell(site, it, code, mod, q, hospital_line=True)
                lines.append(self._line(
                    it, line_id, codes, mod or shown, plain, f"{it.tech} (professional fee)",
                    "professional", True, cell, doctor_fee=fee))  # fmt: skip
            else:
                cell, fee, codes = self._doctor_cell(site, it, code, "", q, hospital_line=False)
                tech = it.tech if codes == [code] else f"{it.tech} (urgent care global fee)"
                lines.append(self._line(
                    it, it.stem, codes, shown, it.plain, tech, "professional", True, cell,
                    doctor_fee=fee))  # fmt: skip
        for ln in lines:
            if ln["at"] == "this_site":
                av, why = self._item_avail(site, ln["_item"])
                ln["availability"], ln["availability_reason"] = av, why
                if av == "not_offered":
                    ln["cell"] = None
            cell = ln["cell"]
            if cell is not None and code_class(ln["codes"][0]) == "anesthesia" and (
                self._fs_money(cell) or (cell["kind"] == "money" and cell["prov"]["method"]
                                         == Method.per_unit_x_base_units.value)
            ):  # fmt: skip
                ln["price_notes"].append("price.anesthesia_base_units_only")
            if cell is not None and cell["kind"] == "money" and cell["prov"]["source_id"] in (
                self.posted_by_source
            ) and self.posted_site[site.id].id != site.id:  # fmt: skip
                ln["chain_price_from"] = self.posted_site[site.id].id  # R12
        return lines

    @staticmethod
    def _fs_money(cell: Json) -> bool:
        moneys = [cell] if cell["kind"] == "money" else (
            [cell["a"], cell["b"]] if cell["kind"] == "conflict" else [])  # fmt: skip
        return any(m["prov"]["source_kind"] in FEE_SCHEDULE_KINDS for m in moneys)

    # ------------------------------------------------------------------ offer evidence (R1)

    def offers_code(self, site: Site, code: str) -> bool:
        """Positive evidence the site offers this code (C3 R1, P6): an ``offered`` entry naming
        the code or a service covering it (engine.yaml offered_services); a posted self-pay price
        for it (the site's own, or its chain's, R12); a row for it in the site's own hospital
        file. Never a TiC row: an insurer's file is a contract term, not a claim by the site."""
        key = (site.id, code)
        if key in self._code_offer:
            return self._code_offer[key]
        ok = any(code in o.codes or self._service_covers(o.service, code) for o in site.offered)
        ok = ok or any(code in p.codes for p in self.posted_site[site.id].cash_prices)
        if not ok:
            src = self._site_hospital_source(site)
            first = self.store.by_code.get((src, code)) if src else None
            if first:
                ok = True
                if self.store.recorder is not None:  # the extract keeps the evidence row
                    self.store.recorder.add(first[:1])
        self._code_offer[key] = ok
        return ok

    def _item_avail(self, site: Site, it: Item) -> tuple[str, str | None]:
        """Availability of a step at a site (one answer for every line of the step): site facts
        (X1) first, then code evidence for any of the step's codes. -> (availability, reason)."""
        if it.path_id and it.step_id:
            said = self.facts.step(site.id, it.path_id, it.step_id)
            if said == "offered":
                return "offered", None
            if said == "not_offered":
                return "not_offered", "site_says_not_offered"
        if any(self.offers_code(site, c) for c in (it.step_codes or (it.code,))):
            return "offered", None
        if self._tic_row_for(site, it.code):
            return "unknown", "insurer_lists_rate"
        return "unknown", "no_evidence"

    def _tic_row_for(self, site: Site, code: str) -> bool:
        """P6 wording only: does an insurer file list a rate for this code under the site's
        TINs (any network)? Never evidence that the site offers it."""
        own, linked = self._site_tins(site)
        cid = site.census_id or ""
        for sid in self.tic_sources:
            for t in [*own, *linked]:
                for r in self.store.tic.get((sid, t, code), ()):
                    if t in own or r.names_site(cid):
                        if self.store.recorder is not None:  # the extract keeps this row
                            self.store.recorder.add([r])
                        return True
        return False

    def _service_covers(self, service: str, code: str) -> bool:
        rule = self.cfg["offered_services"].get(service) or {}
        if "classes" in rule and code_class(code) not in rule["classes"]:
            return False
        if "words" in rule:
            desc = self.reg.describe(code) or ""
            if not any(w in desc for w in rule["words"]):
                return False
        if "ranges" in rule:
            return any(lo <= code <= hi and len(code) == len(lo) for lo, hi in rule["ranges"])
        return bool(rule)

    # ------------------------------------------------------------------ finishing lines

    @staticmethod
    def _finish(lines: list[Json]) -> list[Json]:
        for ln in lines:
            cell = ln["cell"]
            kind = cell["kind"] if cell is not None else None
            lk = ln["likelihood"]
            shown = "possible" if lk == "rare" else lk
            ln["tier"] = "not_in_public_data" if kind in NO_NUMBER else shown
            fee = ln["doctor_fee"]
            un = ln["unusual"]
            ln["in_total"] = (
                ln["tier"] in ("certain", "likely")
                and kind == "money"
                and ln["unit"] == "once"
                and not ln["ai_suggested"]
                and ln["availability"] == "offered"  # R2: no evidence -> never summed
                and not (un and un["whole_line"])  # P8
                and (fee is None or (fee["rung"] or 0) in range(1, 7))
            )
        return lines

    @staticmethod
    def _excluded_reason(ln: Json) -> str:
        kind = ln["cell"]["kind"] if ln["cell"] is not None else None
        if ln["ai_suggested"]:
            return "ai_suggested"
        if ln["availability"] == "not_offered":
            return "not_offered_here"
        if ln["availability"] != "offered":
            return "availability_unknown"
        if kind == "conflict":
            return "conflict"
        if kind != "money":
            return "no_dollar_amount"
        if ln["unusual"] and ln["unusual"]["whole_line"]:
            return "unusual"
        if ln["unit"] != "once":
            return "repeats"
        if ln["doctor_fee"] and (ln["doctor_fee"]["rung"] or 0) >= 7:
            return "reference_only"
        return "possible_tier"

    def _you_pay(self, q: Req) -> Json:
        if q.kind == "insurance":
            yp = self.cfg["you_pay"].get(q.payer) or self.cfg["you_pay"]["default"]
            return {"kind": yp["kind"], "note_key": f"youpay.{yp['kind']}",
                    "portal_label": yp.get("portal_label"), "portal_url": yp.get("portal_url")}  # fmt: skip
        kind = {"cash": "cash_full_amount", "medicare": "medicare_20_percent",
                "masshealth": "masshealth_small_or_no_copay"}[q.kind]  # fmt: skip
        return {
            "kind": kind,
            "note_key": f"youpay.{kind}",
            "portal_label": None,
            "portal_url": None,
        }

    def _totals(self, lines: list[Json], steps: list[Json], q: Req,
                fresh: Callable[[str], Freshness]) -> Json:  # fmt: skip
        summed = [ln for ln in lines if ln["in_total"]]
        likely = None
        if summed:
            provs = [p for ln in summed for p in (ln["cell"]["prov"], ln["cell"].get("prov_high"))
                     if p]  # fmt: skip
            f = [fresh(p["source_id"]) for p in provs]
            likely = {
                "low": round(sum(ln["cell"]["low"] for ln in summed), 2),
                "high": round(sum(ln["cell"]["high"] for ln in summed), 2),
                "line_ids": [ln["line_id"] for ln in summed],
                "includes_estimate": any(
                    ln["cell"]["prov"]["method"] == Method.estimate_peer_range.value
                    for ln in summed
                ),
                "includes_late_source": any(x.late_to_refresh for x in f),
                "includes_stale_source": any(x.stale_on_our_side for x in f),
            }
        partial = any(
            ln["likelihood"] in ("certain", "likely")
            and ln["availability"] != "not_offered"
            and not ln["in_total"]
            and not ln["ai_suggested"]
            for ln in lines
        )
        expected = [st for st in steps if st["_expected"]]
        ranked = [st["rank_value"] for st in expected if st["rank_value"] is not None]
        maybe = [
            st for st in steps
            if st["likelihood"] in ("possible", "rare") and not st["_ai"]
            and st["availability"] == "offered" and st["figure"] in ("own", "estimate")
        ]  # fmt: skip
        return {
            "likely": likely,
            "complete": not partial,
            "missing": sum(1 for st in steps if st["missing"]),
            "excluded": [
                {"line_id": ln["line_id"], "reason": self._excluded_reason(ln)}
                for ln in lines
                if not ln["in_total"]
            ],
            "you_pay": self._you_pay(q),
            "comparable": round(sum(ranked), 2) if ranked else None,
            "real_steps": sum(1 for st in expected if st["figure"] == "own"),
            "might_add": {
                "low": round(min(st["low"] for st in maybe), 2),
                "high": round(sum(st["high"] for st in maybe), 2),
                "step_keys": [st["key"] for st in maybe],
            } if maybe else None,
        }  # fmt: skip

    # ------------------------------------------------------------------ peers (R4, P5, P8, X2)

    def _paykey(self, q: Req) -> tuple:
        return (q.kind, q.payer, q.product, tuple(q.networks))

    @staticmethod
    def _pmod(ln: Json) -> str:
        """The pricing modifier of a line (26 = a reading; display-only modifiers price as none)."""
        return "26" if ln["modifier"] == "26" else ""

    @staticmethod
    def _group(r: Row) -> str:
        """X2: peers are counted by distinct billing group: the TiC billing TIN, or the file."""
        if r.source_kind == "insurer_tic":
            return f"tin:{r.tin}@{r.source_id}"  # one group per TIN per network file
        if r.source_kind in FEE_SCHEDULE_KINDS:
            return f"fs:{r.source_id}"
        return f"file:{r.source_id}"

    def _entries(self, ln: Json) -> list[tuple[float, str, Any]]:
        """(value, group, row or posted provenance) for each real price behind a line: no
        estimate, no reference-only number, no conflict."""
        cell = ln["cell"]
        if cell is None or cell["kind"] != "money" or cell["basis"] == "estimate":
            return []
        fee = ln["doctor_fee"]
        if fee and (fee["rung"] or 0) >= 7:
            return []
        if "_posted" in cell:
            return [cell["_posted"]]
        rows = cell.get("_m", ([],))[0]
        return [(v, self._group(r), r) for v, r in rows]

    def _line_stats(self, code: str, q: Req) -> dict[str, dict[tuple[str, str], list]]:
        """Every quotable site's real prices for one code under this payment, per line
        (component, pricing modifier). Computed once per (code, payment) over the whole
        registry: peers never depend on which sites a request shows."""
        key = (code, self._paykey(q))
        if key not in self._stats:
            it = Item(stem="peer", code=code, unit="once", plain=code, tech=code, why=None,
                      likelihood="certain", tier_basis="picked", step_id=None, gloss=[],
                      learn=[])  # fmt: skip
            out: dict[str, dict[tuple[str, str], list]] = {}
            for s in self.reg.sites.values():
                if s.listing_status == "registry_only":
                    continue
                per: dict[tuple[str, str], list] = {}
                for ln in self._site_lines(s, [it], q):
                    ents = self._entries(ln)
                    if ents:
                        per[(ln["component"], self._pmod(ln))] = ents
                if per:
                    out[s.id] = per
            self._stats[key] = out
        return self._stats[key]

    def _peers(self, site: Site, code: str, comp: str, pmod: str, q: Req, *, estimate: bool,
               network: str | None = None) -> tuple[list[tuple[float, Any]], str]:  # fmt: skip
        """X2 peer set for one line at one site: same code, modifier, component, payer and plan
        product (the request's network files), sites of the same kind (and billing type, unless
        engine.yaml turns it off) that offer the code; one value per distinct billing group (the
        group's lower-median row), the site's own groups left out. ``estimate``: fee-schedule
        groups are left out and one source kind is kept (a Money cites one kind). ``network``
        (O audit): only rows of that network file (``hospital_file`` for hospital files), so
        networks of one payer with different price levels are never pooled. A children-only site
        is its own peer kind (O F4). Cached: it depends on the data and the payment only."""
        ck = (site.id, code, comp, pmod, self._paykey(q), estimate, network)
        hit = self._peer_cache.get(ck)
        if hit is not None:
            return hit
        out = self._peers_uncached(site, code, comp, pmod, q, estimate=estimate, network=network)
        self._peer_cache[ck] = out
        return out

    def _peers_uncached(self, site: Site, code: str, comp: str, pmod: str, q: Req, *,
                        estimate: bool, network: str | None) -> tuple[list, str]:  # fmt: skip
        stats = self._line_stats(code, q)
        mine = {g for _, g, _ in stats.get(site.id, {}).get((comp, pmod), [])}
        kind, bill = self._kind(site), self._billing(site)
        same_bill = self.peer_cfg["key_includes_billing"]
        cands = []
        for sid in sorted(stats):
            if sid == site.id:
                continue
            s = self.reg.sites[sid]
            if self._kind(s) != kind or (same_bill and self._billing(s) != bill):
                continue
            if s.children_only != site.children_only:
                continue
            ents = stats[sid].get((comp, pmod))
            if ents and network is not None:
                ents = [e for e in ents if self._net(e[2]) == network]
            if ents and self.offers_code(s, code):
                cands.append((s, ents))

        def groups(cs) -> dict[str, tuple[float, Any]]:
            out: dict[str, tuple[float, Any]] = {}
            for _, ents in cs:
                by: dict[str, list] = defaultdict(list)
                for v, g, ref in ents:
                    if g in mine or g in out or (estimate and g.startswith("fs:")):
                        continue
                    by[g].append((v, ref))
                for g, vs in by.items():
                    vs.sort(key=lambda t: t[0])
                    out[g] = vs[(len(vs) - 1) // 2]
            return out

        scope = "same_kind"
        got = groups(cands)
        if self.peer_cfg["mode"] == "same_system_then_kind" and site.system_id:
            sys = groups([c for c in cands if c[0].system_id == site.system_id])
            if len(sys) >= self.peer_cfg["system_min_groups"]:
                got, scope = sys, "same_system"
        vals = list(got.values())
        if estimate and vals:  # one source kind per Money: the kind most groups come from
            kinds: dict[str, int] = defaultdict(int)
            for _, ref in vals:
                kinds[self._ref_kind(ref)] += 1
            top = min(kinds, key=lambda k: (-kinds[k], k))
            vals = [t for t in vals if self._ref_kind(t[1]) == top]
        return sorted(vals, key=lambda t: (t[0], self._ref_id(t[1]))), scope

    @staticmethod
    def _net(ref: Any) -> str:
        """The network a price belongs to: its TiC file, or the hospital file / posted page."""
        if isinstance(ref, Row):
            return ref.source_id if ref.source_kind == "insurer_tic" else "hospital_file"
        return "posted"

    @staticmethod
    def _ref_kind(ref: Any) -> str:
        return ref.source_kind if isinstance(ref, Row) else ref["source_kind"]

    @staticmethod
    def _ref_id(ref: Any) -> str:
        return ref.uid if isinstance(ref, Row) else ref["row_ref"]

    def _est_prov(self, ref: Any, q: Req) -> Json:
        payer = q.payer if q.kind == "insurance" else None
        if isinstance(ref, Row):
            p = self.store.prov_dict(ref, PriceBasis.estimate, method=Method.estimate_peer_range)
        else:
            p = dict(ref)
        p["method"] = Method.estimate_peer_range.value
        p["payer_id"] = payer
        return p

    def _gate(self, site: Site, ln: Json, q: Req) -> None:
        """P8: each row is compared with the peer median of its own network (O audit: never a
        pooled median); rows outside [low, high] x that median are set aside (cited, never
        summed); every row outside -> the whole line is unusual."""
        cell = ln["cell"]
        if cell is None or cell["kind"] != "money" or cell["basis"] in ("fee_schedule", "estimate"):
            return
        if ln["at"] != "this_site" or not self._entries(ln):
            return
        lo_x, hi_x = float(self.out_cfg["low"]), float(self.out_cfg["high"])
        meds: dict[str, tuple[float, int] | None] = {}

        def median_for(net: str) -> tuple[float, int] | None:
            if net not in meds:
                peers, _ = self._peers(site, ln["codes"][0], ln["component"], self._pmod(ln), q,
                                       estimate=False, network=net)  # fmt: skip
                m = _lower_median([v for v, _ in peers]) if peers else 0.0
                ok = len(peers) >= self.out_cfg["min_groups"] and m > 0
                meds[net] = (m, len(peers)) if ok else None
            return meds[net]

        if "_posted" in cell:
            v, _, ref = cell["_posted"]
            got = median_for(self._net(ref))
            if got and not lo_x * got[0] <= v <= hi_x * got[0]:
                ln["unusual"] = {"peer_median": got[0], "n_groups": got[1], "whole_line": True,
                                 "set_aside": []}  # fmt: skip
            return
        rows, value, basis, method = cell["_m"]
        kept, out, first = [], [], None
        for v, r in rows:
            got = median_for(self._net(r))
            if got and not lo_x * got[0] <= v <= hi_x * got[0]:
                out.append(r)
                first = first or got
            else:
                kept.append(r)
        if not out:
            return
        if not kept:
            ln["unusual"] = {"peer_median": first[0], "n_groups": first[1], "whole_line": True,
                             "set_aside": []}  # fmt: skip
            return
        ln["cell"] = self._money(kept, value, basis, method)
        ln["unusual"] = {
            "peer_median": first[0], "n_groups": first[1], "whole_line": False,
            "set_aside": [self._money(out, value, basis, method)],
        }  # fmt: skip

    def _estimate(self, site: Site, ln: Json, q: Req) -> None:
        """P5 (rung 6): a missing line of a step this site offers, from the same line's real
        prices at >= min_groups peer groups (same kind, same payer): p25-p75, both ends cited.
        Fewer groups -> no estimate (the Gap stays). A published %-of-charges term stays."""
        cell = ln["cell"]
        if q.kind not in ("insurance", "cash") or ln["at"] != "this_site" or cell is None:
            return
        if ln["availability"] != "offered" or ln["ai_suggested"] or ln["unit"] != "once":
            return
        fee = ln["doctor_fee"]
        reference = cell["kind"] == "money" and fee is not None and (fee["rung"] or 0) >= 7
        if cell["kind"] not in NO_NUMBER and not reference:
            return
        # O audit: per network, never pooled. Each network with >= min_groups groups gives its
        # p25-p75; with no network named, the estimate spans them (low = the lowest p25, high = the
        # highest p75, median = the median of the network medians), so a plan that pays a third
        # of another never hides inside a pooled median. Insurer files first; a hospital-file
        # range only when no insurer network has enough groups (one source kind per Money).
        nets: list[str | None] = [*q.networks, "hospital_file"] if q.kind == "insurance" else [None]
        per: list[tuple[tuple, tuple, float, int, str]] = []
        for net in nets:
            peers, scope = self._peers(site, ln["codes"][0], ln["component"], self._pmod(ln), q,
                                       estimate=True, network=net)  # fmt: skip
            n = len(peers)
            if n < self.peer_cfg["min_groups"]:
                continue
            per.append((peers[_rank_pos(n, self.peer_cfg["low_percentile"])],
                        peers[_rank_pos(n, self.peer_cfg["high_percentile"])],
                        peers[(n - 1) // 2][0], n, scope))  # fmt: skip
        if any(self._net(p[0][1]) != "hospital_file" for p in per):
            per = [p for p in per if self._net(p[0][1]) != "hospital_file"]
        kinds = {self._ref_kind(p[0][1]) for p in per} | {self._ref_kind(p[1][1]) for p in per}
        if not per or len(kinds) > 1:
            return
        lo = min((p[0] for p in per), key=lambda t: (t[0], self._ref_id(t[1])))
        hi = max((p[1] for p in per), key=lambda t: (t[0], self._ref_id(t[1])))
        med = _lower_median([p[2] for p in per])
        n = sum(p[3] for p in per)
        scope = per[0][4]
        money: Json = {"kind": "money", "low": lo[0], "high": hi[0], "basis": "estimate",
                       "prov": self._est_prov(lo[1], q)}  # fmt: skip
        if hi[0] > lo[0]:
            money["prov_high"] = self._est_prov(hi[1], q)
        ln["cell"] = money
        ln["elsewhere"] = []
        ln["estimate"] = {
            "low": lo[0], "high": hi[0], "median": med, "n_groups": n, "kind": self._kind(site),
            "scope": scope, "payer_id": q.payer if q.kind == "insurance" else None,
        }  # fmt: skip
        if fee is not None:
            ln["doctor_fee"] = {"rung": 6, "explanation_key": "fee.rung_6_estimate"}

    @staticmethod
    def _central(ln: Json) -> float:
        """A line's neutral figure for ranking: the peer median for an estimate, else the
        lower-median row behind the cell (after the P8 check), never the minimum row (R5)."""
        if ln["estimate"] is not None:
            return ln["estimate"]["median"]
        cell = ln["cell"]
        if "_posted" in cell:
            return cell["_posted"][0]
        if "_m" in cell:
            return _lower_median([v for v, _ in cell["_m"][0]])
        return (cell["low"] + cell["high"]) / 2

    @staticmethod
    def _counts(ln: Json) -> bool:
        """A line whose number can stand in a step figure."""
        cell, fee, un = ln["cell"], ln["doctor_fee"], ln["unusual"]
        return (
            cell is not None and cell["kind"] == "money"
            and not (un and un["whole_line"])
            and not (fee and (fee["rung"] or 0) >= 7)
        )  # fmt: skip

    # ------------------------------------------------------------------ admission (R8)

    def _admits(self, site: Site, path: CarePath | None, areas: set[str]) -> bool:
        """A site enters a path when it offers the entry visit (layer 1) or the core procedure
        (a layer-2 procedure that is certain or likely) by the offer rules; with no evidence either
        way, when its kind may do that kind of step (engine.yaml admission_step_kinds)."""
        if not self.reg.area_ok(site, areas):
            return False
        if path is None:
            return True
        keys = [st for st in path.steps if not st.no_price and (
            (st.layer == 1 and st.kind == "visit")
            or (st.layer == 2 and st.kind == "procedure"
                and st.likelihood_tier in ("certain", "likely"))
        )]  # fmt: skip
        allowed = set(self.cfg["admission_step_kinds"].get(self._kind(site), ()))
        open_ = []
        for st in keys:
            said = self.facts.step(site.id, path.id, st.id)
            if said == "offered":
                return True
            if said == "not_offered":
                continue
            codes = [c.code for c in st.cpts if c.role in ("primary", "alternative")]
            if any(self.offers_code(site, c) for c in codes):
                return True
            open_.append(st)
        return any(st.kind in allowed for st in open_)

    def _admitted(self, path: CarePath | None, areas: set[str]) -> list[str]:
        key = (path.id if path else None, tuple(sorted(areas)))
        if key not in self._admitted_cache:
            self._admitted_cache[key] = [
                s.id for s in sorted(self.reg.sites.values(), key=lambda s: s.id)
                if s.listing_status != "registry_only" and not s.children_only
                and self._admits(s, path, areas)
            ]  # fmt: skip
        return self._admitted_cache[key]

    # ------------------------------------------------------------------ steps (P1, P3, P4)

    @staticmethod
    def _step_key(ln: Json) -> str:
        return ln["step_id"] or ",".join(ln["codes"])

    def _step_pool(self, key: str, items: list[Item], admitted: list[str], q: Req,
                   path_id: str | None) -> Json:  # fmt: skip
        """P4: one step's price at every admitted site that offers it (its own real prices after
        the P8 check, no estimates), one value per distinct set of billing groups (a chain counts
        once). -> {"range": PeerRange or None, "priced": any site has a figure}."""
        ck = (path_id, key, tuple(it.code for it in items), tuple(admitted), self._paykey(q))
        if ck in self._universe:
            return self._universe[ck]
        vals: dict[frozenset, tuple[float, str]] = {}
        for sid in admitted:
            site = self.reg.sites[sid]
            lines = [ln for ln in self._site_lines(site, items, q)
                     if ln["unit"] == "once" and not ln["ai_suggested"]]  # fmt: skip
            if not lines or any(ln["availability"] != "offered" for ln in lines):
                continue
            for ln in lines:
                self._gate(site, ln, q)
            if not all(self._counts(ln) for ln in lines):
                continue
            sig = frozenset(g for ln in lines for _, g, _ in self._entries(ln)) or frozenset(
                {f"site:{sid}"})  # fmt: skip
            if sig not in vals:
                vals[sig] = (round(sum(self._central(ln) for ln in lines), 2), sid)
        got = sorted(vals.values())
        n = len(got)
        rng = None
        if n >= self.peer_cfg["min_groups"]:
            lo = got[_rank_pos(n, self.peer_cfg["low_percentile"])][0]
            hi = got[_rank_pos(n, self.peer_cfg["high_percentile"])][0]
            rng = {"low": lo, "high": hi, "median": got[(n - 1) // 2][0], "n_groups": n,
                   "kind": None, "scope": "same_kind",
                   "payer_id": q.payer if q.kind == "insurance" else None}  # fmt: skip
        out = {"range": rng, "priced": n > 0}
        self._universe[ck] = out
        return out

    def _steps(self, site: Site, lines: list[Json], items: list[Item], admitted: list[str],
               q: Req) -> list[Json]:  # fmt: skip
        """One summary per step (P3 map, P4 elsewhere, I7 missing per step)."""
        groups: dict[str, list[Json]] = {}
        for ln in lines:
            groups.setdefault(self._step_key(ln), []).append(ln)
        by_key: dict[str, list[Item]] = defaultdict(list)
        for it in items:
            by_key[it.step_id or it.code].append(it)
        out = []
        for key, lns in groups.items():
            first = lns[0]
            ai = all(ln["ai_suggested"] for ln in lns)
            avail = "offered" if first["at"] != "this_site" else first["availability"]
            priced = [ln for ln in lns if ln["unit"] == "once" and (ai or not ln["ai_suggested"])]
            expected = first["likelihood"] in ("certain", "likely") and not ai
            pool = self._step_pool(key, [it for it in by_key[key] if not it.ai], admitted, q,
                                   first["_item"].path_id) if not ai else {"range": None,
                                                                          "priced": False}  # fmt: skip
            figure, low, high, rank, rng = "none", None, None, None, None
            if avail == "offered":
                if priced and all(self._counts(ln) for ln in priced):
                    figure = "estimate" if any(ln["estimate"] for ln in priced) else "own"
                    low = round(sum(ln["cell"]["low"] for ln in priced), 2)
                    high = round(sum(ln["cell"]["high"] for ln in priced), 2)
                    rank = round(sum(self._central(ln) for ln in priced), 2)
            elif pool["range"] is not None:
                rng = pool["range"]
                figure, low, high, rank = "elsewhere", rng["low"], rng["high"], rng["median"]
            missing = expected and figure == "none" and pool["priced"]
            out.append({
                "key": key, "step_id": first["step_id"], "likelihood": first["likelihood"],
                "availability": avail, "figure": figure, "low": low, "high": high,
                "rank_value": rank if expected and figure != "none" else None,
                "estimated": any(ln["estimate"] for ln in lns),
                "unusual": any(ln["unusual"] for ln in lns),
                "in_total": bool(priced) and all(ln["in_total"] for ln in priced),
                "missing": missing, "line_ids": [ln["line_id"] for ln in lns],
                "elsewhere": rng, "_expected": expected, "_ai": ai,
            })  # fmt: skip
        return out

    def _anesthesia_time(self, ln: Json) -> None:
        """Item 12: 'with typical time, about $Y' = base-units fee x (base + minutes/15) / base."""
        t = self.anes_time.get(ln["codes"][0])
        cell = ln["cell"]
        if not t or "price.anesthesia_base_units_only" not in ln["price_notes"] or (
            cell is None or cell["kind"] != "money"
        ):  # fmt: skip
            return
        f = (t["base_units"] + t["minutes"] / 15) / t["base_units"]
        ln["anesthesia_time"] = {
            "minutes": t["minutes"], "base_units": t["base_units"],
            "low": round(cell["low"] * f, 2), "high": round(cell["high"] * f, 2),
            "source": t["source"],
        }  # fmt: skip

    @staticmethod
    def _load_anesthesia_time(times: Any, bases: Any) -> dict[str, Json]:
        """code -> {minutes, base_units, source}: A5's CMS physician time + our base units."""
        if not (times.exists() and bases.exists()):
            return {}
        import yaml

        t = yaml.safe_load(times.read_text()) or {}
        b = yaml.safe_load(bases.read_text()) or {}
        src = t.get("source") or {}
        label = f"CMS {src.get('release', 'physician time file')} ({src.get('member', '')})"
        out = {}
        for code, units in (b.get("base_units") or {}).items():
            code = str(code).zfill(5)
            rec = (t.get("times") or {}).get(code) or (t.get("times") or {}).get(int(code))
            if not rec or rec.get("kind") != "anesthesia" or not rec.get("typical_anesthesia_min"):
                continue
            out[code] = {"minutes": float(rec["typical_anesthesia_min"]),
                         "base_units": float(units), "source": label}  # fmt: skip
        return out

    def _other_payers(self, src: str, lines: list[Json], q: Req) -> list[Json]:
        """Range bar on each certain/likely hospital facility line: every mapped payer's rate in
        the hospital's own file, plus its cash price."""
        out = []
        for line in lines:
            if line["component"] != "facility" or line["likelihood"] not in ("certain", "likely"):
                continue
            code = line["codes"][0]
            rows = [
                r
                for pid in sorted(self.reg.payer_labels)
                for r in self.store.get("hospital", (src, code, pid))
                if r.row_kind == "payer_rate" and r.modifiers == ""
                and r.component in ("facility", "unknown") and r.amount is not None
            ]  # fmt: skip
            groups: dict[str, list[Row]] = defaultdict(list)
            for r in rows:
                groups[r.payer_id or ""].append(r)
            points = []
            for pid, rs in groups.items():
                products = {p for r in rs for p in r.product.split("/") if p}
                points.append({
                    "payer_id": pid,
                    "label": self.reg.payer_labels.get(pid, pid),
                    "product": next(iter(products)) if len(products) == 1
                    and products <= self.reg.products else None,
                    "money": self._money(rs, lambda r: r.amount, PriceBasis.negotiated),
                })  # fmt: skip
            if not points:
                continue
            points.sort(key=lambda p: (p["money"]["low"], p["label"]))
            cash = self._money(self._cash_rows(src, code), lambda r: r.discounted_cash,
                               PriceBasis.discounted_cash)  # fmt: skip
            out.append({
                "line_id": line["line_id"],
                "code": code,
                "points": points,
                "cash": cash,
                "yours": "in_points" if any(p["payer_id"] == q.payer for p in points)
                else "not_in_points",
            })  # fmt: skip
        return out

    def _summary(self, site: Site, price_source_id: str | None, price_label: str) -> Json:
        hours = site.hours
        if hours is None:
            label = "unknown"
        elif hours.may_close_early:
            label = "may_close_early"
        else:
            label = "posted_hours"
        a = site.address
        return {
            "site_id": site.id,
            "name": site.name,
            "site_type": site.site_type,
            "system_id": site.system_id,
            "coords": site.coords.model_dump(mode="json"),
            "address_line": f"{a.street}, {a.city}, {a.state} {a.zip}",
            "phone": site.phone,
            "billing_type": site.billing_type,
            "booking": [b.model_dump(mode="json") for b in site.booking],
            "portal_links": [p.model_dump(mode="json") for p in site.portal_links],
            "hours": hours.model_dump(mode="json") if hours else None,
            "hours_label": label,
            "price_label": price_label,
            "price_source_id": price_source_id,
            "listing_status": site.listing_status,
            "service_areas": list(site.service_areas),
            "kind": self._kind(site),
            "chain_id": self.chain_of.get(site.id),
            "children_only": site.children_only,
            "data_notices": self.reg.data_notices.get(price_source_id or "", []),
        }

    def _price_source(self, site: Site, q: Req, lines: list[Json]) -> tuple[str | None, str]:
        src = self._site_hospital_source(site)
        if src:
            return src, "price_file"
        if q.kind == "cash":
            posted = q.posted.get(site.id)
            return (posted.source_id, "posted_price") if posted else (None, "price_on_request")
        if q.kind == "insurance":
            return (q.networks[0], "price_file") if q.networks else (None, "price_on_request")
        fs = self.pfs if q.kind == "medicare" else self.mh
        if not fs:
            return None, "price_on_request"
        cited = [  # the schedule file behind the site's first fee-schedule number
            ln["cell"]["prov"]["source_id"] for ln in lines
            if ln["cell"]["kind"] == "money" and ln["cell"]["prov"]["source_id"] in fs
        ]  # fmt: skip
        return (cited[0] if cited else fs[0]), "price_file"

    # ------------------------------------------------------------------ freshness

    def _meta(self, sid: str, q: Req) -> SourceMeta:
        return self.store.sources.get(sid) or self.posted_by_source[sid]

    def freshness(self, m: SourceMeta, as_of: date) -> Freshness:
        rule, ours = m.source_rule, m.our_rule
        if not rule:
            rule, ours = DEFAULT_RULES[m.source_kind]
        return Freshness.compute(
            as_of=as_of,
            source_rule=rule,  # type: ignore[arg-type]
            last_updated=date.fromisoformat(m.last_updated) if m.last_updated else None,
            our_rule=ours,  # type: ignore[arg-type]
            fetched_at=date.fromisoformat(m.fetched_at),
            expected_by=date.fromisoformat(m.expected_by) if m.expected_by else None,
            our_refresh_due=date.fromisoformat(m.our_refresh_due) if m.our_refresh_due else None,
        )

    # ------------------------------------------------------------------ assembly

    def _context(self, req: QuoteRequest, as_of: date) -> Req:
        pay = req.payment
        if isinstance(pay, InsurancePayment):
            if pay.payer_id not in self.reg.payer_labels:
                raise ValueError(f"unknown payer {pay.payer_id} (payer_aliases.yaml)")
            if pay.product not in self.reg.products:
                raise ValueError(f"unknown product {pay.product}")
            nets = [
                n for n in self.reg.networks_for(pay.payer_id, pay.product, pay.network)
                if n in self.store.sources
            ]  # fmt: skip
            if pay.network is not None and not nets:
                raise ValueError(f"no loaded TiC network {pay.network!r} for {pay.payer_id}")
            return Req(req, "insurance", pay.payer_id, pay.product, nets, as_of, self.posted)
        if isinstance(pay, MedicarePayment):
            return Req(req, "medicare", "MEDICARE", "", [], as_of, self.posted)
        if isinstance(pay, MassHealthPayment):
            return Req(req, "masshealth", "MASSHEALTH", "", [], as_of, self.posted)
        assert isinstance(pay, CashPayment)
        return Req(req, "cash", None, "", [], as_of, self.posted)

    def quote(self, req: QuoteRequest, as_of: date) -> QuoteResponse:
        q = self._context(req, as_of)
        path = self.reg.paths.get(req.care_path_id) if req.care_path_id else None
        if req.care_path_id and path is None:
            raise ValueError(f"unknown care path {req.care_path_id}")
        if path is not None:
            items, areas = self._path_items(path, q), self.reg.path_areas(path)
        else:
            items = self._code_items(q)
            areas = set().union(*(self.reg.code_areas(c) for c in req.service_codes))
            areas = areas or {"ortho", "skin", "gi", "urgent_care"}
        quotable = {
            sid: s for sid, s in self.reg.sites.items() if s.listing_status != "registry_only"
        }
        named = req.site_ids is not None
        admitted = self._admitted(path, areas)
        cands, without = [], []
        if named:
            for sid in req.site_ids or []:
                site = quotable.get(sid)
                if site is None:
                    raise ValueError(f"unknown or unquotable site {sid}")
                if items and (sid in admitted or (
                    site.children_only and self._admits(site, path, areas))):  # fmt: skip
                    cands.append(site)  # D27: a children-only site only when named
                else:
                    without.append(sid)
        else:
            ok = set(admitted) if items else set()
            cands = [quotable[sid] for sid in admitted] if items else []
            without = sorted(sid for sid, s in quotable.items()
                             if sid not in ok and not s.children_only)  # fmt: skip
        origin = req.near if req.near is not None else self.origin
        dist = {s.id: round(_km(origin, s), 2) for s in cands}
        if req.near is not None:  # C2: the max_sites closest admitted sites
            cands = sorted(cands, key=lambda s: (dist[s.id], s.id))[: req.max_sites]

        fresh_cache: dict[str, Freshness] = {}

        def fresh(sid: str) -> Freshness:
            if sid not in fresh_cache:
                fresh_cache[sid] = self.freshness(self._meta(sid, q), as_of)
            return fresh_cache[sid]

        built = [self._site_quote(site, items, admitted, q, fresh) for site in cands]
        for sq in built:
            sq["distance_km"] = dist[sq["site"]["site_id"]]
        if req.near is not None or named:
            ordering = "rank"

            def order(sq: Json) -> tuple:
                h = sq["headline"]
                return (h["missing"], h["comparable"] if h["comparable"] is not None else math.inf,
                        sq["distance_km"] if req.near is not None else 0.0,
                        -h["real_steps"], sq["site"]["name"], sq["site"]["site_id"])  # fmt: skip
        else:
            ordering = "kind_then_distance"  # P7: no "best value overall"

            def order(sq: Json) -> tuple:
                return (KIND_ORDER[sq["site"]["kind"]], sq["distance_km"], sq["site"]["name"],
                        sq["site"]["site_id"])  # fmt: skip

        built.sort(key=order)
        self._elsewhere(built)
        spreads = self._chain_spreads(built)
        if req.near is None and not named:  # item 9: summaries for all, receipts for the first N
            for sq in built[req.full_receipts :]:
                sq["receipt"] = None
                sq["other_payers"] = []
        used = self._used_sources(built)
        sources = {}
        for sid in sorted(used):
            m = self._meta(sid, q)
            sources[sid] = {
                "source_kind": m.source_kind,
                "publisher": m.publisher,
                "freshness": fresh(sid).model_dump(mode="json"),
            }
        notices = []
        if path is not None and path.review.status != "approved":
            notices.append("care_path_draft")
        if self.store.version.tic_release is None:
            notices.append("tic_not_loaded")
        if any(fresh(s).late_to_refresh for s in used):
            notices.append("late_to_refresh_sources")
        if any(fresh(s).stale_on_our_side for s in used):
            notices.append("stale_on_our_side_sources")
        if q.kind == "masshealth":
            notices.append("masshealth_aco_may_differ")
        if q.kind == "medicare":
            notices.append("medicare_advantage_is_insurance")
        if spreads:
            notices.append("chain_price_spread")
        body = {
            "payment": req.payment.model_dump(mode="json"),
            "payment_label": self._payment_label(q),
            "care_path": None if path is None else {
                "id": path.id,
                "version": path.version,
                "title": path.title.en,
                "review_status": path.review.status,
            },
            "service_codes": list(req.service_codes),
            "picked_by": req.picked_by,
            "as_of": as_of.isoformat(),
            "data_version": {
                "build_id": self.store.version.build_id,
                "build_date": self.store.version.build_date,
                "tic_release": self.store.version.tic_release,
                "sites_version": self.reg.sites_version,
                "care_paths_version": path.version if path else None,
            },
            "sources": sources,
            "sites": built,
            "ordering": ordering,
            "origin": {"lat": origin.lat, "lon": origin.lon},
            "chain_spreads": spreads,
            "sites_without_service": without,
            "copy_keys": COPY_KEYS if path is not None else [],
            "notices": notices,
        }  # fmt: skip
        return QuoteResponse.model_validate(_public(body))

    def _payment_label(self, q: Req) -> Json:
        if q.kind == "insurance":
            name = self.reg.payer_labels.get(q.payer or "", q.payer or "")
            return {"en": f"{name} {q.product}", "zh": f"{name} {q.product}"}
        return dict(self.cfg["payment_labels"][q.kind])

    def _site_quote(self, site: Site, items: list[Item], admitted: list[str], q: Req,
                    fresh: Callable[[str], Freshness]) -> Json:  # fmt: skip
        lines = self._site_lines(site, items, q)
        for ln in lines:  # P8 first (on the site's own rows), then P5 for what is still missing
            self._gate(site, ln, q)
        for ln in lines:
            self._estimate(site, ln, q)
        lines = self._finish(lines)
        for ln in lines:
            self._anesthesia_time(ln)
        steps = self._steps(site, lines, items, admitted, q)
        src, label = self._price_source(site, q, lines)
        hs = self._site_hospital_source(site)
        totals = self._totals(lines, steps, q, fresh)
        t = totals
        return {
            "site": self._summary(site, src, label),
            "headline": {
                "likely_low": t["likely"]["low"] if t["likely"] else None,
                "likely_high": t["likely"]["high"] if t["likely"] else None,
                "includes_estimate": bool(t["likely"] and t["likely"]["includes_estimate"]),
                "complete": t["complete"],
                "missing": t["missing"],
                "comparable": t["comparable"],
                "real_steps": t["real_steps"],
                "might_add": t["might_add"],
            },  # fmt: skip
            "steps": steps,
            "distance_km": None,
            "receipt": {"lines": lines, "totals": totals},
            "other_payers": self._other_payers(hs, lines, q) if hs else [],
        }

    def _elsewhere(self, site_quotes: list[Json]) -> None:
        """'Available elsewhere': a line with no number here lists the cheapest other sites in
        this quote that offer the same part of the same step and have a real dollar amount."""
        offers: dict[tuple, list[tuple[float, Json, Json]]] = defaultdict(list)
        for sq in site_quotes:
            for ln in sq["receipt"]["lines"]:
                if not self._counts(ln) or ln["ai_suggested"] or ln["estimate"]:
                    continue  # a reference-only, unusual or estimated number is not an offer
                if ln["at"] == "this_site" and ln["availability"] == "offered":
                    k = (self._step_key(ln), ln["component"], ln["codes"][0], ln["modifier"])
                    offers[k].append((ln["cell"]["low"], sq["site"], ln["cell"]))
        n = self.cfg["elsewhere_max"]
        for sq in site_quotes:
            me = sq["site"]["site_id"]
            for ln in sq["receipt"]["lines"]:
                cell = ln["cell"]
                if cell is not None and cell["kind"] not in NO_NUMBER or ln["at"] != "this_site":
                    continue
                k = (self._step_key(ln), ln["component"], ln["codes"][0], ln["modifier"])
                opts = sorted((o for o in offers.get(k, []) if o[1]["site_id"] != me),
                              key=lambda o: (o[0], o[1]["site_id"]))[:n]  # fmt: skip
                ln["elsewhere"] = [
                    {"site_id": s["site_id"], "site_name": s["name"], "lat": s["coords"]["lat"],
                     "lon": s["coords"]["lon"], "cell": cell}
                    for _, s, cell in opts
                ]  # fmt: skip

    def _chain_spreads(self, site_quotes: list[Json]) -> list[Json]:
        """R12: within one chain, the same line under the same payer more than chain_spread_max
        apart (each site's neutral figure for the line)."""
        own = set(self.cfg.get("chain_ownerships") or [])
        by: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
        for sq in site_quotes:
            site = self.reg.sites[sq["site"]["site_id"]]
            chain = self.chain_of.get(site.id) or (
                _slug(site.operator) if site.ownership in own else None)  # fmt: skip
            if not chain:
                continue
            for ln in sq["receipt"]["lines"]:
                if ln["at"] == "this_site" and self._counts(ln) and not ln["estimate"]:
                    k = (chain, f"{self._step_key(ln)}/{ln['component']}/{ln['codes'][0]}/"
                         f"{ln['modifier'] or ''}")  # fmt: skip
                    by[k].append((round(self._central(ln), 2), site.id))
        out = []
        for (chain, key), vals in sorted(by.items()):
            lo, hi = min(vals), max(vals)
            if lo[0] > 0 and hi[0] / lo[0] > float(self.cfg["chain_spread_max"]):
                out.append({"chain_id": chain, "key": key, "low_site_id": lo[1], "low": lo[0],
                            "high_site_id": hi[1], "high": hi[0],
                            "ratio": round(hi[0] / lo[0], 2)})  # fmt: skip
        return out

    @staticmethod
    def _used_sources(site_quotes: list[Json]) -> set[str]:
        used: set[str] = set()

        def walk(o: Any) -> None:
            if isinstance(o, dict):
                for k in ("prov", "prov_high"):
                    if isinstance(o.get(k), dict):
                        used.add(o[k]["source_id"])
                if isinstance(o.get("searched"), dict):
                    used.add(o["searched"]["source_id"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        for sq in site_quotes:
            if sq["site"]["price_source_id"]:
                used.add(sq["site"]["price_source_id"])
            walk(sq)
        return used
