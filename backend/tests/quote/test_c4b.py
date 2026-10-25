"""Stream C4b: what a sick person reads first (Austin 2026-10-25) and the aggregation fixes.

One test per rule, on the committed extract (real rows recorded by ``app.quote.fixtures_gen``),
plus small synthetic additions where the extract has no example yet (ER codes before A7, a flat
visit rate under BCBS). Every synthetic row is a copy of a real extract row with one field
changed, so its provenance still resolves."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.quote.contracts import QuoteRequest, QuoteResponse
from app.quote.engine import Engine, code_class
from app.quote.store import RateStore
from tests.quote.conftest import AS_OF

BCBS_HMO = {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None}
CASH = {"kind": "cash"}
STOMACH, RASH = "stomach_ache_v1", "rash_v1"
AFC_ARL = "afc_urgent_care_arlington_arlington"
NEAR = {"lat": 42.3736, "lon": -71.119}


def _q(engine, payment=BCBS_HMO, path=STOMACH, **where):
    body = {"payment": payment, "care_path_id": path, "answers": {}, "service_codes": [],
            "picked_by": "person", "site_ids": None}  # fmt: skip
    body.update(where)
    return engine.quote(QuoteRequest.model_validate(body), AS_OF)


def _site(r, sid):
    return next(s for s in r.sites if s.site.site_id == sid)


def _store(store: RateStore, extra=(), drop=lambda r: False, flags=None, codes=()) -> RateStore:
    return RateStore(
        rows=[r for r in store.rows if not drop(r)] + list(extra), sources=store.sources,
        version=store.version, codes=store.codes | frozenset(codes), npi_sets=store.npi_sets,
        census_tins=store.census_tins, flags={**store.flags, **(flags or {})},
    )  # fmt: skip


def _json(r):
    return r.model_dump(mode="json")


# --------------------------------------------------------------------------- 1: headline range


def test_headline_range_is_certain_and_likely_steps_only(engine):
    """Austin 2026-10-25: the range covers the certain and likely steps (own price or the
    elsewhere range); low = the sum of their lows, high = the sum of their highs. Possible steps
    are listed apart (may_also_order), never in the range."""
    r = _q(engine, near=NEAR)
    checked = 0
    for sq in r.sites:
        hr = sq.headline_range
        if hr is None:
            continue
        by = {st.key: st for st in sq.steps}
        for k in hr.with_likely.step_keys:
            assert by[k].likelihood in ("certain", "likely")
        assert {m.step_key for m in hr.may_also_order} == {
            st.key for st in sq.steps if st.likelihood in ("possible", "rare")
        }
        lo = hr.visit_only.low + sum(by[k].low for k in hr.with_likely.step_keys)
        hi = hr.visit_only.high + sum(by[k].high for k in hr.with_likely.step_keys)
        assert (hr.low, hr.high) == (round(lo, 2), round(hi, 2))
        assert hr.includes == [by[k].plain_name for k in hr.with_likely.step_keys]
        assert hr.with_possible.high >= hr.high
        checked += 1
    assert checked >= 5
    assert any("Urine test" in sq.headline_range.includes for sq in r.sites if sq.headline_range)


def test_headline_contract_refuses_a_possible_step_in_the_range(engine):
    r = _json(_q(engine, near=NEAR))
    sq = next(s for s in r["sites"] if s["headline_range"] and s["headline_range"]["may_also_order"]
              and s["headline_range"]["may_also_order"][0]["low"] is not None)  # fmt: skip
    hr = sq["headline_range"]
    m = hr["may_also_order"][0]
    for key in ("with_likely",):
        hr[key]["step_keys"].append(m["step_key"])
        hr[key]["includes"].append(m["plain_name"])
        hr[key]["low"] = round(hr[key]["low"] + m["low"], 2)
        hr[key]["high"] = round(hr[key]["high"] + m["high"], 2)
    hr["low"], hr["high"], hr["includes"] = (hr["with_likely"]["low"], hr["with_likely"]["high"],
                                             list(hr["with_likely"]["includes"]))  # fmt: skip
    with pytest.raises(ValidationError, match="only certain / likely"):
        QuoteResponse.model_validate(r)
    r2 = _json(_q(engine, near=NEAR))
    s2 = next(s for s in r2["sites"] if s["headline_range"])
    s2["headline_range"]["with_likely"]["high"] += 10
    s2["headline_range"]["high"] += 10
    s2["headline_range"]["with_possible"]["high"] += 10
    with pytest.raises(ValidationError, match="visit \\+ steps"):
        QuoteResponse.model_validate(r2)


def test_exclusive_group_counts_only_the_dearest_member_in_with_possible(engine):
    r = _q(engine, near=NEAR)
    seen = 0
    for sq in r.sites:
        hr = sq.headline_range
        if hr is None:
            continue
        by = {st.key: st for st in sq.steps}
        imaging = [k for k in ("belly_ultrasound", "belly_ct") if by[k].low is not None]
        if len(imaging) < 2:
            continue
        counted = [k for k in imaging if k in hr.with_possible.step_keys]
        assert len(counted) == 1
        assert by[counted[0]].high == max(by[k].high for k in imaging)
        other = next(k for k in imaging if k not in counted)
        assert by[other].plain_name in hr.with_possible.alternatives
        seen += 1
    assert seen >= 3


def test_self_pay_hospital_visit_says_from_and_the_doctor_bills_separately(engine):
    r = _q(engine, CASH, "shoulder_acute_injury_v1", site_ids=["mount_auburn_hospital"])
    hr = _site(r, "mount_auburn_hospital").headline_range
    assert hr.from_only and hr.note_keys == ["headline.doctor_bills_separately"]
    assert hr.visit_only.low == 203.0  # Mount Auburn's posted self-pay clinic fee (facility)


# --------------------------------------------------------------------------- 2: options A / B


def test_rash_options_give_each_site_one_first_visit(engine):
    r = _q(engine, path=RASH, near=NEAR)
    assert [o.id for o in r.options] == ["a", "b"] and all(o.priced for o in r.options)
    for sq in r.sites:
        keys = {st.key for st in sq.steps}
        if sq.option_id == "a":
            assert "skin_doctor_visit" not in keys and "visit" in keys
        else:
            assert "visit" not in keys and "skin_doctor_visit" in keys
            st = next(s for s in sq.steps if s.key == "skin_doctor_visit")
            assert st.likelihood == "certain"
    kinds = {sq.option_id: sq.site.kind for sq in r.sites}
    assert kinds.get("a") == "urgent_care"


def test_afc_no_longer_shows_its_visit_twice_on_rash(engine):
    """Before C4b AFC's own $135.61 BCBS visit was the visit line and the skin-doctor line."""
    r = _q(engine, path=RASH, site_ids=[AFC_ARL])
    sq = _site(r, AFC_ARL)
    assert sq.option_id == "a"
    assert [ln.step_id for ln in sq.receipt.lines].count("skin_doctor_visit") == 0


