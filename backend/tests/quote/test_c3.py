"""Stream C3: the quote engine fixed at the source (wave-2 review R1-R12, Austin's rulings P1-P9).

One test per rule, on the committed extract (real rows from the full pack, recorded by
``python -m app.quote.fixtures_gen``; the C3 cases are ``fixtures_gen.C3_CASES``)."""

from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
import yaml

from app.quote.contracts import QuoteRequest
from app.quote.engine import Engine
from app.quote.facts import load_site_facts
from app.quote.fixtures_gen import AETNA_PPO, KEY_SITES, MILTON, NEAR, TUFTS_HMO
from app.quote.store import valid_npi
from tests.quote.conftest import AS_OF

BCBS_HMO = {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None}
SHOULDER = "shoulder_chronic_clicking_v1"
AFC_ARL = "afc_urgent_care_arlington_arlington"
CHA = "cha_cambridge_hospital"
ASC = "mass_general_brigham_endoscopy_clinic_braintree"


def _q(engine, payment=BCBS_HMO, path=SHOULDER, **where):
    body = {"payment": payment, "care_path_id": path, "answers": {}, "service_codes": [],
            "picked_by": "person", "site_ids": None}  # fmt: skip
    body.update(where)
    return engine.quote(QuoteRequest.model_validate(body), AS_OF)


def _site(r, sid):
    return next(s for s in r.sites if s.site.site_id == sid)


def _line(r, sid, lid):
    return next(ln for ln in _site(r, sid).receipt.lines if ln.line_id == lid)


def _engine_with(engine, **cfg) -> Engine:
    """The same data under changed engine.yaml rules (a hand mutation)."""
    reg = copy.copy(engine.reg)
    reg.config = {**engine.reg.config, **cfg}
    return Engine(engine.store, reg)


# --------------------------------------------------------------------------- 1, 2: offer evidence


def test_a_tic_row_alone_is_unknown_and_never_summed(engine):
    """R1 / R2 / P6: every line whose only 'evidence' is an insurer row is unknown with the P6
    reason, never in a total; and offers_code never looks at TiC rows."""
    seen = 0
    for path in sorted(engine.reg.paths):
        r = _q(engine, path=path, site_ids=KEY_SITES)
        for sq in r.sites:
            for ln in sq.receipt.lines:
                if ln.availability_reason == "insurer_lists_rate":
                    seen += 1
                    assert ln.availability == "unknown" and not ln.in_total
    assert seen > 10
    # AFC Watertown has TiC rows for 97161 (PT) but nothing from the site: not offered
    afc = engine.reg.sites["afc_watertown"]
    assert engine._tic_row_for(afc, "97161") and not engine.offers_code(afc, "97161")


def test_offer_evidence_sources(engine):
    """R1: a hospital file listing the code, a posted price (own or chain), an offered entry."""
    reg = engine.reg
    mtauburn = reg.sites["mount_auburn_hospital"]
    assert engine.offers_code(mtauburn, "73030")  # its own hospital file lists it
    afc = reg.sites["afc_watertown"]
    assert engine.offers_code(afc, "73030")  # its posted self-pay page
    sibling = next(s for s in reg.sites.values() if engine.chain_of.get(s.id) == "afc_urgent_care"
                   and s.id != "afc_watertown" and not s.cash_prices)  # fmt: skip
    assert engine.offers_code(sibling, "73030")  # R12: the chain's posted page
    # imaging without a modality (a DPH licence) covers an X-ray, never an MRI
    assert engine._service_covers("imaging", "73030")
    assert not engine._service_covers("imaging", "73221")


