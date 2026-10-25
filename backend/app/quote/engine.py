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
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from functools import cached_property
from datetime import date
from typing import Any

from app.care_paths.models import CarePath
from app.etl.contracts import Method, PriceBasis
from app.quote.facts import SiteFacts, load_site_facts
from app.quote.pctc import NO_PROFESSIONAL_FEE, READING, load_pctc
from app.quote.tin_roles import effective_billing, load_roles
from app.quote.contracts import (
    BASIS_RANK,
    KIND_ORDER,
    CashPayment,
    InsurancePayment,
    MassHealthPayment,
    MedicarePayment,
    QuoteRequest,
    QuoteResponse,
    headline_basis,
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
ESTIMATED_FIGURES = ("estimate", "elsewhere", "elsewhere_estimate")
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


_TABLES: dict[tuple, Any] = {}


def _contract_table(path: Any) -> dict[str, dict[str, float]]:
    """data/quote/contract_levels.yaml, parsed once per file version (1.9 MB of YAML)."""
    if not path.exists():
        return {}
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _TABLES:
        _TABLES[key] = (yaml_load(path) or {}).get("groups") or {}
    return _TABLES[key]


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
    step_name: str = ""  # C4b: the step's plain name (StepSummary.plain_name, `includes`)
    excl: str | None = None  # C4b: the step's exclusive_group
    entry: bool = False  # C4b: this option's first visit (the headline's low end)
    travels: tuple[str, tuple[str, ...]] | None = None  # C4c: (step id, codes) it is billed with


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
    rev_prefixes: tuple[str, ...] | None = None  # C4b ER: hospital-file rows' allowed rev codes

    def rows_ok(self, rows: list[Row]) -> list[Row]:
        """Hospital-file rows this request may read. The ER reference reads only emergency-room
        rows: revenue code 045x, or no revenue code (CHA's ED rows carry none)."""
        if self.rev_prefixes is None:
            return rows
        return [r for r in rows if not r.rev_code
                or r.rev_code.zfill(4).startswith(self.rev_prefixes)]  # fmt: skip


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
        self.pctc = load_pctc(REPO_ROOT / cfg["pctc_file"])  # C4b 3a: CMS PC/TC indicator
        self.chain_names = {cid: ch.get("display_name") or ch["operator"]
                            for cid, ch in (cfg.get("chains") or {}).items()}  # fmt: skip
        self._flat: dict[tuple, bool] = {}
        o = cfg["no_location_origin"]
        self.origin = _P(float(o["lat"]), float(o["lon"]))
        # caches over data that never changes after startup (no request state, P1 #20)
        self._code_offer: dict[tuple[str, str], bool] = {}
        self._stats: dict[tuple, dict] = {}
        self._peer_cache: dict[tuple, tuple[list, str]] = {}
        cl = REPO_ROOT / cfg["contract_levels_file"]
        self.contract_levels: dict[str, dict[str, float]] = _contract_table(cl)
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
        what = "the place's own bill for this item"
        if cls == "visit":
            what = "the hospital's own bill for the clinic visit"

        if q.kind == "cash":
            if src is None:
                return _no_source(f"{what} for a self-pay patient"), True, None
            if not loaded:
                return (
                    _not_loaded(f"{what}: we do not read this code from price files yet"),
                    True,
                    None,
                )
            rows = q.rows_ok([r for c in loaded for r in self._cash_rows(src, c)])
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
                rows = q.rows_ok(rows)
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
                    what = ("a hospital bill this place may also charge (we could not "
                            "confirm how it bills)")  # fmt: skip
                return _not_published(self.store, q.networks[0], f"this insurer's rate for {what}",
                                      "Ask the center what your plan pays for its own bill."), \
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
        what = "the place's own bill for this item"
        if cls == "visit":
            what = "the hospital's own bill for the clinic visit"
        label = {"medicare": "Medicare", "masshealth": "MassHealth"}[q.kind]
        own = None
        if src and loaded:
            lobs = {"medicare"} if q.kind == "medicare" else {"medicaid"}
            rows = q.rows_ok(self._hospital_rows(src, loaded, q.payer or "", lobs, None))
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
            _not_loaded(f"{label}'s hospital payment schedule for {what} (not loaded yet)"),
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
                f"{label}'s rate for the doctor's bill",
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
            per_unit = "anesthesia_per_unit" in self.store.row_flags(r)  # C4b: A6's flag
            if twin is None and not per_unit:
                full.append(r)
                continue
            if twin is not None and self.store.recorder is not None:
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
            return _no_source("the doctor's own bill for a self-pay patient"), {
                "rung": None, "explanation_key": "fee.self_pay_no_source"}, [code]  # fmt: skip
        if q.kind == "medicare":
            cell, fee = self._fee_schedule_fee(self.pfs, code, mod, setting, 5, "Medicare", site)
            return cell, fee, [code]
        if q.kind == "masshealth":
            # C4b 3d: never a Medicare figure (rung 7) for a person who is not on Medicare
            cell, fee = self._fee_schedule_fee(self.mh, code, mod, setting, 4, "MassHealth", site)
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
            return _not_loaded("the doctor's bill here: the insurer publishes it per billing "
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
        # C4b 3d: no Medicare reference (rung 7) for an insured person: the gap stays a gap (the
        # peer estimate, rung 6, may still fill it from this insurer's own rates)
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

    @staticmethod
    def _entry_steps(path: CarePath, option: Any | None) -> set[str]:
        """The first visit(s): the option's visit step, else every layer-1 visit."""
        if option is not None:
            return {option.visit_step}
        return {st.id for st in path.steps if st.layer == 1 and st.kind == "visit"}

    def _path_items(self, path: CarePath, q: Req, option: Any | None = None) -> list[Item]:
        """The items to price. C4b (D-UI-3): with an entry option, the other options' first
        visits are not steps here (an urgent care has no skin-doctor visit line), and the
        option's own first visit is the certain entry visit."""
        answers = q.req.answers
        scope_ok = {"medicare": ("all", "medicare")}.get(q.kind, ("all", "commercial"))
        entry = self._entry_steps(path, option)
        others = {o.visit_step for o in path.entry_options if o.visit_step} - entry
        by_id = {st.id: st for st in path.steps}
        out: list[Item] = []
        for st in path.steps:
            if st.condition and not _matches(st.condition, answers):
                continue
            if st.id in others:
                continue
            tier, rating = st.likelihood_tier, st.appropriateness.rating
            if option is not None and st.id in entry:
                tier = "certain"  # the option's first visit
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
                "travels": (st.travels_with, tuple(
                    c.code for c in by_id[st.travels_with].cpts
                    if c.role in ("primary", "alternative"))) if st.travels_with else None,
                "step_name": st.plain.name,
                "excl": st.exclusive_group,
                "entry": st.id in entry,
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
                    "the hospital's bill"
                    if billing == "hospital_outpatient"
                    else "the center's bill"
                )
                lines.append(self._line(
                    it, f"{it.stem}_facility", extra.get("codes", [code]), shown,
                    f"{it.plain}: {who}", f"{it.tech} (facility fee)", "facility", confirmed, cell,
                    extra_gloss=["facility_fee"], list_price=lp,
                    price_notes=extra.get("price_notes", [])))  # fmt: skip
            if two_part and (
                code in self.facility_only
                or (cls != "anesthesia" and self.pctc.get(code) in NO_PROFESSIONAL_FEE)
            ):
                continue  # C4b 3a: CMS PC/TC 3/4/7/9 (e.g. clinical labs): no doctor's fee line
            if two_part:
                reading = (self.pctc[code] in READING if code in self.pctc
                           else code in self.reg.pc_tc_codes)  # fmt: skip
                mod = "26" if reading else ""
                line_id = f"{it.stem}_reading" if reading else f"{it.stem}_doctor"
                if cls == "anesthesia":
                    line_id, plain = it.stem, it.plain
                else:
                    plain = f"{it.plain}: the doctor's " + ("reading" if reading else "bill")
                cell, fee, codes = self._doctor_cell(site, it, code, mod, q, hospital_line=True)
                lines.append(self._line(
                    it, line_id, codes, mod or shown, plain, f"{it.tech} (professional fee)",
                    "professional", True, cell, doctor_fee=fee))  # fmt: skip
                lines[-1]["_ladder"] = True  # a hospital doctor's fee: priced by the ladder
            else:
                cell, fee, codes = self._doctor_cell(site, it, code, "", q, hospital_line=False)
                tech = it.tech if codes == [code] else f"{it.tech} (urgent care global fee)"
                lines.append(self._line(
                    it, it.stem, codes, shown, it.plain, tech, "professional", True, cell,
                    doctor_fee=fee))  # fmt: skip
        for ln in lines:
            if ln["at"] == "this_site":
                av, why = self._item_avail(site, ln["_item"], q)
                ln["availability"], ln["availability_reason"] = av, why
                if av == "not_offered":
                    ln["cell"] = None
            cell = ln["cell"]
            if cell is not None and cell["kind"] == "money" and "_m" in cell:
                self._flat_and_flags(ln, q)
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

    def _is_flat(self, r: Row) -> bool:
        """C4b item 5: a TiC row on a non-visit code whose group (TIN) has the same amount, same
        billing class, on a visit code in the same network file: the insurer pays this place one
        amount per visit (Tufts Direct pays ConvenientMD $125 on 99203 / 99213 / 81003 / 81025)."""
        if r.source_kind != "insurer_tic" or r.amount is None or code_class(r.code) == "visit":
            return False
        k = (r.source_id, r.tin, r.billing_class, r.amount)
        if k not in self._flat:
            self._flat[k] = any(
                x.amount == r.amount and x.billing_class == r.billing_class
                for vc in self.visit_codes for x in self.store.tic.get((r.source_id, r.tin, vc), ())
            )  # fmt: skip
        return self._flat[k]

    @cached_property
    def visit_codes(self) -> tuple[str, ...]:
        ref = set(getattr(self.reg.codes, "reference", {}) or {})  # not the ED levels
        return tuple(
            sorted(c for c in self.store.codes if code_class(c) == "visit" and c not in ref)
        )

    def _flat_and_flags(self, ln: Json, q: Req) -> None:
        """C4b items 4-5 on one priced line: A6's TiC flags and the flat visit rate.

        * ``institutional_on_physician_npi``: a doctors' group's "institutional" row is neither a
          facility fee nor a doctor's fee: left out of the line.
        * ``anesthesia_per_unit``: a per-unit rate, never a whole price (left to the anesthesia
          per-unit rule, which multiplies an anesthesia group's rate by the base units).
        * ``same_npi_pos_multi_rate``: the same doctors at the same place have several rates in
          the file: the line keeps the range and says so (``price.several_rates_same_doctors``).
        * flat visit rate: rows that are this group's visit amount are counted once, on the
          visit. When every row is one, the line keeps the amount, is never summed (P8a cannot
          sum it either: it is never gated) and says ``price.flat_visit_rate``."""
        cell = ln["cell"]
        rows, value, basis, method = cell["_m"]
        flags = self.store.row_flags
        keep = [(v, r) for v, r in rows if "institutional_on_physician_npi" not in flags(r)]
        if ln["at"] == "this_site":
            flat = [(v, r) for v, r in keep if self._is_flat(r)]
            if flat and len(flat) == len(keep):
                ln["_flat"] = True
                ln["price_notes"].append("price.flat_visit_rate")
            elif flat:
                keep = [t for t in keep if t not in flat]
        if len(keep) != len(rows):
            m = self._money([r for _, r in keep], value, basis, method) if keep else None
            ln["cell"] = m or _not_published(
                self.store,
                rows[0][1].source_id,
                "a usable rate for this item here (the file's "
                "rows for it are not this kind of fee)",
                "Ask the office what your plan pays.",
            )
            cell = ln["cell"]
        if cell["kind"] == "money" and any(
                "same_npi_pos_multi_rate" in flags(r) for _, r in cell["_m"][0]):  # fmt: skip
            ln["price_notes"].append("price.several_rates_same_doctors")

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

    def _item_avail(self, site: Site, it: Item, q: Req) -> tuple[str, str | None]:
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
        if it.travels is not None:
            # C4c: a step billed whenever another happens (care path travels_with: anesthesia
            # with the colonoscopy, the lab check with the skin sample) is done wherever that
            # step is offered (site facts or code evidence for it)
            tid, tcodes = it.travels
            said = self.facts.step(site.id, it.path_id or "", tid)
            if said == "offered" or (said is None and any(self.offers_code(site, c)
                                                          for c in tcodes)):  # fmt: skip
                return "offered", None
        if self._tic_row_for(site, it.code):
            # C4b 3e: "your insurer lists a rate" is only true for an insurance payment
            return "unknown", ("insurer_lists_rate" if q.kind == "insurance"
                               else "price_file_lists_rate")  # fmt: skip
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
                and not ln.get("_flat")  # C4b item 5: counted once, on the visit
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
        if ln.get("_flat"):
            return "flat_visit_rate"
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
            and not ln.get("_flat")  # C4b: its amount is the visit's, already summed
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
        if ln.get("_flat"):  # C4b: the visit's amount, not a price for this item
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
        if ln["at"] != "this_site" or ln.get("_flat") or not self._entries(ln):
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
                side = "high" if v > hi_x * got[0] else "low"
                if self._contract_level(site, self._group(r), ln["codes"][0], q, side):
                    # Austin 2026-10-25: a group consistently this far from its peers is its
                    # contract, not a data error: summed, real price, with a note
                    kept.append(r)
                    note = f"price.group_consistently_{'higher' if side == 'high' else 'lower'}"
                    if note not in ln["price_notes"]:
                        ln["price_notes"].append(note)
                    continue
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

    def contract_key(self, site: Site, group: str, q: Req) -> str:
        return f"{site.id}|{group}|{q.kind}|{q.payer or ''}|{q.product}"

    def contract_ratios(self, site: Site, group: str, q: Req) -> dict[str, float]:
        """O ``contract_level`` (app/audit/causes.py), reimplemented on the engine's peer sets:
        the group's lower-median price / its peer median (same network, same kind) for every
        code-modifier-component the group prices at this site. Offline only (it prices every
        code at every site): python -m app.quote.contract_levels writes the table."""
        net = group.split("@", 1)[1] if "@" in group else "hospital_file"
        ratios: dict[str, float] = {}
        for c in self.contract_level_codes():
            per = self._line_stats(c, q).get(site.id, {})
            for (comp, pmod), ents in per.items():
                vals = sorted(v for v, g, _ in ents if g == group)
                if not vals:
                    continue
                peers, _ = self._peers(site, c, comp, pmod, q, estimate=False, network=net)
                if len(peers) < self.out_cfg["min_groups"]:
                    continue
                med = _lower_median([v for v, _ in peers])
                if med > 0:
                    ratios[f"{c}-{pmod}-{comp}"] = round(vals[(len(vals) - 1) // 2] / med, 4)
        return ratios

    def contract_level_codes(self) -> list[str]:
        """The codes contract levels are measured on: every loaded code except the response-level
        reference codes (codes.yaml ``reference:``, the ED visit levels): an ER fee is no sign of
        a group's contract level at a clinic (A7 note, C4b)."""
        ref = set(getattr(self.reg.codes, "reference", {}) or {})
        return sorted(c for c in self.store.codes if c not in ref)

    def _contract_level(self, site: Site, group: str, code: str, q: Req, side: str) -> bool:
        """Austin 2026-10-25: the same group sits at >= high x (<= low x) its peer median on
        >= min_codes OTHER codes (median ratio), from data/quote/contract_levels.yaml."""
        cfg = self.out_cfg["contract_level"]
        ratios = self.contract_levels.get(self.contract_key(site, group, q)) or {}
        others = [r for k, r in ratios.items() if not k.startswith(f"{code}-")]
        if len(others) < int(cfg["min_codes"]):
            return False
        m = statistics.median(others)  # as O's causes.py
        return m >= float(cfg["high"]) if side == "high" else m <= float(cfg["low"])

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
            if q.kind == "insurance" and code_class(ln["codes"][0]) == "anesthesia":
                self._anes_estimate(ln, q)
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
        if fee is not None or ln.get("_ladder"):  # C4b: a ladder gap (no rung 7 now) too
            ln["doctor_fee"] = {"rung": 6, "explanation_key": "fee.rung_6_estimate"}

    @cached_property
    def _anes_groups(self) -> dict[str, dict[str, list[Row]]]:
        """network file -> anesthesia group TIN -> its per-unit rows (A6 flag anesthesia_per_unit,
        an anesthesia group by name, as the per-unit rule reads them)."""
        out: dict[str, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
        for (sid, tin, code), rows in self.store.tic.items():
            if code not in self.anes_base:
                continue
            for r in rows:
                if (r.amount and "anesthesia_per_unit" in self.store.row_flags(r)
                        and "ANESTH" in r.business_name.upper()):  # fmt: skip
                    out[sid][tin].append(r)
        return out

    def _anes_estimate(self, ln: Json, q: Req) -> None:
        """C4c (Austin: anesthesia with a colonoscopy is in the headline): no rate for this site's
        anesthesia here or at peer sites -> the payer's own anesthesia groups in the person's
        network files: per-unit rate x (CMS base units + typical minutes / 15), p25-p75 of >=
        min_groups groups (one rate per group, its lower median), both ends cited. Same payer
        only; never across payers, never Medicare."""
        code = ln["codes"][0]
        base = self.anes_base.get(code)
        if not base:
            return
        t = self.anes_time.get(code)
        factor = base + (t["minutes"] / 15 if t else 0.0)
        per = []
        for net in q.networks:
            vals = []
            for _tin, rows in sorted(self._anes_groups.get(net, {}).items()):
                if self.store.recorder is not None:  # the extract keeps the rows behind it
                    self.store.recorder.add(rows)
                rs = sorted(rows, key=lambda r: (r.amount, r.uid))
                r = rs[(len(rs) - 1) // 2]
                vals.append((round(r.amount * factor, 2), r))
            vals.sort(key=lambda v: (v[0], v[1].uid))
            n = len(vals)
            if n >= self.peer_cfg["min_groups"]:
                per.append((vals[_rank_pos(n, self.peer_cfg["low_percentile"])],
                            vals[_rank_pos(n, self.peer_cfg["high_percentile"])],
                            vals[(n - 1) // 2][0], n))  # fmt: skip
        if not per:
            return
        lo = min((p[0] for p in per), key=lambda v: (v[0], v[1].uid))
        hi = max((p[1] for p in per), key=lambda v: (v[0], v[1].uid))
        money: Json = {"kind": "money", "low": lo[0], "high": hi[0], "basis": "estimate",
                       "prov": self._est_prov(lo[1], q)}  # fmt: skip
        if hi[0] > lo[0]:
            money["prov_high"] = self._est_prov(hi[1], q)
        ln["cell"] = money
        ln["elsewhere"] = []
        ln["estimate"] = {
            "low": lo[0], "high": hi[0], "median": _lower_median([p[2] for p in per]),
            "n_groups": sum(p[3] for p in per), "kind": None, "scope": "payer_network",
            "payer_id": q.payer,
        }  # fmt: skip
        ln["price_notes"] = [
            n for n in ln["price_notes"] if n != "price.anesthesia_base_units_only"
        ]
        ln["price_notes"].append("price.anesthesia_typical_time" if t else
                                 "price.anesthesia_base_units_only")  # fmt: skip
        if ln["doctor_fee"] is not None or ln.get("_ladder"):
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

    def option_of(self, site: Site, path: CarePath | None) -> Any | None:
        """C4b: the first entry option of the path whose kinds, site types or service areas the
        site matches (None: the path has no options, or the site matches none)."""
        if path is None:
            return None
        kind = self._kind(site)
        for o in path.entry_options:
            if (kind in o.site_kinds or site.site_type in o.site_types
                    or set(site.service_areas) & set(o.service_areas)):  # fmt: skip
                return o
        return None

    def _admits(self, site: Site, path: CarePath | None, areas: set[str],
                option: Any | None = None) -> bool:  # fmt: skip
        """A site enters a path when it offers the entry visit (layer 1) or the core procedure
        (a layer-2 procedure that is certain or likely) by the offer rules; with no evidence either
        way, when its kind may do that kind of step (engine.yaml admission_step_kinds)."""
        if not self.reg.area_ok(site, areas):
            return False
        if path is None:
            return True
        entry = self._entry_steps(path, option)
        keys = [st for st in path.steps if not st.no_price and (
            st.id in entry
            or (st.layer == 2 and st.kind == "procedure"
                and st.likelihood_tier in ("certain", "likely"))
        )]  # fmt: skip
        core = [st for st in path.steps if not st.no_price and st.layer == 2
                and st.kind == "procedure" and st.likelihood_tier == "certain"]  # fmt: skip
        if core and option is None:
            # C4c: a procedure path (colonoscopy) is admitted by its certain core procedure only,
            # never by an optional consult: offered, or unknown at a kind that does procedures
            keys = core
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

    def _admitted(self, path: CarePath | None, areas: set[str],
                  option: Any | None = None) -> list[str]:  # fmt: skip
        """Admitted sites. With an option: the sites whose option it is (option_of) that offer
        its first visit or the core procedure. Without: the path's whole pool (the sites peers
        and 'elsewhere' ranges are drawn from)."""
        key = (path.id if path else None, tuple(sorted(areas)), option.id if option else None)
        if key not in self._admitted_cache:
            self._admitted_cache[key] = [
                s.id for s in sorted(self.reg.sites.values(), key=lambda s: s.id)
                if s.listing_status != "registry_only" and not s.children_only
                and (option is None or self.option_of(s, path) is option)
                and self._admits(s, path, areas, option)
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
            if not lines or any(ln["availability"] != "offered" or ln.get("_flat")
                                for ln in lines):  # fmt: skip
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
            from_kinds: set[str] = set()
            flat = bool(priced) and all(ln.get("_flat") for ln in priced)
            if avail == "offered":
                if priced and all(self._counts(ln) for ln in priced):
                    paid = [ln for ln in priced if not ln.get("_flat")]  # C4b: flat adds $0
                    figure = "estimate" if any(ln["estimate"] for ln in priced) else "own"
                    low = round(sum(ln["cell"]["low"] for ln in paid), 2)
                    high = round(sum(ln["cell"]["high"] for ln in paid), 2)
                    rank = round(sum(self._central(ln) for ln in paid), 2)
                elif (part := self._partial_lines(priced)) is not None:
                    # C4c: the hospital's bill is priced, the doctor's bill has no number: "from
                    # $X". Never a ranking figure (missing data never makes a site cheaper, P1)
                    low, high, from_kinds = part
                    figure = "estimate" if any(ln["estimate"] for ln in priced) else "own"
                elif pool["range"] is not None and not first["_item"].entry:
                    # main 2026-10-25: offered here but no own price -> the step's range at the
                    # sites that price it, as an estimate (never summed, never this site's price)
                    rng = pool["range"]
                    figure, low, high = "elsewhere_estimate", rng["low"], rng["high"]
                    rank = rng["median"]
            elif pool["range"] is not None:
                rng = pool["range"]
                figure, low, high, rank = "elsewhere", rng["low"], rng["high"], rng["median"]
            missing = expected and (figure == "none" or bool(from_kinds)) and pool["priced"]
            out.append({
                "key": key, "step_id": first["step_id"], "likelihood": first["likelihood"],
                "availability": avail, "figure": figure, "low": low, "high": high,
                "rank_value": rank if expected and figure != "none" and not from_kinds else None,
                "from_only": bool(from_kinds), "_from_kinds": from_kinds,
                "estimated": any(ln["estimate"] for ln in lns) or figure == "elsewhere_estimate",
                "unusual": any(ln["unusual"] for ln in lns),
                "in_total": bool(priced) and all(ln["in_total"] for ln in priced),
                "missing": missing, "line_ids": [ln["line_id"] for ln in lns],
                "elsewhere": rng, "_expected": expected, "_ai": ai,
                "plain_name": first["_item"].step_name or first["_item"].plain,
                "flat_visit_rate": flat and figure == "own",
                "_excl": first["_item"].excl, "_entry": first["_item"].entry,
                "_why": first["why"],
                "_kind": first["_item"].step_kind,
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
        fh = self.facts.hours.get(site.id)
        if hours is None and fh is not None:  # C4c: the site's own page, via site facts (X1)
            from app.sites.contracts import Hours

            hours = Hours.model_validate({"source": "operator_html", "source_url": fh["url"],
                                          "checked_at": fh["checked_at"], "weekly": fh["weekly"]})  # fmt: skip
            label = "site_page_hours"
        elif hours is None:
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
            "chain_name": self.chain_names.get(self.chain_of.get(site.id) or ""),
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
        pay = req.payment
        if isinstance(pay, InsurancePayment) and pay.product == "HMO" and "Q14" not in req.answers:
            # C4c: an HMO plan needs a referral; unanswered Q14 is derived from the plan here
            # (the frontend did it before), so every client gets the referral layer
            req = req.model_copy(
                update={"answers": {**req.answers, "Q14": ["hmo_referral_required"]}}
            )
        q = self._context(req, as_of)
        path = self.reg.paths.get(req.care_path_id) if req.care_path_id else None
        if req.care_path_id and path is None:
            raise ValueError(f"unknown care path {req.care_path_id}")
        if path is not None:
            areas = self.reg.path_areas(path)
        else:
            areas = set().union(*(self.reg.code_areas(c) for c in req.service_codes))
            areas = areas or {"ortho", "skin", "gi", "urgent_care"}
        quotable = {
            sid: s for sid, s in self.reg.sites.items() if s.listing_status != "registry_only"
        }
        named = req.site_ids is not None
        pool = self._admitted(path, areas)  # P4 / P5: peers and elsewhere ranges come from here
        options = list(path.entry_options) if path is not None else []
        # C4b (D-UI-3): one group per priced entry option (its own first visit and sites); a path
        # without options is one group of the whole pool
        groups: list[tuple[Any, list[Item], list[str]]] = []
        if options:
            for o in options:
                if o.priced:
                    groups.append((o, self._path_items(path, q, o),  # type: ignore[arg-type]
                                   self._admitted(path, areas, o)))  # fmt: skip
        else:
            items = self._path_items(path, q) if path is not None else self._code_items(q)
            groups.append((None, items, pool))
        member: dict[str, tuple[Any, list[Item]]] = {}
        for o, its, adm in groups:
            for sid in adm if its else []:
                member.setdefault(sid, (o, its))
        cands: list[tuple[Site, Any, list[Item]]] = []
        without: list[str] = []
        if named:
            for sid in req.site_ids or []:
                site = quotable.get(sid)
                if site is None:
                    raise ValueError(f"unknown or unquotable site {sid}")
                if sid in member:
                    cands.append((site, *member[sid]))
                    continue
                kid = None  # D27: a children-only site only when named
                if site.children_only:
                    for o, its, _ in groups:
                        if its and (o is None or self.option_of(site, path) is o) and \
                                self._admits(site, path, areas, o):  # fmt: skip
                            kid = (o, its)
                            break
                if kid:
                    cands.append((site, *kid))
                else:
                    without.append(sid)
        else:
            cands = [(quotable[sid], o, its) for o, its, adm in groups if its for sid in adm]
            unpriced = {
                sid
                for sid in pool
                if path is not None
                and options
                and ((o := self.option_of(quotable[sid], path)) is not None and not o.priced)
            }
            without = sorted(sid for sid, s in quotable.items()
                             if sid not in member and sid not in unpriced
                             and not s.children_only)  # fmt: skip
        origin = req.near if req.near is not None else self.origin
        dist = {c[0].id: round(_km(origin, c[0]), 2) for c in cands}
        if req.near is not None:  # C2: the max_sites closest admitted sites (per option, C4b)
            kept: list[tuple[Site, Any, list[Item]]] = []
            for o, _, _ in groups:
                mine = [c for c in cands if c[1] is o]
                kept += sorted(mine, key=lambda c: (dist[c[0].id], c[0].id))[: req.max_sites]
            cands = kept

        fresh_cache: dict[str, Freshness] = {}

        def fresh(sid: str) -> Freshness:
            if sid not in fresh_cache:
                fresh_cache[sid] = self.freshness(self._meta(sid, q), as_of)
            return fresh_cache[sid]

        built = [self._site_quote(site, its, pool, q, fresh, o) for site, o, its in cands]
        for sq in built:
            sq["distance_km"] = dist[sq["site"]["site_id"]]
        opt_index = {o.id: i for i, o in enumerate(options)}

        def rank(sq: Json) -> tuple:
            h = sq["headline"]
            return (h["missing"], h["comparable"] if h["comparable"] is not None else math.inf,
                    sq["distance_km"] if req.near is not None else 0.0,
                    -h["real_steps"], sq["site"]["name"], sq["site"]["site_id"])  # fmt: skip

        if options:  # C4b: option A then B; within one, distance (default) or price
            by = req.order_by or "distance"
            ordering = f"option_then_{by}"

            def order(sq: Json) -> tuple:
                head = (opt_index[sq["option_id"]],)
                if by == "price":  # completeness basis first: a partial figure never leads
                    hr = sq["headline_range"]
                    return (
                        head
                        + ((BASIS_RANK[hr["basis"]], hr["low"]) if hr else (3, math.inf))
                        + (sq["distance_km"], sq["site"]["name"], sq["site"]["site_id"])
                    )
                return head + (sq["distance_km"], sq["site"]["name"], sq["site"]["site_id"])
        elif req.near is not None or named:
            ordering = "rank"
            order = rank
        else:
            ordering = "kind_then_distance"  # P7: no "best value overall"

            def order(sq: Json) -> tuple:
                return (KIND_ORDER[sq["site"]["kind"]], sq["distance_km"], sq["site"]["name"],
                        sq["site"]["site_id"])  # fmt: skip

        built.sort(key=order)
        self._elsewhere(built)
        spreads = self._chain_spreads(built)
        if req.near is None and not named:  # item 9: summaries for all, receipts for the first N
            seen: dict[Any, int] = defaultdict(int)
            for sq in built:  # C4b: the first N of each option
                seen[sq["option_id"]] += 1
                if seen[sq["option_id"]] > req.full_receipts:
                    sq["receipt"] = None
                    sq["other_payers"] = []
        er = self._er_reference(q, origin) if path is not None else None
        used = self._used_sources(built) | (self._walk_sources(er) if er else set())
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
        if path is not None and not options:  # C4c: one implicit option, so cheapest exists
            imp = self._implicit_option(path)
            for sq in built:
                sq["option_id"] = imp.id
            opts = [self._option_summary(imp, built)]
        else:
            opts = [self._option_summary(o, built) for o in options]
        referral = set(req.answers.get("Q14", [])) & set(self.cfg["referral_answers"])
        if referral and any(o["specialist"] and o["site_count"] for o in opts):
            notices.append("hmo_referral_for_specialist")  # C4b 3c: at the top, not in a receipt
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
            "options": opts,
            "er_reference": er,
        }  # fmt: skip
        return QuoteResponse.model_validate(_public(body))

    def _payment_label(self, q: Req) -> Json:
        if q.kind == "insurance":
            name = self.reg.payer_labels.get(q.payer or "", q.payer or "")
            return {"en": f"{name} {q.product}", "zh": f"{name} {q.product}"}
        return dict(self.cfg["payment_labels"][q.kind])

    def _site_quote(self, site: Site, items: list[Item], admitted: list[str], q: Req,
                    fresh: Callable[[str], Freshness], option: Any | None = None) -> Json:  # fmt: skip
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
            "option_id": option.id if option is not None else None,
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
            "headline_range": self._headline_range(steps, lines),
            "steps": steps,
            "distance_km": None,
            "receipt": {"lines": lines, "totals": totals},
            "other_payers": self._other_payers(hs, lines, q) if hs else [],
        }

    # ------------------------------------------------------------------ headline range (C4b)

    @staticmethod
    def _step_fig(st: Json) -> tuple[float, float] | None:
        """A step's (low, high) for the headline: this site's own price or estimate, or the
        elsewhere range when this site has no evidence it does it; a flat-rate step adds $0."""
        if st["figure"] == "none":
            return None
        return (st["low"], st["high"])

    def _partial_lines(self, once: list[Json]) -> tuple[float, float, set[str]] | None:
        """C4b 3b / C4c: a step whose hospital (facility) bill is priced and whose doctor's bill
        has no number (no public source for self-pay; not published or not loaded): 'from $X'.
        -> (low, high, the gap kinds of the doctor's bills) or None."""
        priced = [ln for ln in once if self._counts(ln) and not ln.get("_flat")]
        rest = [ln for ln in once if ln not in priced]
        if not priced or not rest or not all(
            ln["cell"] is not None and ln["cell"]["kind"] in NO_NUMBER
            and ln["component"] == "professional" for ln in rest
        ) or any(ln["component"] != "facility" for ln in priced):  # fmt: skip
            return None
        return (round(sum(ln["cell"]["low"] for ln in priced), 2),
                round(sum(ln["cell"]["high"] for ln in priced), 2),
                {ln["cell"]["kind"] for ln in rest})  # fmt: skip

    def _headline_range(self, steps: list[Json], lines: list[Json]) -> Json | None:
        """C4b item 1 (Austin 2026-10-25): the headline is a range for the certain and likely
        steps. Low = the sum of their lows, high = the sum of their highs (this site's own price,
        or the elsewhere range where it does not do the step). Three subtotals for the breakdown:
        visit_only (the first visit, every bill), with_likely (= the headline), with_possible
        (+ possible and rare steps; within an exclusive_group only the dearest counts). Possible
        steps are listed one by one in may_also_order, never in the headline."""
        real = [st for st in steps if not st["_ai"]]
        # C4c: the base is the certain first visit; an entry step that is not certain (the
        # colonoscopy's optional pre-procedure consult) is never in it. No certain entry visit:
        # the certain steps of the care here (a referral at your own doctor is not "the visit")
        base = [st for st in real if st["_entry"] and st["likelihood"] == "certain"]
        if not base:
            base = [
                st for st in real if st["likelihood"] == "certain" and st["_kind"] != "referral"
            ]
        if not base:
            return None
        vlo = vhi = 0.0
        est = False
        for st in base:
            f = self._step_fig(st)
            if f is None:
                return None
            est = est or st["figure"] in ESTIMATED_FIGURES
            vlo, vhi = vlo + f[0], vhi + f[1]
        rest = [st for st in real if st not in base]

        def tier(sts: list[Json], exclusive: bool) -> Json:
            best: dict[str, Json] = {}
            if exclusive:
                for st in sts:
                    g, f = st["_excl"], self._step_fig(st)
                    if g and f is not None and (g not in best or f[1] > best[g]["high"]):
                        best[g] = st
            lo, hi, out = vlo, vhi, {"step_keys": [], "includes": [], "not_priced": [],
                                      "alternatives": [], "estimated": est}  # fmt: skip
            for st in sts:
                f = self._step_fig(st)
                if f is None and st["_kind"] == "referral":
                    continue  # C4c: the referral visit at your own doctor is not this place's
                    # price; unpriced, it shows in the steps, never as this site's gap
                if f is None:
                    out["not_priced"].append(st["plain_name"])
                elif exclusive and st["_excl"] and best[st["_excl"]] is not st:
                    out["alternatives"].append(st["plain_name"])
                else:
                    lo, hi = lo + f[0], hi + f[1]
                    out["step_keys"].append(st["key"])
                    out["includes"].append(st["plain_name"])
                    out["estimated"] = out["estimated"] or st["figure"] in ESTIMATED_FIGURES
            return {"low": round(lo, 2), "high": round(hi, 2), **out}

        likely = [st for st in rest if st["likelihood"] in ("certain", "likely")]
        possible = [st for st in rest if st["likelihood"] in ("possible", "rare")]
        visit = {"low": round(vlo, 2), "high": round(vhi, 2), "step_keys": [], "includes": [],
                 "not_priced": [], "alternatives": [], "estimated": est}  # fmt: skip
        with_likely = tier(likely, exclusive=False)
        with_possible = tier(likely + possible, exclusive=True)
        counted = base + [st for st in likely if st["key"] in with_likely["step_keys"]]
        kinds = set().union(*(st["_from_kinds"] for st in counted))
        from_only = bool(kinds)
        notes = (["headline.doctor_bills_separately"] if "no_source" in kinds else []) + (
            ["headline.doctor_bill_not_published"] if kinds - {"no_source"} else []
        )
        return {
            "low": with_likely["low"], "high": with_likely["high"],
            "basis": headline_basis(from_only, with_likely),
            "includes": list(with_likely["includes"]),
            "from_only": from_only,
            "note_keys": notes,
            "visit_step_keys": [st["key"] for st in base],
            "visit_only": visit, "with_likely": with_likely, "with_possible": with_possible,
            "may_also_order": [
                {"step_key": st["key"], "plain_name": st["plain_name"], "why": st["_why"],
                 "low": f[0] if (f := self._step_fig(st)) else None,
                 "high": f[1] if f else None, "figure": st["figure"],
                 "from_only": st["from_only"],
                 "exclusive_group": st["_excl"]}
                for st in possible
            ],
        }  # fmt: skip

    @staticmethod
    def _implicit_option(path: CarePath) -> Any:
        from types import SimpleNamespace

        from app.care_paths.models import Title

        visit = next((st.id for st in path.steps if st.layer == 1 and st.kind == "visit"
                      and st.likelihood_tier == "certain"), None)  # fmt: skip
        return SimpleNamespace(
            id="a", label=Title(en=path.title.en, zh=path.title.zh or path.title.en),
            visit_step=visit, specialist=False, priced=True, missing_reason=None, implicit=True,
        )  # fmt: skip

    def _option_summary(self, o: Any, built: list[Json]) -> Json:
        """C4b: one entry option over its sites in this response: each subtotal's min low ..
        max high, the plain names any site includes, and the cheapest site (lowest headline low,
        ties by distance; Austin: 'the cheapest place to see a doctor for this')."""
        mine = [sq for sq in built if sq["option_id"] == o.id]
        ranged = [sq for sq in mine if sq["headline_range"] is not None]
        counts: dict[str, int] = defaultdict(int)
        for sq in ranged:
            counts[sq["headline_range"]["basis"]] += 1
        # C4c: the option's range and spans come from the sites of the best basis present (the
        # same set cheapest_site_id is picked from), so a partial 'from' figure never sets them
        best = min((BASIS_RANK[b] for b in counts), default=None)
        top = [sq for sq in ranged if BASIS_RANK[sq["headline_range"]["basis"]] == best]

        def span(key: str) -> Json | None:
            vals = [sq["headline_range"][key] for sq in top]
            if not vals:
                return None
            names: list[str] = []
            for v in vals:
                names += [n for n in v["includes"] if n not in names]
            return {"low": min(v["low"] for v in vals), "high": max(v["high"] for v in vals),
                    "includes": names}  # fmt: skip

        # main 2026-10-25: never let a partial (or borrowed) figure win "cheapest": the best
        # completeness basis present first, then the lowest low, then the nearest
        cheapest = min(ranged, key=lambda sq: (BASIS_RANK[sq["headline_range"]["basis"]],
                                               sq["headline_range"]["low"], sq["distance_km"],
                                               sq["site"]["site_id"]), default=None)  # fmt: skip
        head = span("with_likely")
        return {
            "id": o.id, "label": o.label.model_dump(mode="json"), "visit_step": o.visit_step,
            "specialist": o.specialist, "priced": o.priced, "missing_reason": o.missing_reason,
            "site_count": len(mine), "sites_with_range": len(ranged),
            "low": head["low"] if head else None, "high": head["high"] if head else None,
            "includes": head["includes"] if head else [],
            "visit_only": span("visit_only"), "with_likely": head,
            "with_possible": span("with_possible"),
            "cheapest_site_id": cheapest["site"]["site_id"] if cheapest else None,
            "cheapest_basis": cheapest["headline_range"]["basis"] if cheapest else None,
            "basis": top[0]["headline_range"]["basis"] if top else None,
            "sites_by_basis": dict(counts), "partial_site_count": counts.get("partial", 0),
            "implicit": bool(getattr(o, "implicit", False)),
        }  # fmt: skip

    # ------------------------------------------------------------------ ER reference (C4b 7)

    def _er_reference(self, q: Req, origin: Any) -> Json:
        """C4b item 7: what the nearest hospitals' emergency rooms bill for an ED visit, levels
        3-5 (facility + doctor), under this payment. Response level only: never ranked, never a
        site's price. Austin: 'the ER visit alone usually costs much more, before any tests'."""
        cfg = self.cfg["er_reference"]
        codes = list(cfg["codes"])
        base = {"note_key": "er.visit_alone_costs_more", "codes": codes, "low": None,
                "high": None, "includes_doctor": False, "hospitals": []}  # fmt: skip
        if not any(c in self.store.codes for c in codes):
            return {**base, "status": "not_loaded"}
        # one site per hospital price file, and only files that list an ED visit code (a hospital
        # with an emergency room); the site named like the hospital itself, else the nearest
        near: dict[str, tuple[int, float, Site]] = {}
        for s in self.reg.sites.values():
            src = self._site_hospital_source(s)
            if s.listing_status == "registry_only" or s.children_only or src is None:
                continue
            if s.site_type != "hospital_outpatient" or not any(
                    self.store.by_code.get((src, c)) for c in codes):  # fmt: skip
                continue
            d = round(_km(origin, s), 2)
            hosp_like = (0 if s.name == self.reg.hospital_names.get(s.hospital_entity_id or "")
                         else 1 if re.match(r"[^,]*(hospital|medical center)$", s.name, re.I)
                         else 2)  # fmt: skip
            if src not in near or (hosp_like, d, s.id) < (near[src][0], near[src][1],
                                                         near[src][2].id):  # fmt: skip
                near[src] = (hosp_like, d, s)
        # main 2026-10-25: BMC also bills 99283 at a clinic (revenue code 0520, $122.40 self-pay):
        # only emergency-room rows (045x) or rows with no revenue code price the ER facility fee
        qe = replace(q, rev_prefixes=tuple(str(p) for p in cfg["rev_code_prefixes"]))
        hosp = [(d, s) for _, d, s in sorted(near.values(), key=lambda t: (t[1], t[2].id))][
            : int(cfg["hospitals"])
        ]
        it = Item(stem="er", code=codes[0], unit="once", plain="ER visit", tech="ED visit",
                  why=None, likelihood="certain", tier_basis="picked", step_id=None, gloss=[],
                  learn=[])  # fmt: skip
        out, lows, highs, doctor_all = [], [], [], True
        for d, s in hosp:
            levels = []
            for code in codes:
                fac = self._facility_cell(s, code, qe, "er")[0]
                doc = self._doctor_cell(s, it, code, "", q, hospital_line=True)[0]
                levels.append({"code": code, "facility": fac, "doctor": doc})
                if fac["kind"] == "money":
                    dm = doc if doc["kind"] == "money" else None
                    doctor_all = doctor_all and dm is not None
                    lows.append((code, fac["low"] + (dm["low"] if dm else 0)))
                    highs.append((code, fac["high"] + (dm["high"] if dm else 0)))
            out.append({"site_id": s.id, "name": s.name, "distance_km": d, "levels": levels})
        if not lows:
            return {**base, "status": "not_published", "hospitals": out}
        return {**base, "status": "priced", "hospitals": out,
                "low": round(min(v for _, v in lows), 2),
                "high": round(max(v for _, v in highs), 2),
                "includes_doctor": doctor_all}  # fmt: skip

    def _elsewhere(self, site_quotes: list[Json]) -> None:
        """'Available elsewhere': a line with no number here lists the cheapest other sites in
        this quote that offer the same part of the same step and have a real dollar amount."""
        offers: dict[tuple, list[tuple[float, Json, Json]]] = defaultdict(list)
        for sq in site_quotes:
            for ln in sq["receipt"]["lines"]:
                if not self._counts(ln) or ln["ai_suggested"] or ln["estimate"] or ln.get("_flat"):
                    continue  # a reference-only, unusual, estimated or flat number is not an offer
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
                if (ln["at"] == "this_site" and self._counts(ln) and not ln["estimate"]
                        and not ln.get("_flat")):  # fmt: skip
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

    @classmethod
    def _used_sources(cls, site_quotes: list[Json]) -> set[str]:
        used: set[str] = set()
        for sq in site_quotes:
            if sq["site"]["price_source_id"]:
                used.add(sq["site"]["price_source_id"])
            used |= cls._walk_sources(sq)
        return used

    @staticmethod
    def _walk_sources(obj: Any) -> set[str]:
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

        walk(obj)
        return used