def test_stomach_gi_option_is_listed_unpriced_and_has_no_sites(engine):
    r = _q(engine)
    b = next(o for o in r.options if o.id == "b")
    assert not b.priced and b.missing_reason and b.site_count == 0 and b.low is None
    assert all(sq.option_id == "a" for sq in r.sites)
    gi = {s for s in r.sites_without_service if "gi" in engine.reg.sites[s].service_areas
          and engine.option_of(engine.reg.sites[s], engine.reg.paths[STOMACH]) is b}  # fmt: skip
    assert not gi  # an unpriced option's sites are not "without the service"


def test_option_ranges_and_cheapest_site(engine):
    r = _q(engine, path=RASH)
    for o in r.options:
        mine = [sq for sq in r.sites if sq.option_id == o.id and sq.headline_range]
        assert o.low == min(sq.headline_range.low for sq in mine)
        assert o.high == max(sq.headline_range.high for sq in mine)
        best = min(mine, key=lambda sq: (sq.headline_range.low, sq.distance_km, sq.site.site_id))
        assert o.cheapest_site_id == best.site.site_id
    doc = _json(r)
    other = next(s for s in doc["sites"] if s["option_id"] == "a" and s["headline_range"]
                 and s["site"]["site_id"] != doc["options"][0]["cheapest_site_id"])  # fmt: skip
    doc["options"][0]["cheapest_site_id"] = other["site"]["site_id"]
    with pytest.raises(ValidationError, match="cheapest_site_id"):
        QuoteResponse.model_validate(doc)