def test_site_facts_are_evidence_only_when_agreed(tmp_path, engine):
    """X1: agreed / austin_reviewed claims count; disputed and missing do not; the files absent
    = no facts."""
    assert load_site_facts(tmp_path).steps == {}
    (tmp_path / "capabilities.yaml").write_text(yaml.safe_dump({"version": 1, "capabilities": {
        "physical_therapy": {"label": {"en": "PT", "zh": "PT"},
                             "covers": [{"path": SHOULDER, "step": "physical_therapy"}]},
        "xray": {"label": {"en": "X-ray", "zh": "X光"}, "covers": [{"path": SHOULDER,
                                                                  "step": "xray"}]},
    }}))  # fmt: skip
    ev = [{"url": "https://example.org", "quote": "We offer physical therapy",
           "fetched_at": "2026-10-25", "page_sha256": "0" * 64}]  # fmt: skip
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump({"version": 1, "sites": {
        "afc_watertown": {"capabilities": {
            "physical_therapy": {"value": "offered", "status": "agreed", "evidence": ev},
            "xray": {"value": "not_offered", "status": "disputed", "evidence": ev},
        }},
        "mount_auburn_hospital": {"capabilities": {
            "xray": {"value": "not_offered", "status": "austin_reviewed", "evidence": ev}}},
    }}))  # fmt: skip
    facts = load_site_facts(tmp_path)
    assert facts.step("afc_watertown", SHOULDER, "physical_therapy") == "offered"
    assert facts.step("afc_watertown", SHOULDER, "xray") is None  # disputed = unknown
    eng = Engine(engine.store, engine.reg)
    eng.facts = facts
    r = _q(eng, site_ids=["afc_watertown", "mount_auburn_hospital"])
    pt = _line(r, "afc_watertown", "physical_therapy")
    assert pt.availability == "offered"
    x = _line(r, "mount_auburn_hospital", "xray_facility")
    assert x.availability == "not_offered" and x.cell is None and not x.in_total
    assert x.availability_reason == "site_says_not_offered"


# --------------------------------------------------------------------------- 3: admission


def test_admission_needs_the_entry_visit_or_the_core_procedure(engine):
    """R8: a surgery center is not admitted to a shoulder path (no visit, no core procedure it
    can do), but is to colonoscopy; a site with only an anesthesia line never is."""
    shoulder, colon = engine.reg.paths[SHOULDER], engine.reg.paths["colon_screening_v1"]
    asc = engine.reg.sites[ASC]
    assert not engine._admits(asc, shoulder, {"ortho", "urgent_care", "gi"})
    assert engine._admits(asc, colon, engine.reg.path_areas(colon))
    eng = _engine_with(engine, admission_step_kinds={k: ["anesthesia"] for k in (
        "urgent_care", "office", "hospital_outpatient", "ambulatory_surgery_center")})  # fmt: skip
    bare = asc.model_copy(update={"offered": [], "hospital_entity_id": None})
    assert not eng._admits(bare, colon, eng.reg.path_areas(colon))


def test_new_chat2_paths_have_areas(engine):
    """Chat2 (P12): stomach ache and rash start at urgent care or a specialist."""
    areas = engine.reg.config["areas"]
    assert areas["gi_abdomen"] == ["urgent_care", "gi"]
    assert areas["skin_rash"] == ["urgent_care", "skin"]


# --------------------------------------------------------------------------- 4: TIN roles


def test_an_asc_tin_prices_the_facility_line_never_the_doctors(engine):
    """R3: at MGB Endoscopy Braintree (TIN 043306443, an ASC billing on the CMS-1500 form) the
    $2,038 Aetna row is the center's fee; the doctor line is not priced from it (it was, and
    anesthesia was estimated at 20.97x Medicare from it)."""
    assert engine._role(engine.reg.sites[ASC], "043306443") == "facility"
    r = _q(engine, AETNA_PPO, "colon_screening_v1", site_ids=[ASC])
    fac = _line(r, ASC, "colonoscopy_facility")
    doc = _line(r, ASC, "colonoscopy_doctor")
    assert fac.cell.kind == "money" and fac.cell.low == 2038.0
    assert fac.cell.prov.source_kind.value == "insurer_tic"
    assert not (doc.cell.kind == "money" and doc.cell.prov.source_kind.value == "insurer_tic")
    assert not doc.in_total and doc.estimate is None  # no doctor group linked, no ASC peers
    anes = _line(r, ASC, "anesthesia")
    assert not (anes.cell.kind == "money" and anes.cell.low > 1000)


# --------------------------------------------------------------------------- 5: estimator


def test_estimates_come_from_the_same_kind_and_payer_with_five_groups(engine, registry):
    """P5 / X2: an urgent care is never estimated from hospital rows: every estimate's cited
    rows belong to sites of the estimating site's kind, under the request's payer, with >= 5
    billing groups behind the range."""
    seen = 0
    for path in sorted(registry.paths):
        r = _q(engine, path=path, near=NEAR, max_sites=12)
        for sq in r.sites:
            for ln in sq.receipt.lines:
                if ln.estimate is None:
                    continue
                seen += 1
                assert ln.estimate.kind == sq.site.kind and ln.estimate.n_groups >= 5
                assert ln.estimate.payer_id == "BCBS_MA"
                site = registry.sites[sq.site.site_id]
                pmod = "26" if ln.modifier == "26" else ""
                peers, _ = engine._peers(site, ln.codes[0], ln.component, pmod,
                                         engine._context(QuoteRequest.model_validate({
                                             "payment": BCBS_HMO, "care_path_id": path,
                                             "answers": {}, "service_codes": [],
                                             "picked_by": "person", "site_ids": None}), AS_OF),
                                         estimate=True)  # fmt: skip
                assert len(peers) == ln.estimate.n_groups
                own = set(registry.site_tins(site))
                for _, ref in peers:  # never this site's own group, never another kind
                    assert getattr(ref, "tin", None) not in own
    assert seen > 0


