"""Minimal quote engine for the P1 thin real slice (one care path x {BCBS HMO, cash} x 3 sites).

care path steps -> codes -> rate rows (in-memory ``SliceData``) -> ``QuoteResponse``, validated by
the contract models exactly once. Every dollar is a rate row's number (``prov.row_ref``); every
missing number is a typed Gap that comes from a real lookup that found nothing:

* ``not_published``: we searched the named file for this code / payer / modifier and it has no
  dollar row (``searched`` names the file);
* ``percent_only``: the file has only "X% of charges" for it;
* ``not_loaded``: a source exists but we do not read it yet (a code outside the ETL code list,
  a site whose doctor groups are not linked to TiC billing TINs, a clinic's posted cash page);
* ``no_source``: no public source exists (a doctor's self-pay fee).

Lines per step, per site billing type:

* hospital outpatient: the hospital's own fee (hospital MRF, facility rows) and the doctor's fee
  (insurer TiC, professional rows of the site's billing TINs at place of service 22; imaging
  reads use modifier 26). Therapy codes have no separate doctor's fee.
* office visit: one global fee (insurer TiC, professional rows at place of service 11).

Ranges: when several rows match (provider groups, plan variants, the fully- and self-insured
HMO Blue files) the cell is Money(low=min, high=max) and ``prov`` cites the lowest row. The
contract has one Provenance per Money, so the high end is not cited (docs/p1-slice.md).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.care_paths.loader import load_paths
from app.care_paths.models import CarePath, Step
from app.etl.config import load_codes, load_sources
from app.etl.contracts import PriceBasis
from app.quote.contracts import (
    CashPayment,
    InsurancePayment,
    QuoteRequest,
    QuoteResponse,
    missing_for,
    rank_key,
    tier_basis_for_rating,
)
from app.quote.slice_data import (
    REPO_ROOT,
    Row,
    SliceData,
    load_config,
    load_from_build,
)
from app.registries import all_hospitals
from app.sites.contracts import Freshness, Site, SitesFile

SITES_PATH = REPO_ROOT / "contracts" / "fixtures" / "sites.json"
PAYER_ALIASES = REPO_ROOT / "data" / "etl" / "payer_aliases.yaml"
TIC_NETWORKS = REPO_ROOT / "data" / "etl" / "tic_networks.yaml"
GLOSSARY = REPO_ROOT / "content" / "glossary" / "glossary.yaml"

OTHER_PAYERS_CODE = "73030"  # the range bar is shown on the X-ray facility line (P1)


def load_sites(path: Path = SITES_PATH) -> dict[str, Site]:
    doc = json.loads(path.read_text())
    doc.pop("_fixture", None)
    doc.pop("_schema", None)
    return {s.id: s for s in SitesFile.model_validate(doc).sites}


def _matches(when: dict[str, list[str]], answers: dict[str, list[str]]) -> bool:
    return all(set(vals) & set(answers.get(q, [])) for q, vals in when.items())


def _searched(meta_sid: str, sha: str) -> dict[str, str]:
    return {"source_id": meta_sid, "source_sha256": sha}


def _money(lo: Row, amount_lo: float, amount_hi: float, basis: PriceBasis) -> dict[str, Any]:
    return {
        "kind": "money",
        "low": amount_lo,
        "high": amount_hi,
        "basis": basis.value,
        "prov": lo.prov(basis).model_dump(mode="json"),
    }


def _range(rows: list[Row], value, basis: PriceBasis) -> dict[str, Any] | None:
    """Money over the distinct values of ``rows``; prov is the lowest row (then lowest stage_row
    in source order, which the caller sets by the order of ``rows``)."""
    vals = [(value(r), i, r) for i, r in enumerate(rows) if value(r) is not None]
    if not vals:
        return None
    vals.sort(key=lambda t: (t[0], t[1]))
    return _money(vals[0][2], vals[0][0], max(v for v, _, _ in vals), basis)


class Engine:
    def __init__(
        self,
        data: SliceData,
        *,
        config: dict[str, Any] | None = None,
        sites: dict[str, Site] | None = None,
        paths: dict[str, CarePath] | None = None,
    ) -> None:
        self.data = data
        self.config = config or load_config()
        self.sites = sites or load_sites()
        self.paths = paths or load_paths()
        aliases = yaml.safe_load(PAYER_ALIASES.read_text())
        self.payer_labels = {k: v["label"] for k, v in aliases["payers"].items()}
        self.products = set(aliases["products"])
        self.etl_codes = set(load_codes().codes)
        self.glossary = set(yaml.safe_load(GLOSSARY.read_text())["terms"])
        specs = {s.source_id: s for s in load_sources().sources}
        self.hospital_source = {
            s.entity_id: s.source_id for s in specs.values() if s.kind.value == "hospital_mrf"
        }
        self.scope_sites = list(self.config["sites"])

    # ------------------------------------------------------------------ startup

    @classmethod
    def scope(cls, config: dict[str, Any], sites: dict[str, Site], paths: dict[str, CarePath]):
        path = paths[config["care_path"]]
        codes = sorted({c for st in path.steps for c in st.all_codes()})
        specs = {s.source_id: s for s in load_sources().sources}
        by_entity = {
            s.entity_id: s.source_id for s in specs.values() if s.kind.value == "hospital_mrf"
        }
        hospitals = all_hospitals()
        hosp_sources, tins, publishers = [], set(), {}
        for sid in config["sites"]:
            site = sites[sid]
            if site.hospital_entity_id:
                src = by_entity[site.hospital_entity_id]
                hosp_sources.append(src)
                publishers[src] = hospitals[site.hospital_entity_id].name
            tins |= set(site.tins)
        nets = yaml.safe_load(TIC_NETWORKS.read_text())["networks"]
        labels = {n["source_id"]: n["label"] for n in nets}
        tic_sources = [s for srcs in config["networks"].values() for s in srcs]
        for s in tic_sources:
            payer = specs[s].payer_id or ""
            aliases = yaml.safe_load(PAYER_ALIASES.read_text())["payers"]
            publishers[s] = f"{aliases[payer]['label']} · {labels[s]}"
        return hosp_sources, tic_sources, sorted(tins), codes, publishers

    @classmethod
    def load_real(
        cls, hospital_build: Path, tic_root: Path, extra_hospital_sources=()
    ) -> SliceData:
        config, sites, paths = load_config(), load_sites(), load_paths()
        hosp, tic, tins, codes, publishers = cls.scope(config, sites, paths)
        for s in extra_hospital_sources:
            ent = next(sp.entity_id for sp in load_sources().sources if sp.source_id == s)
            publishers[s] = all_hospitals()[ent].name
        return load_from_build(
            hospital_build=hospital_build,
            tic_root=tic_root,
            hospital_sources=[*hosp, *extra_hospital_sources],
            tic_sources=tic,
            tins=tins,
            codes=codes,
            publishers=publishers,
        )

    # ------------------------------------------------------------------ lookups

    def _hospital_insurance(self, src: str, code: str, mod: str, payer: str, product: str):
        rows = self.data.get("hospital", (src, code, payer))
        cands = [
            r
            for r in rows
            if r.row_kind == "payer_rate"
            and r.payer_id == payer
            and not r.excluded
            and r.line_of_business in ("commercial", "unknown")
            and (r.product == "" or product in r.product.split("/"))
            and r.modifiers == mod
            and r.component in ("facility", "unknown")
        ]
        money = _range(cands, lambda r: r.amount, PriceBasis.negotiated)
        sha = self.data.sources[src].source_sha256
        if money:
            confirmed = all(r.component == "facility" for r in cands if r.amount is not None)
            return money, confirmed
        pct = sorted((r.negotiated_pct, r.stage_row) for r in cands if r.negotiated_pct is not None)
        if pct:
            return {
                "kind": "percent_only",
                "pct": pct[0][0],
                "of": "the hospital's full charge for this line, which its file does not list",
                "searched": _searched(src, sha),
            }, all(r.component == "facility" for r in cands)
        return {
            "kind": "not_published",
            "what": "this insurer's rate for this item at this hospital",
            "ask": "Ask the hospital billing office for a Good Faith Estimate for your plan.",
            "searched": _searched(src, sha),
        }, True

    def _cash_rows(self, src: str, code: str, mod: str) -> list[Row]:
        return [
            r
            for r in self.data.get("cash", (src, code))
            if r.modifiers == mod and r.component in ("facility", "unknown")
        ]

    def _hospital_cash(self, src: str, code: str, mod: str):
        cands = self._cash_rows(src, code, mod)
        money = _range(cands, lambda r: r.discounted_cash, PriceBasis.discounted_cash)
        if money:
            return money, all(r.component == "facility" for r in cands)
        sha = self.data.sources[src].source_sha256
        return {
            "kind": "not_published",
            "what": "a self-pay (cash) price for this item",
            "ask": "Ask the hospital for its discounted cash price or a Good Faith Estimate.",
            "searched": _searched(src, sha),
        }, True

    def _list_price(self, src: str, code: str, mod: str) -> dict[str, Any] | None:
        cands = [r for r in self._cash_rows(src, code, mod) if r.gross is not None]
        grosses = {r.gross for r in cands}
        if len(grosses) != 1:
            return None  # several list prices for one line: not shown (docs/p1-slice.md)
        r = cands[0]
        return _money(r, r.gross, r.gross, PriceBasis.gross)  # type: ignore[arg-type]

    def _tic(self, tic_sources: list[str], tins: list[str], code: str, mod: str, pos: set[str]):
        rows: list[Row] = []
        for sid in tic_sources:
            for tin in tins:
                rows += self.data.get("tic", (sid, tin, code))
        cands = [
            r
            for r in rows
            if r.billing_class == "professional"
            and r.modifiers == mod
            and not r.excluded
            and set(r.service_codes.split("|")) & pos
        ]
        dollars = [r for r in cands if r.amount is not None and r.negotiated_type != "percentage"]
        money = _range(dollars, lambda r: r.amount, PriceBasis.negotiated)
        first = tic_sources[0]
        if money:
            names = {r.business_name for r in dollars}
            gtins = {r.tin for r in dollars}
            fee = {
                "rung": 2,
                "explanation_key": "fee.rung_2_group",
                "group_name": next(iter(names)) if len(names) == 1 else None,
                "group_tin": (
                    f"{next(iter(gtins))[:2]}-{next(iter(gtins))[2:]}"
                    if len(gtins) == 1 and len(next(iter(gtins))) == 9
                    else None
                ),
            }
            return money, fee
        pct = sorted((r.negotiated_pct, r.stage_row) for r in cands if r.negotiated_pct is not None)
        sha = self.data.sources[first].source_sha256
        if pct:
            return {
                "kind": "percent_only",
                "pct": pct[0][0],
                "of": "the doctor group's billed charge",
                "searched": _searched(first, sha),
            }, None
        return {
            "kind": "not_published",
            "what": "this insurer's rate for this doctor group and item",
            "ask": "Ask the office which doctor group bills for it and what your plan pays.",
            "searched": _searched(first, sha),
        }, None

    # ------------------------------------------------------------------ lines

    def _steps(self, path: CarePath, answers: dict[str, list[str]]):
        """Active steps with their (likelihood, rating) after the path's tier modifiers."""
        out = []
        for st in path.steps:
            if st.condition and not _matches(st.condition, answers):
                continue
            tier, rating = st.likelihood_tier, st.appropriateness.rating
            for m in path.tier_modifiers:
                if m.step == st.id and _matches(m.when, answers):
                    tier = m.tier
                    if m.appropriateness is not None:
                        rating = m.appropriateness.rating
            out.append((st, tier, rating))
        return out

    def _site_lines(self, site: Site, path: CarePath, req: QuoteRequest) -> list[dict[str, Any]]:
        cfg = self.config
        pay = req.payment
        insured = isinstance(pay, InsurancePayment)
        hospital = site.billing_type == "hospital_outpatient"
        src = self.hospital_source.get(site.hospital_entity_id) if site.hospital_entity_id else None
        tic_sources = cfg["networks"].get(f"{pay.payer_id}/{pay.product}", []) if insured else []
        pos = set(cfg["place_of_service"][site.billing_type])
        lines: list[dict[str, Any]] = []

        for st, tier, rating in self._steps(path, req.answers):
            basis = tier_basis_for_rating(rating)
            gloss = [g for g in st.glossary if g in self.glossary]
            learn = [{"label": lm.label, "url": lm.url} for lm in st.learn_more]
            primary = [c.code for c in st.cpts if c.role == "primary"]
            addons = [c.code for c in st.cpts if c.code in cfg["per_15_minutes"]]
            base = {
                "step_id": st.id,
                "likelihood": tier,
                "why": st.plain.why,
                "tier_basis": basis,
                "learn_more": learn,
            }
            for code in primary + addons:
                per15 = code in cfg["per_15_minutes"]
                name = st.plain.name if not per15 else "Later exercise sessions (each 15 minutes)"
                tech = st.plain.technical_name if not per15 else "Therapeutic exercise"
                stem = st.id if not per15 else f"{st.id}_sessions"
                unit = "per_15_minutes" if per15 else "once"
                if hospital:
                    lines.append(
                        self._facility_line(base, stem, code, name, tech, gloss, unit, src, pay)
                    )
                    if code not in cfg["facility_only_codes"]:
                        lines.append(
                            self._doctor_line(base, stem, code, name, tech, gloss, unit, site,
                                              tic_sources, pos, pay, hospital=True)
                        )  # fmt: skip
                else:
                    lines.append(
                        self._doctor_line(base, stem, code, name, tech, gloss, unit, site,
                                          tic_sources, pos, pay, hospital=False)
                    )  # fmt: skip
            for ai in st.ai_potential:
                for c in ai.cpts:
                    lines.append(self._ai_line(base, st, c.code, ai.text))
        return lines

    def _line(self, base, line_id, codes, mod, plain, tech, gloss, component, confirmed, unit,
              cell, **kw) -> dict[str, Any]:  # fmt: skip
        return {
            "line_id": line_id,
            "tier": "",  # set by _finish
            "likelihood": base["likelihood"],
            "step_id": base["step_id"],
            "codes": codes,
            "modifier": mod or None,
            "plain_name": plain,
            "technical_name": tech,
            "why": base["why"],
            "glossary_keys": gloss,
            "component": component,
            "component_confirmed": confirmed,
            "unit": unit,
            "availability": "offered",
            "cell": cell,
            "list_price": kw.get("list_price"),
            "tier_basis": base["tier_basis"],
            "doctor_fee": kw.get("doctor_fee"),
            "ai_suggested": kw.get("ai_suggested", False),
            "in_total": False,
            "elsewhere": [],
            "learn_more": base["learn_more"],
        }

    def _facility_line(self, base, stem, code, name, tech, gloss, unit, src, pay):
        if isinstance(pay, CashPayment):
            cell, confirmed = self._hospital_cash(src, code, "")
        else:
            cell, confirmed = self._hospital_insurance(src, code, "", pay.payer_id, pay.product)
        gloss = gloss + (["facility_fee"] if "facility_fee" in self.glossary else [])
        return self._line(
            base, f"{stem}_facility", [code], "", f"{name}: the hospital's fee",
            f"{tech} (hospital facility fee)", gloss, "facility", confirmed, unit, cell,
            list_price=self._list_price(src, code, ""),
        )  # fmt: skip

    def _doctor_line(self, base, stem, code, name, tech, gloss, unit, site, tic_sources, pos, pay,
                     *, hospital: bool):  # fmt: skip
        mod = self.config["professional_modifier"].get(code, "") if hospital else ""
        if hospital:
            reading = bool(mod)
            line_id = f"{stem}_reading" if reading else f"{stem}_doctor"
            plain = f"{name}: the doctor's fee" if not reading else f"{name}: the doctor's reading"
            tech_name = f"{tech} (professional fee)"
        else:
            line_id, plain, tech_name = stem, name, tech
        if isinstance(pay, CashPayment):
            cell = {
                "kind": "no_source",
                "what": "the doctor's own fee for a self-pay patient",
                "ask": "Ask for a Good Faith Estimate (No Surprises Act). In Massachusetts the "
                "office must tell you the price within 2 business days (c.111 §228).",
            }
            fee = {"rung": None, "explanation_key": "fee.self_pay_no_source"}
        elif not site.tins:
            cell = {
                "kind": "not_loaded",
                "what": "the doctor's fee here: the insurer publishes it per billing group, and "
                "we have not linked this site's doctor groups yet",
                "eta": None,
            }
            fee = None
        else:
            cell, fee = self._tic(tic_sources, list(site.tins), code, mod, pos)
        return self._line(
            base, line_id, [code], mod, plain, tech_name, gloss, "professional", True, unit, cell,
            doctor_fee=fee,
        )  # fmt: skip

    def _ai_line(self, base, st: Step, code: str, text: str) -> dict[str, Any]:
        if code in self.etl_codes:
            raise NotImplementedError(f"{code}: AI-suggested codes inside the ETL list (P1)")
        cell = {
            "kind": "not_loaded",
            "what": "the price of the medicine itself (we do not read drug codes from the price "
            "files yet)",
            "eta": None,
        }
        return self._line(
            base, f"{st.id}_drug_ai", [code], "", "The medicine in the shot",
            "Injected medicine (billed as a drug)", [], "drug", False, "once", cell,
            ai_suggested=True,
        ) | {"why": text}  # fmt: skip

    # ------------------------------------------------------------------ assembly

    @staticmethod
    def _finish(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for ln in lines:
            kind = ln["cell"]["kind"]
            lk = ln["likelihood"]
            if kind in ("not_published", "not_loaded", "no_source"):
                ln["tier"] = "not_in_public_data"
            else:
                ln["tier"] = "possible" if lk == "rare" else lk
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
    def _excluded_reason(ln: dict[str, Any]) -> str:
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

    def _totals(self, lines, pay, fresh_by_source: dict[str, Freshness]) -> dict[str, Any]:
        summed = [ln for ln in lines if ln["in_total"]]
        likely = None
        if summed:
            fresh = [fresh_by_source[ln["cell"]["prov"]["source_id"]] for ln in summed]
            likely = {
                "low": round(sum(ln["cell"]["low"] for ln in summed), 2),
                "high": round(sum(ln["cell"]["high"] for ln in summed), 2),
                "line_ids": [ln["line_id"] for ln in summed],
                "includes_estimate": False,
                "includes_late_source": any(f.late_to_refresh for f in fresh),
                "includes_stale_source": any(f.stale_on_our_side for f in fresh),
            }
        partial = any(
            ln["likelihood"] in ("certain", "likely")
            and not ln["in_total"]
            and not ln["ai_suggested"]
            for ln in lines
        )
        if isinstance(pay, InsurancePayment):
            yp = self.config["you_pay"][pay.payer_id]
            you_pay = {
                "kind": yp["kind"],
                "note_key": f"youpay.{yp['kind']}",
                "portal_label": yp.get("portal_label"),
                "portal_url": yp.get("portal_url"),
            }
        else:
            you_pay = {"kind": "cash_full_amount", "note_key": "youpay.cash_full_amount",
                       "portal_label": None, "portal_url": None}  # fmt: skip
        return {
            "likely": likely,
            "complete": not partial,
            "missing": 0,  # set once every site is built (I7 needs the other sites)
            "excluded": [
                {"line_id": ln["line_id"], "reason": self._excluded_reason(ln)}
                for ln in lines
                if not ln["in_total"]
            ],
            "you_pay": you_pay,
        }

    def _other_payers(self, src: str, pay, lines) -> list[dict[str, Any]]:
        line = next((ln for ln in lines if ln["line_id"] == "xray_facility"), None)
        if line is None:
            return []
        rows = [
            r
            for pid in sorted(self.payer_labels)  # mapped payers only; unmapped names are noise
            for r in self.data.get("hospital", (src, OTHER_PAYERS_CODE, pid))
            if r.row_kind == "payer_rate"
            and not r.excluded
            and r.modifiers == ""
            and r.component in ("facility", "unknown")
            and r.amount is not None
        ]
        groups: dict[str, list[Row]] = defaultdict(list)
        for r in rows:  # one point per payer: the range over its plans
            groups[r.payer_id or ""].append(r)
        points = []
        for key, rs in groups.items():
            money = _range(rs, lambda r: r.amount, PriceBasis.negotiated)
            products = {p for r in rs for p in r.product.split("/") if p}
            points.append({
                "payer_id": rs[0].payer_id,
                "label": self.payer_labels.get(rs[0].payer_id or "", key),
                "product": next(iter(products)) if len(products) == 1 and products <= self.products
                else None,
                "money": money,
            })  # fmt: skip
        points.sort(key=lambda p: (p["money"]["low"], p["label"]))
        if not points:
            return []
        cash, _ = self._hospital_cash(src, OTHER_PAYERS_CODE, "")
        payer = pay.payer_id if isinstance(pay, InsurancePayment) else None
        return [{
            "line_id": line["line_id"],
            "code": OTHER_PAYERS_CODE,
            "points": points,
            "cash": cash if cash["kind"] == "money" else None,
            "yours": "in_points" if any(p["payer_id"] == payer for p in points) else "not_in_points",
        }]  # fmt: skip

    def _summary(self, site: Site, price_source_id: str) -> dict[str, Any]:
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
            "price_label": "price_file",
            "price_source_id": price_source_id,
            "listing_status": site.listing_status,
            "service_areas": list(site.service_areas),
        }

    def _freshness(self, as_of: date) -> dict[str, Freshness]:
        out = {}
        for sid, m in self.data.sources.items():
            hospital = m.source_kind == "hospital_mrf"
            out[sid] = Freshness.compute(
                as_of=as_of,
                source_rule="hospital_mrf_365_days" if hospital else "tic_45_days",
                last_updated=date.fromisoformat(m.last_updated) if m.last_updated else None,
                our_rule="hospital_monthly" if hospital else "tic_monthly",
                fetched_at=date.fromisoformat(m.fetched_at),
            )
        return out

    def quote(self, req: QuoteRequest, as_of: date) -> QuoteResponse:
        if req.care_path_id is None:
            raise ValueError("P1 prices care paths only; the manual picker (D3) is stream C")
        path = self.paths[req.care_path_id]
        pay = req.payment
        if not isinstance(pay, (InsurancePayment, CashPayment)):
            raise ValueError(f"P1 prices BCBS HMO and cash only, not {pay.kind}")
        if (
            isinstance(pay, InsurancePayment)
            and f"{pay.payer_id}/{pay.product}" not in self.config["networks"]
        ):
            raise ValueError(f"P1 has no TiC network for {pay.payer_id} {pay.product}")
        fresh = self._freshness(as_of)  # per request (D18); never stored on the shared engine
        wanted = req.site_ids if req.site_ids is not None else self.scope_sites
        site_quotes, without = [], []
        for sid in wanted:
            if sid not in self.scope_sites:
                raise ValueError(f"site {sid} is outside the P1 slice")
            site = self.sites[sid]
            src = (
                self.hospital_source.get(site.hospital_entity_id)
                if site.hospital_entity_id
                else None
            )
            if src is None and isinstance(pay, CashPayment):
                # its own cash source is a posted page we do not read yet; the contract needs a
                # price_source_id with freshness, so it cannot be shown (docs/p1-slice.md)
                without.append(sid)
                continue
            price_source = src or self.config["networks"][f"{pay.payer_id}/{pay.product}"][0]
            lines = self._finish(self._site_lines(site, path, req))
            sq = {
                "site": self._summary(site, price_source),
                "receipt": {"lines": lines, "totals": self._totals(lines, pay, fresh)},
                "other_payers": (
                    self._other_payers(src, pay, lines)
                    if src and isinstance(pay, InsurancePayment)
                    else []
                ),
            }
            site_quotes.append(sq)
        site_quotes = self._rank(site_quotes)
        used = self._used_sources(site_quotes)
        sources = {
            sid: {
                "source_kind": self.data.sources[sid].source_kind,
                "publisher": self.data.sources[sid].publisher,
                "freshness": fresh[sid].model_dump(mode="json"),
            }
            for sid in sorted(used)
        }
        notices = []
        if path.review.status != "approved":
            notices.append("care_path_draft")
        if self.data.version.tic_release is None:
            notices.append("tic_not_loaded")
        if any(fresh[s].late_to_refresh for s in used):
            notices.append("late_to_refresh_sources")
        if any(fresh[s].stale_on_our_side for s in used):
            notices.append("stale_on_our_side_sources")
        body = {
            "payment": pay.model_dump(mode="json"),
            "care_path": {
                "id": path.id,
                "version": path.version,
                "title": path.title.en,
                "review_status": path.review.status,
            },
            "service_codes": [],
            "picked_by": req.picked_by,
            "as_of": as_of.isoformat(),
            "data_version": {
                "build_id": self.data.version.build_id,
                "build_date": self.data.version.build_date,
                "tic_release": self.data.version.tic_release,
                "sites_version": 1,
                "care_paths_version": path.version,
            },
            "sources": sources,
            "sites": site_quotes,
            "sites_without_service": without,
            "notices": notices,
        }
        return QuoteResponse.model_validate(body)

    def _rank(self, site_quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """I7 with the contract's own helpers: missing = unpriced certain/likely lines + steps
        another site lists and this one does not; then order by (missing, total low)."""
        from app.quote.contracts import SiteQuote

        def model(sq):
            return SiteQuote.model_validate(sq)

        exp_steps = set()
        for sq in site_quotes:
            for ln in sq["receipt"]["lines"]:
                if ln["likelihood"] in ("certain", "likely") and not ln["ai_suggested"]:
                    exp_steps.add(ln["step_id"] or ",".join(ln["codes"]))
        for sq in site_quotes:
            sq["receipt"]["totals"]["missing"] = missing_for(model(sq), exp_steps)
        return sorted(site_quotes, key=lambda sq: (rank_key(model(sq)), sq["site"]["site_id"]))

    @staticmethod
    def _used_sources(site_quotes) -> set[str]:
        used: set[str] = set()

        def walk(o):
            if isinstance(o, dict):
                if "prov" in o and isinstance(o["prov"], dict):
                    used.add(o["prov"]["source_id"])
                if "searched" in o and isinstance(o["searched"], dict):
                    used.add(o["searched"]["source_id"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        for sq in site_quotes:
            used.add(sq["site"]["price_source_id"])
            walk(sq)
        return used