def test_ordering_within_an_option_is_distance_by_default_or_price(engine):
    r = _q(engine, path=RASH, near=NEAR)
    assert r.ordering == "option_then_distance"
    r2 = _q(engine, path=RASH, near=NEAR, order_by="price")
    assert r2.ordering == "option_then_price"
    doc = _json(r)
    a = [i for i, s in enumerate(doc["sites"]) if s["option_id"] == "a"]
    doc["sites"][a[0]], doc["sites"][a[1]] = doc["sites"][a[1]], doc["sites"][a[0]]
    with pytest.raises(ValidationError, match="option_then_distance"):
        QuoteResponse.model_validate(doc)


def test_hmo_referral_for_a_specialist_option_is_a_top_notice(engine):
    hmo = {"Q14": ["hmo_referral_required"]}
    assert "hmo_referral_for_specialist" in _q(engine, path=RASH, answers=hmo, near=NEAR).notices
    assert "hmo_referral_for_specialist" not in _q(engine, path=RASH, near=NEAR).notices
    # stomach's specialist option (GI) is not priced: no sites, no notice
    assert "hmo_referral_for_specialist" not in _q(engine, answers=hmo, near=NEAR).notices


# --------------------------------------------------------------------------- 3: aggregation


def test_lab_codes_have_no_doctor_fee_line_cms_pctc(engine):
    """3a: CMS PC/TC indicator 9 (clinical labs): a hospital prices the facility line only."""
    assert {engine.pctc[c] for c in ("81003", "81025", "85025", "80053", "87220")} == {"9"}
    r = _q(engine)
    two_part = [
        sq for sq in r.sites if sq.receipt and sq.site.billing_type == "hospital_outpatient"
    ]
    assert two_part
    for sq in two_part:
        for ln in sq.receipt.lines:
            if code_class(ln.codes[0]) == "lab":
                assert ln.component == "facility", ln.line_id


def test_no_medicare_figure_for_a_non_medicare_payment(engine):
    """3d: no rung 7, and no Medicare fee-schedule number at all, for BCBS / self-pay /
    MassHealth quotes."""
    for pay in (BCBS_HMO, CASH, {"kind": "masshealth"}):
        for path in ("shoulder_chronic_clicking_v1", STOMACH, RASH):
            r = _q(engine, pay, path, near=NEAR)
            for sq in r.sites:
                for ln in sq.receipt.lines:
                    assert not (ln.doctor_fee and ln.doctor_fee.rung == 7)
                    c = ln.cell
                    if hasattr(c, "prov"):
                        assert c.prov.source_kind.value not in ("medicare_pfs", "medicare_opps",
                                                                "medicare_asc")  # fmt: skip


def test_self_pay_unknown_lines_do_not_say_your_insurer(engine):
    """3e: an insurer file listing a rate is 'price_file_lists_rate' for a self-pay person."""
    reasons = set()
    for path in ("shoulder_chronic_clicking_v1", STOMACH):
        r = _q(engine, CASH, path, near=NEAR)
        reasons |= {ln.availability_reason for sq in r.sites for ln in sq.receipt.lines}
    assert "insurer_lists_rate" not in reasons and "price_file_lists_rate" in reasons
    ins = _q(engine, BCBS_HMO, STOMACH, near=NEAR)
    assert "price_file_lists_rate" not in {ln.availability_reason for sq in ins.sites
                                           for ln in sq.receipt.lines}  # fmt: skip


# --------------------------------------------------------------------------- 4: A6 TiC flags


def _priced_tic_line(r, component="professional"):
    for sq in r.sites:
        for ln in sq.receipt.lines:
            c = ln.cell
            if (hasattr(c, "prov") and c.prov.source_kind.value == "insurer_tic"
                    and ln.estimate is None and ln.component == component
                    and not ln.price_notes and c.low == c.high):  # fmt: skip
                return sq.site.site_id, ln
    raise AssertionError("no TiC-priced line")


def test_same_npi_multi_rate_is_marked_on_the_line(engine, store, registry):
    sid, ln = _priced_tic_line(_q(engine, near=NEAR))
    uid = f"{ln.cell.prov.source_id}:{ln.cell.prov.row_id}"
    eng = Engine(_store(store, flags={uid: frozenset({"same_npi_pos_multi_rate"})}), registry)
    again = next(x for x in _site(_q(eng, near=NEAR), sid).receipt.lines if x.line_id == ln.line_id)
    assert "price.several_rates_same_doctors" in again.price_notes