def test_urgent_care_is_never_estimated_from_hospitals(engine, registry):
    """P5: drop every urgent-care peer (keep only hospitals) and an urgent care gets no
    estimate; the kind filter, not luck, keeps hospital prices out."""
    site = registry.sites["afc_urgent_care_cambridge_cambridge"]
    q = engine._context(QuoteRequest.model_validate({
        "payment": BCBS_HMO, "care_path_id": SHOULDER, "answers": {}, "service_codes": [],
        "picked_by": "person", "site_ids": None}), AS_OF)  # fmt: skip
    peers, _ = engine._peers(site, "99203", "professional", "", q, estimate=True)
    kinds = {engine._kind(registry.sites[s]) for s in engine._line_stats("99203", q)}
    assert "hospital_outpatient" in kinds  # hospitals do have 99203 doctor rows
    assert peers
    for _, ref in peers:
        owners = [sid for sid, per in engine._line_stats("99203", q).items()
                  if any(r is ref for ents in per.values() for _, _, r in ents)]  # fmt: skip
        # a fee-schedule row can be shared by several sites' TINs; it is in the set because an
        # urgent care has it, never because a hospital does
        assert any(engine._kind(registry.sites[s]) == "urgent_care" for s in owners)


def test_fewer_than_min_groups_means_no_estimate(engine):
    """P5: < 5 groups -> the Gap stays. Raising the minimum removes every estimate."""
    strict = _engine_with(engine, peers={**engine.peer_cfg, "min_groups": 10_000})
    r = _q(strict, near=NEAR)
    assert all(ln.estimate is None for sq in r.sites for ln in sq.receipt.lines)


# --------------------------------------------------------------------------- 6: ranking


def test_ties_break_by_distance_with_a_point(engine):
    r = _q(engine, near=NEAR, max_sites=20)
    keys = [(s.headline.missing, s.headline.comparable, s.distance_km) for s in r.sites]
    for a, b in zip(keys, keys[1:]):
        if a[:2] == b[:2]:
            assert a[2] <= b[2]


def test_comparable_uses_the_peer_median_for_estimates_and_elsewhere(engine):
    """P1 / P4: estimates and steps done elsewhere enter at the neutral median."""
    r = _q(engine, near=NEAR, max_sites=20)
    seen = 0
    for sq in r.sites:
        lines = {ln.line_id: ln for ln in sq.receipt.lines}
        for st in sq.steps:
            if st.figure == "elsewhere" and st.rank_value is not None:
                assert st.rank_value == st.elsewhere.median
                seen += 1
            if st.figure == "estimate" and st.rank_value is not None:
                est = [lines[i] for i in st.line_ids if lines[i].estimate]
                assert est and all(e.estimate.median <= e.estimate.high for e in est)
                seen += 1
    assert seen > 0


def test_a_step_done_elsewhere_shows_the_range_and_is_never_summed(engine):
    """P4: AFC does not show it does PT: the PT step's figure is 'elsewhere' (p25-p75 at sites
    that do, same payer), outside the total."""
    r = _q(engine, near=NEAR, max_sites=12)
    afc = next(s for s in r.sites if s.site.site_id.startswith("afc_"))
    pt = next(st for st in afc.steps if st.key == "physical_therapy")
    assert pt.availability == "unknown" and not pt.in_total
    if pt.figure == "elsewhere":
        assert pt.elsewhere.n_groups >= 5 and pt.elsewhere.payer_id == "BCBS_MA"
        assert (pt.low, pt.high) == (pt.elsewhere.low, pt.elsewhere.high)


# --------------------------------------------------------------------------- 7: chains


def test_a_chain_posted_price_applies_at_every_location(engine):
    """R12: AFC's posted self-pay page prices every AFC, and the line says whose page it is."""
    r = _q(engine, {"kind": "cash"}, near=NEAR, max_sites=12)
    afcs = [s for s in r.sites if s.site.chain_id == "afc_urgent_care"]
    assert afcs
    for sq in afcs:
        x = next(ln for ln in sq.receipt.lines if ln.line_id == "xray")
        assert x.cell.kind == "money" and x.cell.basis.value == "posted_self_pay"
        assert x.chain_price_from == ("afc_watertown" if sq.site.site_id != "afc_watertown"
                                      else None)  # fmt: skip


