"""Round C4c: engine fixes found by D6's real-data checks (main traced each on c4b_a7.sqlite).

One test per item, on the committed extract (real rows recorded by ``app.quote.fixtures_gen``)."""

from __future__ import annotations

import pytest

from app.quote.contracts import QuoteRequest
from tests.quote.conftest import AS_OF

BCBS_HMO = {"kind": "insurance", "payer_id": "BCBS_MA", "product": "HMO", "network": None}
BCBS_PPO = {**BCBS_HMO, "product": "PPO"}
AETNA_PPO = {"kind": "insurance", "payer_id": "AETNA", "product": "PPO", "network": None}
CASH = {"kind": "cash"}
COLON = "colon_screening_v1"
NEAR = {"lat": 42.3736, "lon": -71.119}
CHA_SOM = "cha_somerville_urgent_care_center_somerville"
CHA = "cha_cambridge_hospital"
ASC = "mass_general_brigham_endoscopy_clinic_braintree"


def _q(engine, payment=BCBS_HMO, path=COLON, **where):
    body = {"payment": payment, "care_path_id": path, "answers": {}, "service_codes": [],
            "picked_by": "person", "site_ids": None}  # fmt: skip
    body.update(where)
    return engine.quote(QuoteRequest.model_validate(body), AS_OF)


def _site(r, sid):
    return next(s for s in r.sites if s.site.site_id == sid)


def _step(sq, key):
    return next(st for st in sq.steps if st.key == key)


# --------------------------------------------------------------------------- 1


def test_colonoscopy_headline_is_built_on_the_certain_procedure(engine):
    """Item 1: the colonoscopy path's layer-1 step (a pre-procedure consult) is possible: never
    the headline's base; it is listed in may_also_order like any possible step."""
    r = _q(engine, near=NEAR)
    ranged = [sq for sq in r.sites if sq.headline_range]
    assert ranged
    for sq in ranged:
        hr = sq.headline_range
        assert hr.visit_step_keys == ["colonoscopy"]
        assert "pre_procedure_consult" in {m.step_key for m in hr.may_also_order}
        assert "pre_procedure_consult" not in hr.with_likely.step_keys


# --------------------------------------------------------------------------- 2


def test_anesthesia_is_done_wherever_its_colonoscopy_is(engine):
    """Item 2: anesthesia travels_with the colonoscopy (care path): offered wherever the
    colonoscopy is, so it is never left 'unknown' at a site that does the procedure."""
    r = _q(engine, near=NEAR)
    for sq in r.sites:
        if _step(sq, "colonoscopy").availability == "offered":
            assert _step(sq, "anesthesia").availability == "offered", sq.site.site_id


def test_anesthesia_estimate_from_the_payers_own_anesthesia_groups(engine):
    """Item 2: no anesthesia rate here or at peer sites -> the payer's anesthesia groups'
    per-unit rates x (base units + typical minutes / 15), p25-p75, marked estimate with the
    typical-time note. Aetna publishes such rates; BCBS publishes none (stays without figure)."""
    r = _q(engine, AETNA_PPO, site_ids=[ASC])
    ln = next(x for x in _site(r, ASC).receipt.lines if x.step_id == "anesthesia")
    assert ln.estimate is not None and ln.estimate.scope == "payer_network"
    assert ln.estimate.payer_id == "AETNA" and ln.estimate.n_groups >= 5
    assert "price.anesthesia_typical_time" in ln.price_notes
    assert "price.anesthesia_base_units_only" not in ln.price_notes
    t = engine.anes_time["00812"]
    factor = engine.anes_base["00812"] + t["minutes"] / 15
    low_row = next(x for x in engine.store.rows if x.uid ==
                   f"{ln.cell.prov.source_id}:{ln.cell.prov.row_id}")  # fmt: skip
    assert ln.cell.low == round(low_row.amount * factor, 2)
    assert _step(_site(r, ASC), "anesthesia").figure == "estimate"
    b = _q(engine, BCBS_HMO, site_ids=[ASC])
    assert _step(_site(b, ASC), "anesthesia").figure == "none"


# --------------------------------------------------------------------------- 3


def test_a_procedure_path_lists_sites_by_its_core_procedure(engine):
    """Item 3: an office that only offers the optional consult is not a colonoscopy site."""
    r = _q(engine)
    assert r.sites and not [sq for sq in r.sites if sq.site.kind == "office"]
    for sq in r.sites:
        assert sq.site.kind in ("hospital_outpatient", "ambulatory_surgery_center")