def test_institutional_row_on_a_physician_npi_is_never_a_fee(engine, store, registry):
    sid, ln = _priced_tic_line(_q(engine, near=NEAR))
    p = ln.cell.prov
    eng = Engine(_store(store, flags={f"{p.source_id}:{p.row_id}": frozenset(
        {"institutional_on_physician_npi"})}), registry)  # fmt: skip
    again = next(x for x in _site(_q(eng, near=NEAR), sid).receipt.lines if x.line_id == ln.line_id)
    assert not (hasattr(again.cell, "prov") and again.cell.prov.row_id == p.row_id)


def test_anesthesia_per_unit_flag_is_never_a_whole_price(engine, store, registry):
    """A6 flags a per-unit anesthesia rate even when this pack has no twin code to show it (the
    twin may sit in another network file). Flagged: an anesthesia group's rate prices the base
    units (rate x units); another group's is not a fee. Unflagged, the same row is a whole fee."""
    base = next(x for x in store.rows if x.source_kind == "insurer_tic")
    mk = lambda name, tin: replace(  # noqa: E731
        base, code="00812", amount=20.98, business_name=name, tin=tin,
        row_id=f"{'b' * 16}:{tin[-1]}", modifiers="", negotiated_type="negotiated")  # fmt: skip
    anes, other = mk("BOSTON ANESTHESIA LLC", "999999993"), mk("SKIN CLINIC PC", "999999994")
    plain = Engine(_store(store, [anes, other]), registry)
    rows, value, method = plain._anesthesia_units([anes], "00812")
    assert rows == [anes] and method is None and value(anes) == 20.98  # no flag, no twin: whole
    flags = {a.uid: frozenset({"anesthesia_per_unit"}) for a in (anes, other)}
    eng = Engine(_store(store, [anes, other], flags=flags), registry)
    rows, value, method = eng._anesthesia_units([anes], "00812")
    assert method.value == "per_unit_x_base_units" and value(anes) == round(20.98 * 3, 2)
    rows, _, method = eng._anesthesia_units([other], "00812")
    assert rows == [] and method is None


# --------------------------------------------------------------------------- 5: flat visit rate


def _flat_store(engine, store):
    """AFC Arlington's own BCBS visit row, copied onto the urine test code at the same amount:
    the insurer pays the place one amount per visit (the Tufts / ConvenientMD shape)."""
    r = _q(engine, site_ids=[AFC_ARL])
    v = next(ln for ln in _site(r, AFC_ARL).receipt.lines if ln.step_id == "visit")
    p = v.cell.prov
    row = next(x for x in store.rows if x.source_id == p.source_id and x.row_id == p.row_id)
    twin = replace(
        row,
        code="81003",
        row_id=row.row_id.split(":")[0] + ":99999",
        stage_row=row.stage_row + 10**7,
    )
    own = set(engine.reg.site_tins(engine.reg.sites[AFC_ARL]))
    return _store(store, [twin], drop=lambda x: x.code == "81003" and x.tin in own), row.amount


def test_flat_visit_rate_is_counted_once_on_the_visit(engine, store, registry):
    st, amount = _flat_store(engine, store)
    eng = Engine(st, registry)
    sq = _site(_q(eng, site_ids=[AFC_ARL]), AFC_ARL)
    urine = next(ln for ln in sq.receipt.lines if ln.step_id == "urine_test")
    assert urine.cell.low == amount and not urine.in_total
    assert urine.price_notes == ["price.flat_visit_rate"] and urine.unusual is None
    assert {"line_id": urine.line_id, "reason": "flat_visit_rate"} in [
        e.model_dump() for e in sq.receipt.totals.excluded
    ]
    st_u = next(s for s in sq.steps if s.key == "urine_test")
    assert st_u.flat_visit_rate and (st_u.low, st_u.high) == (0, 0) and not st_u.missing
    visit = next(s for s in sq.steps if s.key == "visit")
    assert sq.headline_range.low == visit.low  # the test adds $0