def test_chain_spread_is_flagged(engine):
    """R12: the same line under the same payer differing > 1.5x inside one chain is listed."""
    r = _q(engine, TUFTS_HMO, near=MILTON, max_sites=20)
    loose = _engine_with(engine, chain_spread_max=1.0001)
    r2 = _q(loose, TUFTS_HMO, near=MILTON, max_sites=20)
    assert ("chain_price_spread" in r.notices) == bool(r.chain_spreads)
    assert len(r2.chain_spreads) >= len(r.chain_spreads)
    for c in r2.chain_spreads:
        assert c.ratio > 1.0001 and c.high > c.low


# --------------------------------------------------------------------------- 8: unusual


def test_the_14_dollar_afc_tufts_visit_is_set_aside(engine):
    """P8 / R17: Tufts' $14 99203 row for DRX UC Watertown PC is under 1/3 of the urgent-care
    median: left out of the line (cited in set_aside), so the low end is a real rate."""
    r = _q(engine, TUFTS_HMO, "back_new_pain_v1", site_ids=[AFC_ARL])
    v = _line(r, AFC_ARL, "visit")
    assert v.unusual is not None and not v.unusual.whole_line
    assert [m.low for m in v.unusual.set_aside] == [14.0]
    assert v.cell.low > 14.0 and v.cell.low >= v.unusual.peer_median / 3
    assert v.in_total


def test_the_cha_5_dollar_colonoscopy_is_unusual_and_not_summed(engine):
    """P8 / R17: CHA's own Medicare row for 45378 is $5.04, against ~$1,000 at other
    hospitals: the whole line is unusual, shown, not summed."""
    r = _q(engine, {"kind": "medicare"}, "colon_diagnostic_v1", site_ids=[CHA])
    ln = _line(r, CHA, "colonoscopy_facility")
    assert ln.cell.kind == "money" and ln.cell.low == 5.04
    assert ln.unusual is not None and ln.unusual.whole_line and not ln.in_total
    assert ln.unusual.peer_median > 500
    reasons = {e.line_id: e.reason for e in _site(r, CHA).receipt.totals.excluded}
    assert reasons["colonoscopy_facility"] == "unusual"


# --------------------------------------------------------------------------- 10, 11, 12


def test_every_site_has_a_step_summary_for_the_map(engine):
    """P3: per step: availability, figure, low/high, estimated, unusual."""
    r = _q(engine, near=NEAR)
    path = engine.reg.paths[SHOULDER]
    for sq in r.sites:
        keys = [st.key for st in sq.steps]
        assert keys and set(keys) <= {s.id for s in path.steps}
        for st in sq.steps:
            if st.figure in ("own", "estimate"):
                assert st.availability == "offered" and st.low is not None


def test_unknown_billing_is_priced_as_a_hospital_clinic(engine, registry):
    """P9 / R7: billing_type unknown -> facility line + doctor line, never an office's one
    global line; the facility gap says it may charge a hospital facility fee."""
    sid = next(s.id for s in registry.sites.values() if s.billing_type == "unknown"
               and s.listing_status != "registry_only" and not s.children_only
               and "ortho" in s.service_areas)  # fmt: skip
    r = _q(engine, site_ids=[sid])
    lines = {ln.line_id: ln for ln in r.sites[0].receipt.lines}
    assert "visit_facility" in lines and "visit_doctor" in lines
    f = lines["visit_facility"].cell
    if f.kind == "not_published" and registry.sites[sid].hospital_entity_id is None:
        assert "may also charge" in f.what


def test_possible_steps_are_might_add_never_headline(engine):
    """P9: headline = certain + likely; possible steps show as might_add."""
    r = _q(engine, site_ids=["mount_auburn_hospital"])
    sq = r.sites[0]
    t = sq.receipt.totals
    poss = [st for st in sq.steps if st.likelihood in ("possible", "rare")]
    assert poss and not any(st.in_total for st in poss)
    if t.might_add:
        assert set(t.might_add.step_keys) <= {st.key for st in poss}
        assert t.might_add.low <= t.might_add.high