def test_a_path_without_options_gets_one_implicit_option(engine):
    for path in (COLON, "shoulder_chronic_clicking_v1"):
        r = _q(engine, path=path, near=NEAR)
        assert len(r.options) == 1 and r.options[0].implicit
        assert all(sq.option_id == "a" for sq in r.sites)
        assert r.ordering == "rank"  # the list keeps its ordering
        o = r.options[0]
        assert o.cheapest_site_id is not None and o.cheapest_basis is not None


# --------------------------------------------------------------------------- 4


def _fake(sid, low, basis, km):
    sub = {"low": low, "high": low + 50, "includes": ["Urine test"]}
    return {"option_id": "a", "distance_km": km, "site": {"site_id": sid},
            "headline_range": {"low": low, "high": low + 50, "basis": basis, "visit_only": sub,
                               "with_likely": sub, "with_possible": sub}}  # fmt: skip


def test_option_range_comes_from_the_best_basis_present(engine):
    """Item 4: 小周's option A read '$149-$207 across 4 places', $149 being a 'from' figure."""
    a = engine.reg.paths["stomach_ache_v1"].entry_options[0]
    sites = [_fake("cha", 149.0, "partial", 1.0), _fake("afc1", 193.0, "includes_estimate", 2.0),
             _fake("afc2", 193.0, "includes_estimate", 3.0)]  # fmt: skip
    o = engine._option_summary(a, sites)
    assert (o["low"], o["high"], o["basis"]) == (193.0, 243.0, "includes_estimate")
    assert o["partial_site_count"] == 1 and o["sites_by_basis"] == {
        "partial": 1,
        "includes_estimate": 2,
    }
    assert o["visit_only"]["low"] == 193.0


# --------------------------------------------------------------------------- 5, 6


def test_a_step_with_a_priced_hospital_bill_says_from(engine):
    """Item 5: CHA Somerville self-pay: the belly ultrasound / CT hospital bills are posted, the
    doctor's read has no public source: 'from $X', with the from flag in may_also_order."""
    sq = _site(_q(engine, CASH, "stomach_ache_v1", site_ids=[CHA_SOM]), CHA_SOM)
    m = {x.step_key: x for x in sq.headline_range.may_also_order}
    for k in ("belly_ultrasound", "belly_ct"):
        st = _step(sq, k)
        assert st.from_only and st.figure == "own" and st.low is not None and st.rank_value is None
        assert m[k].from_only and m[k].low == st.low


def test_cha_cambridge_visit_is_from_the_hospital_bill(engine):
    """Item 6: CHA Cambridge's visit hospital bill is a summed estimate, its doctor's bill is not
    published by BCBS: the visit is 'from $X' (doctor_bill_not_published), not 'no range'."""
    sq = _site(_q(engine, path="rash_v1", site_ids=[CHA]), CHA)
    hr = sq.headline_range
    assert hr is not None and hr.from_only and hr.basis == "partial"
    assert hr.note_keys == ["headline.doctor_bill_not_published"]
    assert _step(sq, hr.visit_step_keys[0]).from_only


# --------------------------------------------------------------------------- 7, 8, 9


def test_hours_from_the_sites_own_page(engine):
    r = _q(engine, path="rash_v1")
    got = [sq for sq in r.sites if sq.site.hours_label == "site_page_hours"]
    assert got
    for sq in got:
        h = sq.site.hours
        assert h.source == "operator_html" and h.weekly and h.source_url
        assert sq.site.site_id in engine.facts.hours


def test_hmo_without_a_q14_answer_gets_the_referral(engine):
    sq = _q(engine, near=NEAR).sites[0]
    assert "referral" in {st.key for st in sq.steps}
    assert "referral" not in {st.key for st in _q(engine, BCBS_PPO, near=NEAR).sites[0].steps}


@pytest.mark.parametrize("path", [COLON, "stomach_ache_v1", "rash_v1"])
def test_surface_words_never_say_facility_or_professional_fee(engine, path):
    """Item 9 (Austin): the words people read never say 'facility fee' / 'professional fee';
    technical_name keeps the term."""
    for pay in (BCBS_HMO, CASH, {"kind": "medicare"}):
        for sq in _q(engine, pay, path, near=NEAR).sites:
            for ln in sq.receipt.lines:
                words = [ln.plain_name, getattr(ln.cell, "what", "") or "",
                         getattr(ln.cell, "ask", "") or ""]  # fmt: skip
                for w in words:
                    assert "facility fee" not in w.lower() and "professional fee" not in w.lower()