def test_flat_visit_rate_is_never_summed_by_the_contract_level_rule(engine, store, registry):
    """P8a sums a gated line when its group is consistently far from peers; a flat line is never
    gated, so P8a can never sum the visit amount a second time."""
    st, _ = _flat_store(engine, store)
    reg = copy.copy(registry)
    reg.config = {**registry.config, "outliers": {**registry.config["outliers"],
                  "contract_level": {"min_codes": 0, "high": 0.0, "low": 99.0}}}  # fmt: skip
    eng = Engine(st, reg)
    urine = next(ln for ln in _site(_q(eng, site_ids=[AFC_ARL]), AFC_ARL).receipt.lines
                 if ln.step_id == "urine_test")  # fmt: skip
    assert not urine.in_total
    assert not any(n.startswith("price.group_consistently") for n in urine.price_notes)


# --------------------------------------------------------------------------- 6: lab admission


def test_a_lab_code_pick_admits_urgent_care(engine):
    body = {"payment": BCBS_HMO, "care_path_id": None, "answers": {}, "service_codes": ["81003"],
            "picked_by": "person", "site_ids": None}  # fmt: skip
    r = engine.quote(QuoteRequest.model_validate(body), AS_OF)
    assert any(sq.site.kind == "urgent_care" for sq in r.sites)
    assert "urgent_care" in engine.reg.code_areas("81003")
    assert "urgent_care" not in engine.reg.code_areas("88305")  # pathology is not a clinic lab


# --------------------------------------------------------------------------- 7: ER reference


def test_er_reference_is_not_loaded_until_the_ed_codes_are_in_the_pack(engine):
    er = _q(engine, near=NEAR).er_reference
    assert er.status == "not_loaded" and er.low is None and not er.hospitals
    assert er.note_key == "er.visit_alone_costs_more"


def test_er_reference_on_synthetic_ed_rows(engine, store, registry):
    """A small synthetic fixture until A7's ED codes land: Mount Auburn's own BCBS clinic visit
    rows re-coded as ED levels 3 and 5 (x2 and x4), with the real rows' provenance."""
    base = [r for r in store.rows if r.source_id == "mtauburn_mrf" and r.payer_id == "BCBS_MA"
            and r.code == "99203" and r.amount is not None and r.component == "facility"]  # fmt: skip
    assert base
    extra = []
    for code, x in (("99283", 2), ("99285", 4)):
        extra += [replace(r, code=code, amount=round(r.amount * x, 2), row_id=f"{r.row_id}{code}",
                          stage_row=r.stage_row + 10**7 * x) for r in base]  # fmt: skip
    eng = Engine(_store(store, extra, codes={"99283", "99284", "99285"}), registry)
    r = _q(eng, near=NEAR)
    er = r.er_reference
    assert er.status == "priced" and len(er.hospitals) == 3
    ma = next((h for h in er.hospitals if h.site_id == "mount_auburn_hospital"), None)
    assert ma is not None
    lv3 = next(lv for lv in ma.levels if lv.code == "99283")
    assert lv3.facility.kind == "money" and lv3.facility.low == round(
        min(b.amount for b in base) * 2, 2
    )
    assert er.low <= lv3.facility.low and er.high >= lv3.facility.high
    for sq in r.sites:  # never a site's price, never ranked
        assert all(
            c not in ("99283", "99284", "99285") for ln in sq.receipt.lines for c in ln.codes
        )


# --------------------------------------------------------------------------- 8: contract fields


def test_step_plain_name_and_chain_name(engine):
    r = _q(engine, site_ids=[AFC_ARL])
    sq = _site(r, AFC_ARL)
    assert sq.site.chain_name == "AFC Urgent Care"
    assert {st.key: st.plain_name for st in sq.steps}["urine_test"] == "Urine test"


# --------------------------------------------------------------------------- completeness basis


def _fake(sid, low, basis, km):
    sub = {"low": low, "high": low + 50, "includes": ["Urine test"]}
    return {"option_id": "a", "distance_km": km, "site": {"site_id": sid},
            "headline_range": {"low": low, "high": low + 50, "basis": basis, "visit_only": sub,
                               "with_likely": sub, "with_possible": sub}}  # fmt: skip