def test_anesthesia_shows_a_typical_time_note(engine):
    """Item 12: the base-units line stays; 'with typical time' = fee x (base + min/15)/base."""
    r = _q(engine, {"kind": "medicare"}, "colon_diagnostic_v1", site_ids=[CHA])
    ln = _line(r, CHA, "anesthesia")
    assert "price.anesthesia_base_units_only" in ln.price_notes
    t = ln.anesthesia_time
    assert t is not None and t.minutes == 57.22 and t.base_units == 4  # CMS CY2026 work time
    assert t.low == round(ln.cell.low * (4 + 57.22 / 15) / 4, 2) and "CMS" in t.source


# --------------------------------------------------------------------------- 13: crashes, fallbacks


def test_placeholder_npi_never_reaches_a_quote(engine, store):
    """R10: Aetna / Tufts files use NPI '0'; the pack drops it and the loader filters old packs.
    Tufts HMO near Milton (a 500 before) quotes."""
    assert not valid_npi("0") and valid_npi("1234567893")
    assert all(valid_npi(n) for v in store.npi_sets.values() for n in v)
    r = _q(engine, TUFTS_HMO, near=MILTON)
    assert r.sites


def test_server_refuses_the_test_extract_without_the_flag(monkeypatch):
    from app.quote.store import ExtractRefused, load_from_env

    monkeypatch.delenv("CARECOST_QUOTE_PACK", raising=False)
    monkeypatch.delenv("CARECOST_ALLOW_EXTRACT", raising=False)
    with pytest.raises(ExtractRefused, match="refusing"):
        load_from_env()
    monkeypatch.setenv("CARECOST_QUOTE_PACK", "/nonexistent/pack.sqlite")
    with pytest.raises(ExtractRefused, match="does not exist"):
        load_from_env()


def test_dockerfile_has_no_extract_fallback():
    text = (Path(__file__).resolve().parents[3] / "Dockerfile").read_text()
    assert "--from-extract" not in text and "exit 1" in text


def test_health_reports_build_rows_and_staleness(store, registry):
    from fastapi.testclient import TestClient

    from app.server import create_app

    with TestClient(create_app(store, registry=registry, today=lambda: AS_OF)) as c:
        h = c.get("/api/health").json()
    assert h["build_id"] == store.version.build_id
    assert sum(h["rows_by_kind"].values()) == h["rows"] and h["rows_by_source"]
    assert h["stale_on_our_side"] == [] and h["ok"] is True
    assert "late_to_refresh" in h and h["test_extract"] is False


# --------------------------------------------------------------------------- 14: labels


def test_self_pay_is_named_self_pay_no_insurance(engine):
    """P2: enum values stay ('cash'); the words a person reads say Self-pay (no insurance)."""
    r = _q(engine, {"kind": "cash"}, site_ids=KEY_SITES)
    assert (
        r.payment_label.en == "Self-pay (no insurance)" and r.payment_label.zh == "自费（无保险）"
    )
    whats = [ln.cell.what for sq in r.sites for ln in sq.receipt.lines
             if ln.cell is not None and ln.cell.kind == "not_published"]  # fmt: skip
    assert not any("(cash)" in w for w in whats)


def test_two_primary_codes_in_one_step_get_their_own_lines(engine, registry):
    """Chat2: a step may list two primary codes under one payment; each gets its own line id."""
    from app.care_paths.models import CptRef

    path = registry.paths["colon_screening_v1"]
    st = next(s for s in path.steps if s.id == "colonoscopy")
    both = [c.model_copy(update={"payer_scope": "all"}) if isinstance(c, CptRef) else c
            for c in st.cpts]  # fmt: skip
    p2 = path.model_copy(
        update={
            "steps": [
                s.model_copy(update={"cpts": both}) if s.id == "colonoscopy" else s
                for s in path.steps
            ]
        }
    )
    eng = Engine(engine.store, engine.reg)
    q = eng._context(QuoteRequest.model_validate({
        "payment": BCBS_HMO, "care_path_id": "colon_screening_v1", "answers": {},
        "service_codes": [], "picked_by": "person", "site_ids": None}), AS_OF)  # fmt: skip
    stems = [it.stem for it in eng._path_items(p2, q) if it.step_id == "colonoscopy"]
    assert len(stems) == len(set(stems)) == 2


@pytest.mark.skipif(not os.environ.get("CARECOST_QUOTE_PACK"), reason="real pack not built here")
def test_real_pack_no_location_shoulder_quotes(registry):  # pragma: no cover
    from app.quote.store import load_pack

    store = load_pack(Path(os.environ["CARECOST_QUOTE_PACK"]), tins=registry.tins,
                      census_ids=registry.census_ids)  # fmt: skip
    r = _q(Engine(store, registry))
    assert r.ordering == "kind_then_distance" and len(r.sites) > 100
