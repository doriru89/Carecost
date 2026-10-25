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
MassHealth, rung 5 Medicare, rung 6 Medicare x the group's own typical multiple (an estimate, in
the total and flagged), rung 7 Medicare as a reference floor (shown, never summed). Self-pay
doctor fees have no public source.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.care_paths.models import CarePath
from app.etl.contracts import Method, PriceBasis
from app.quote.contracts import (
    CashPayment,
    InsurancePayment,
    MassHealthPayment,
    MedicarePayment,
    QuoteRequest,
    QuoteResponse,
    tier_basis_for_rating,
)
from app.quote.registry import Registry, posted_source
from app.quote.store import DEFAULT_RULES, FEE_SCHEDULE_KINDS, RateStore, Row, SourceMeta
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
        self.posted = {s.id: m for s in self.reg.sites.values() if (m := posted_source(s))}
        self.posted_by_source = {m.source_id: m for m in self.posted.values()}
        # fee schedules: every loaded file of a kind (Medicare PFS = RVU file + anesthesia file;
        # MassHealth = 101 CMR 316 / 317 / 318). One release per file id.
        self.pfs = self.store.sources_of("medicare_pfs")
        self.opps = self.store.sources_of("medicare_opps")
        self.asc = self.store.sources_of("medicare_asc")
        self.mh = self.store.sources_of("masshealth_fs")
        self._multiples: dict[tuple, Json | None] = {}
        self._evidence: dict[tuple[str, str], bool] = {}
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
            "prov": self.store.prov(lo[2], basis, method=method).model_dump(mode="json"),
        }
        if hi[0] > lo[0]:
            p = self.store.prov(hi[2], basis, method=method).model_dump(mode="json")
            out["prov_high"] = p
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

    def _site_tic(self, q: Req, site: Site, codes: list[str], mod: str, pos: frozenset,
                  billing_class: str, *, any_pos: bool = False,
                  networks: list[str] | None = None) -> list[Row]:  # fmt: skip
        own, linked = self._site_tins(site)
        rows = self._tic_rows(q, own, codes, mod, pos, billing_class, any_pos=any_pos,
                              networks=networks)  # fmt: skip
        if linked:
            cid = site.census_id or ""
            more = self._tic_rows(q, linked, codes, mod, pos, billing_class, any_pos=any_pos,
                                  networks=networks)  # fmt: skip
            rows += [r for r in more if r.names_site(cid)]
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
            return _not_published(self.store, src, f"a self-pay (cash) price for {what}",
                                  "Ask the hospital for its discounted cash price or a Good Faith "
                                  "Estimate."), True, list_price  # fmt: skip

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
        fs_srcs = self.asc if site.billing_type == "asc" else self.opps
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

    def _group_rate(self, rows: list[Row]) -> tuple[Json, Json] | None:
        dollars = [r for r in rows if r.amount is not None and r.negotiated_type != "percentage"]
        money = self._money(dollars, lambda r: r.amount, PriceBasis.negotiated)
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
        by_npi = self._by_npi(dollars)
        if by_npi:
            fee["by_npi"] = by_npi
            fee["npi_count"] = len(by_npi)
        return money, fee

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

    def _multiple(self, q: Req, site: Site, setting: str, pos: frozenset) -> Json | None:
        """Rung 6 (D5): the group's own typical multiple of Medicare for this payer, from codes
        where both a group TiC dollar rate and the Medicare PFS rate exist (>= 5 codes)."""
        key = (site.id, tuple(q.networks), setting, q.payer)
        if key in self._multiples:
            return self._multiples[key]
        lows, highs = [], []
        if self.pfs:
            for code in sorted(self.store.codes):
                fs = [r.amount for r in self._fs_rows(self.pfs, code, "", setting, site)
                      if r.amount]  # fmt: skip
                if not fs:
                    continue
                rows = [
                    r for r in self._site_tic(q, site, [code], "", pos, "professional")
                    if r.amount is not None and r.negotiated_type != "percentage"
                ]  # fmt: skip
                if rows:
                    lows.append(min(r.amount for r in rows) / fs[0])  # type: ignore[operator]
                    highs.append(max(r.amount for r in rows) / fs[0])  # type: ignore[operator]
        out = None
        if len(lows) >= self.cfg["ladder"]["rung6_min_codes"]:
            out = {
                "low": round(statistics.median(lows), 2),
                "high": round(statistics.median(highs), 2),
                "n_codes": len(lows),
                "payer_id": q.payer,
            }
        self._multiples[key] = out
        return out

    def _estimate(self, q: Req, site: Site, code: str, mod: str, setting: str, pos: frozenset):
        mult = self._multiple(q, site, setting, pos)
        rows = self._fs_rows(self.pfs, code, mod, setting, site)
        if not mult or not rows:
            return None
        base = min(rows, key=lambda r: (r.amount or 0, r.stage_row))
        if base.amount is None:
            return None
        prov = self.store.prov(base, PriceBasis.estimate, method=Method.estimate_medicare_multiple)
        p = prov.model_dump(mode="json")
        low, high = round(base.amount * mult["low"], 2), round(base.amount * mult["high"], 2)
        money: Json = {"kind": "money", "low": low, "high": high, "basis": "estimate", "prov": p}
        if high > low:
            money["prov_high"] = p
        fee = {"rung": 6, "explanation_key": "fee.rung_6_estimate", "multiple": mult}
        return money, fee

    def _doctor_cell(self, site: Site, item: Item, code: str, mod: str, q: Req, *,
                     hospital_line: bool):  # fmt: skip
        """-> (cell, doctor_fee or None, codes shown on the line)."""
        billing = site.billing_type
        setting = self.fs_setting[billing]
        pos = self.pos[billing]
        if q.kind == "cash":
            posted = q.posted.get(site.id)
            if not hospital_line and site.hospital_entity_id is None:
                if posted:
                    return self._posted_cell(site, posted, code), None, [code]
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
            got = self._group_rate(rows)
        if got is None:
            rows = self._site_tic(q, site, codes, mod, pos, "professional", any_pos=(mod == "26"))
            got = self._group_rate(rows)
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
        est = self._estimate(q, site, code, mod, setting, pos)
        if est:
            return est[0], est[1], codes
        if self.pfs:
            ref = self._money(self._fs_rows(self.pfs, code, mod, setting, site), lambda r: r.amount,
                              PriceBasis.fee_schedule)  # fmt: skip
            if ref:
                return ref, {"rung": 7, "explanation_key": "fee.rung_7_medicare_reference"}, codes
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
        prov = {
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
                "prov": prov}  # fmt: skip

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
            }  # fmt: skip
            cpts = [c for c in st.cpts if c.payer_scope in scope_ok]
            for c in cpts:
                if c.role == "primary":
                    out.append(Item(stem=st.id, code=c.code, unit="once", plain=st.plain.name,
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
        }

    def _site_lines(self, site: Site, items: list[Item], q: Req) -> list[Json]:
        lines: list[Json] = []
        billing = site.billing_type
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
            if ln["at"] == "this_site" and not self._offers(site, ln["codes"][0]):
                ln["availability"] = "unknown"
            if code_class(ln["codes"][0]) == "anesthesia" and self._fs_money(ln["cell"]):
                ln["price_notes"].append("price.anesthesia_base_units_only")
        return lines

    @staticmethod
    def _fs_money(cell: Json) -> bool:
        moneys = [cell] if cell["kind"] == "money" else (
            [cell["a"], cell["b"]] if cell["kind"] == "conflict" else [])  # fmt: skip
        return any(m["prov"]["source_kind"] in FEE_SCHEDULE_KINDS for m in moneys)

    def _offers(self, site: Site, code: str) -> bool:
        """Positive evidence that the site offers this code (Site.offered, P1 #14): an offered
        entry naming the code or a service that covers it (engine.yaml offered_services), a
        posted self-pay price for it, or any rate row for it in the site's own hospital file or
        in a TiC file for the site's billing TINs. Absence = unknown, never 'not offered'."""
        key = (site.id, code)
        if key in self._evidence:
            return self._evidence[key]
        ok = any(code in o.codes or self._service_covers(o.service, code) for o in site.offered)
        ok = ok or any(code in p.codes for p in site.cash_prices)
        if not ok:
            ok = self._first_row(site, code) is not None
        self._evidence[key] = ok
        return ok

    def _first_row(self, site: Site, code: str) -> Row | None:
        """The first rate row for the code in the site's own hospital file or a TiC file for its
        TINs (any modifier, place of service, payer). Recorded alone, so the committed extract
        reproduces the evidence without every row behind it."""
        found: Row | None = None
        src = self._site_hospital_source(site)
        if src and self.store.by_code.get((src, code)):
            found = self.store.by_code[(src, code)][0]
        if found is None:
            own, linked = self._site_tins(site)
            cid = site.census_id or ""
            for sid in self.tic_sources:
                for t in [*own, *linked]:
                    for r in self.store.tic.get((sid, t, code), ()):
                        if t in own or r.names_site(cid):
                            found = r
                            break
                    if found:
                        break
                if found:
                    break
        if found is not None and self.store.recorder is not None:
            self.store.recorder.add([found])
        return found

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

    @staticmethod
    def _finish(lines: list[Json]) -> list[Json]:
        for ln in lines:
            kind = ln["cell"]["kind"]
            lk = ln["likelihood"]
            ln["tier"] = "not_in_public_data" if kind in NO_NUMBER else (
                "possible" if lk == "rare" else lk)  # fmt: skip
            fee = ln["doctor_fee"]
            ln["in_total"] = (
                ln["tier"] in ("certain", "likely")
                and kind == "money"
                and ln["unit"] == "once"
                and not ln["ai_suggested"]
                and (fee is None or (fee["rung"] or 0) in range(1, 7))
            )
        return lines

    @staticmethod
    def _excluded_reason(ln: Json) -> str:
        kind = ln["cell"]["kind"]
        if ln["ai_suggested"]:
            return "ai_suggested"
        if kind == "conflict":
            return "conflict"
        if kind != "money":
            return "no_dollar_amount"
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

    def _totals(self, lines: list[Json], q: Req, fresh: Callable[[str], Freshness]) -> Json:
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
                    ln["cell"]["prov"]["method"] == "estimate_medicare_multiple" for ln in summed
                ),
                "includes_late_source": any(x.late_to_refresh for x in f),
                "includes_stale_source": any(x.stale_on_our_side for x in f),
            }
        partial = any(
            ln["likelihood"] in ("certain", "likely")
            and not ln["in_total"]
            and not ln["ai_suggested"]
            for ln in lines
        )
        return {
            "likely": likely,
            "complete": not partial,
            "missing": 0,  # set once every site is built (I7 needs the other sites)
            "excluded": [
                {"line_id": ln["line_id"], "reason": self._excluded_reason(ln)}
                for ln in lines
                if not ln["in_total"]
            ],
            "you_pay": self._you_pay(q),
        }

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
        wanted = req.site_ids if named else sorted(quotable)
        cands, without = [], []
        for sid in wanted:
            site = quotable.get(sid)
            if site is None:
                raise ValueError(f"unknown or unquotable site {sid}")
            if site.children_only and not named:
                continue  # D27: a children-only site only when the person names it
            if not self.reg.area_ok(site, areas) or not items:
                without.append(sid)
                continue
            cands.append(site)
        if req.near is not None:  # C2: the max_sites closest sites, then I7 inside that set
            cands = sorted(cands, key=lambda s: (_km(req.near, s), s.id))[: req.max_sites]

        fresh_cache: dict[str, Freshness] = {}

        def fresh(sid: str) -> Freshness:
            if sid not in fresh_cache:
                fresh_cache[sid] = self.freshness(self._meta(sid, q), as_of)
            return fresh_cache[sid]

        built = {site.id: self._site_quote(site, items, q) for site in cands}
        if len(built) > req.max_sites:  # no point given: the best max_sites of the whole set (I7)
            for sq in built.values():
                sq["receipt"]["totals"] = self._totals(sq["receipt"]["lines"], q, fresh)
            best = self._rank(list(built.values()))[: req.max_sites]
            built = {sq["site"]["site_id"]: sq for sq in best}
        site_quotes = list(built.values())
        for sq in site_quotes:  # fresh copies of the mutable parts, then I7 inside the chosen set
            for ln in sq["receipt"]["lines"]:
                ln["elsewhere"] = []
        self._elsewhere(site_quotes)
        for sq in site_quotes:
            sq["receipt"]["totals"] = self._totals(sq["receipt"]["lines"], q, fresh)
        site_quotes = self._rank(site_quotes)
        used = self._used_sources(site_quotes)
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
        body = {
            "payment": req.payment.model_dump(mode="json"),
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
            "sites": site_quotes,
            "sites_without_service": without,
            "copy_keys": COPY_KEYS if path is not None else [],
            "notices": notices,
        }  # fmt: skip
        return QuoteResponse.model_validate(body)

    def _site_quote(self, site: Site, items: list[Item], q: Req) -> Json:
        lines = self._finish(self._site_lines(site, items, q))
        src, label = self._price_source(site, q, lines)
        hs = self._site_hospital_source(site)
        return {
            "site": self._summary(site, src, label),
            "receipt": {"lines": lines, "totals": {}},
            "other_payers": self._other_payers(hs, lines, q) if hs else [],
        }

    def _elsewhere(self, site_quotes: list[Json]) -> None:
        """'Available elsewhere': a line with no number here lists the cheapest other sites in
        this quote that have a dollar amount for the same part of the same step."""
        offers: dict[tuple, list[tuple[float, Json, Json]]] = defaultdict(list)
        for sq in site_quotes:
            for ln in sq["receipt"]["lines"]:
                fee = ln["doctor_fee"]
                if (fee and (fee["rung"] or 0) >= 7) or ln["ai_suggested"]:
                    continue  # a reference-only number is not an offer (it never counts)
                if ln["cell"]["kind"] == "money" and ln["at"] == "this_site":
                    k = (
                        ln["step_id"] or ",".join(ln["codes"]),
                        ln["component"],
                        ln["codes"][0],
                        ln["modifier"],
                    )
                    offers[k].append((ln["cell"]["low"], sq["site"], ln["cell"]))
        n = self.cfg["elsewhere_max"]
        for sq in site_quotes:
            me = sq["site"]["site_id"]
            for ln in sq["receipt"]["lines"]:
                if ln["cell"]["kind"] not in NO_NUMBER or ln["at"] != "this_site":
                    continue
                k = (
                    ln["step_id"] or ",".join(ln["codes"]),
                    ln["component"],
                    ln["codes"][0],
                    ln["modifier"],
                )
                opts = sorted((o for o in offers.get(k, []) if o[1]["site_id"] != me),
                              key=lambda o: (o[0], o[1]["site_id"]))[:n]  # fmt: skip
                ln["elsewhere"] = [
                    {"site_id": s["site_id"], "site_name": s["name"], "lat": s["coords"]["lat"],
                     "lon": s["coords"]["lon"], "cell": cell}
                    for _, s, cell in opts
                ]  # fmt: skip

    @staticmethod
    def _rank(site_quotes: list[Json]) -> list[Json]:
        """I7: missing = unpriced certain/likely lines + certain/likely steps another site lists
        and this one does not; then order by (missing, total low, site id)."""

        def expected(ln: Json) -> bool:  # contracts._expected
            return ln["likelihood"] in ("certain", "likely") and not ln["ai_suggested"]

        def key(ln: Json) -> str:
            return ln["step_id"] or ",".join(ln["codes"])

        steps = {key(ln) for sq in site_quotes for ln in sq["receipt"]["lines"] if expected(ln)}
        for sq in site_quotes:
            lines = sq["receipt"]["lines"]
            unpriced = sum(1 for ln in lines if expected(ln) and not ln["in_total"])
            sq["receipt"]["totals"]["missing"] = unpriced + len(steps - {key(ln) for ln in lines})

        def rank(sq: Json) -> tuple:
            t = sq["receipt"]["totals"]
            return (t["missing"], t["likely"]["low"] if t["likely"] else float("inf"),
                    sq["site"]["site_id"])  # fmt: skip

        return sorted(site_quotes, key=rank)

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