def test_cheapest_prefers_a_complete_price_over_a_cheaper_partial_one(engine):
    """main 2026-10-25: AFC's complete $179 (provider fee included) beats CHA's partial $149
    (facility fee, the doctor bills separately); an estimate sits between the two."""
    a = engine.reg.paths[STOMACH].entry_options[0]
    afc, cha = _fake("afc_x", 179.0, "complete", 5.0), _fake("cha_x", 149.0, "partial", 1.0)
    est = _fake("est_x", 160.0, "includes_estimate", 2.0)
    o = engine._option_summary(a, [cha, afc])
    assert (o["cheapest_site_id"], o["cheapest_basis"]) == ("afc_x", "complete")
    o = engine._option_summary(a, [cha, est])
    assert (o["cheapest_site_id"], o["cheapest_basis"]) == ("est_x", "includes_estimate")
    o = engine._option_summary(a, [cha])
    assert (o["cheapest_site_id"], o["cheapest_basis"]) == ("cha_x", "partial")


def test_headline_basis_is_derived_and_cheapest_uses_the_best_basis(engine):
    r = _q(engine, CASH)  # self-pay stomach: today every priced site is a 'from' figure
    a = r.options[0]
    for sq in r.sites:
        hr = sq.headline_range
        if hr is not None:
            want = "partial" if hr.from_only or hr.with_likely.not_priced else (
                "includes_estimate" if hr.with_likely.estimated else "complete")  # fmt: skip
            assert hr.basis == want
    assert a.cheapest_basis == _site(r, a.cheapest_site_id).headline_range.basis
    doc = _json(_q(engine, path=RASH))
    sq = next(s for s in doc["sites"] if s["headline_range"])
    sq["headline_range"]["basis"] = "partial" if sq["headline_range"]["basis"] != "partial" else (
        "complete")  # fmt: skip
    with pytest.raises(ValidationError, match="basis is derived"):
        QuoteResponse.model_validate(doc)


def test_price_ordering_never_puts_a_partial_figure_above_a_complete_one(engine):
    from app.quote.contracts import BASIS_RANK

    r = _q(engine, path=RASH, order_by="price")
    for oid in ("a", "b"):
        mine = [sq for sq in r.sites if sq.option_id == oid]
        ranks = [BASIS_RANK[sq.headline_range.basis] if sq.headline_range else 3 for sq in mine]
        assert ranks == sorted(ranks)
    doc = _json(r)
    idx = [i for i, s in enumerate(doc["sites"]) if s["option_id"] == "a"]
    first, last = idx[0], idx[-1]  # the last of option A (worst basis or dearest) moved first
    doc["sites"][first], doc["sites"][last] = doc["sites"][last], doc["sites"][first]
    with pytest.raises(ValidationError, match="option_then_price"):
        QuoteResponse.model_validate(doc)


def test_offered_unpriced_step_is_an_estimate_not_partial(engine, store, registry):
    """main 2026-10-25: AFC Watertown's posted self-pay visit ($179, provider fee included; the
    codes A7 adds to its curated cash_prices, patched here) with an urine test it offers but
    prices nowhere on its page, vs CHA Somerville's 'from $149' (doctor bills separately) with a
    priced urine test. AFC's test takes the elsewhere range as an estimate: includes_estimate,
    not partial, so AFC is the cheapest even though CHA's low is lower."""
    reg = copy.copy(registry)
    reg.sites = dict(registry.sites)
    w = registry.sites["afc_watertown"]
    cp = [p.model_copy(update={"codes": ["99203", "99213"]}) if p.item_id ==
          "evaluation_consultation" else p for p in w.cash_prices]  # fmt: skip
    reg.sites["afc_watertown"] = w.model_copy(update={"cash_prices": cp})
    eng = Engine(store, reg)
    cha = "cha_somerville_urgent_care_center_somerville"
    r = _q(eng, CASH, site_ids=["afc_watertown", cha])
    afc_hr, cha_hr = _site(r, "afc_watertown").headline_range, _site(r, cha).headline_range
    urine = next(st for st in _site(r, "afc_watertown").steps if st.key == "urine_test")
    assert (urine.availability, urine.figure, urine.estimated) == (
        "offered",
        "elsewhere_estimate",
        True,
    )
    assert not urine.in_total and not urine.missing
    assert afc_hr.visit_only.low == 179.0 and afc_hr.basis == "includes_estimate"
    assert cha_hr.from_only and cha_hr.basis == "partial" and cha_hr.low < afc_hr.low
    assert (r.options[0].cheapest_site_id, r.options[0].cheapest_basis) == (
        "afc_watertown",
        "includes_estimate",
    )
