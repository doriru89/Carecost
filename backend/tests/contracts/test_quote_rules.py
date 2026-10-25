"""One negative test per quote/site/catalog contract rule (contract fix round, 2026-10-24).

Each test breaks one rule on a real fixture and expects the validator to refuse it. The mutation
table in the round's report lists, per rule, the test that fails when the rule is deleted.
"""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.quote import contracts as q
from app.sites import contracts as sites

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "contracts" / "fixtures"
# P1: the golden BCBS / cash quotes in contracts/fixtures are now real engine output. The negative
# rule tests below mutate the earlier hand-made quotes, kept here, because they carry shapes real
# P1 data does not produce (rung 7, by_npi, an AI Money line, not_offered, a stale source).
HANDMADE = Path(__file__).resolve().parent / "handmade"
CTX = {"allow_placeholders": True}
QUOTES = ("quote_bcbs_hmo_shoulder", "quote_cash_shoulder", "quote_medicare_shoulder")


def _fx(name: str, real: bool = False) -> dict:
    hand = HANDMADE / f"{name}.json"
    path = hand if hand.exists() and not real else FIX / f"{name}.json"
    doc = json.loads(path.read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return doc


def _ok(doc: dict) -> q.QuoteResponse:
    return q.QuoteResponse.model_validate(doc, context=CTX)


def _bad(doc: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _ok(doc)


def _site(doc: dict, site_id: str) -> dict:
    return next(s for s in doc["sites"] if s["site"]["site_id"] == site_id)


def _line(doc: dict, site_id: str, line_id: str) -> dict:
    return next(ln for ln in _site(doc, site_id)["receipt"]["lines"] if ln["line_id"] == line_id)


MA, BWH, FR, AFC = (
    "mount_auburn_hospital",
    "brigham_and_womens_hospital",
    "franciscan_childrens",
    "afc_watertown",
)


def test_fixtures_are_valid_starting_points():
    for n in QUOTES:
        _ok(_fx(n))
        q.QuoteResponse.model_validate(_fx(n, real=True), context=CTX)


# --------------------------------------------------------------------------- AI never in totals


def test_ai_suggested_money_line_is_never_summed():
    """An AI-picked service may show a deterministic price (P5), but never in the total."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    _line(doc, MA, "referral_visit")["ai_suggested"] = True  # certain + Money + in_total
    _bad(doc, "AI-suggested")


def test_assistant_picks_are_all_labelled_ai_suggested():
    doc = _fx("quote_bcbs_hmo_shoulder")
    doc["picked_by"] = "assistant"
    _bad(doc, "never a care path")
    doc["care_path"] = None
    doc["copy_keys"] = []
    _bad(doc, "every line the assistant picked is ai_suggested")


def test_assistant_cannot_request_a_care_path_quote():
    req = {
        "payment": {"kind": "cash"},
        "care_path_id": "shoulder_chronic_clicking_v1",
        "answers": {},
        "service_codes": [],
        "picked_by": "assistant",
        "site_ids": None,
    }
    with pytest.raises(ValidationError, match="assistant"):
        q.QuoteRequest.model_validate(req)


# --------------------------------------------------------------------------- chips = provenance


def test_every_number_needs_its_source_in_the_response():
    """M06/M08: the chip is prov.source_id; a number whose source is not listed is refused."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    el = _line(doc, FR, "xray_facility")["elsewhere"][0]["cell"]["prov"]
    el["source_id"] = "made_up_mrf"
    el["row_ref"] = el["row_ref"].replace("mtauburn_mrf", "made_up_mrf")
    _bad(doc, "not in sources")


def test_both_sides_of_a_conflict_need_their_source():
    """M07: a conflict shows both numbers, so both sources must be listed."""
    doc = _fx("quote_medicare_shoulder")
    b = _line(doc, BWH, "injection_doctor")["cell"]["b"]["prov"]
    old = b["source_id"]
    b["source_id"] = "made_up_pfs"
    b["row_ref"] = b["row_ref"].replace(old, "made_up_pfs")
    _bad(doc, "not in sources")


def test_a_tic_price_cannot_wear_a_hospital_chip():
    doc = _fx("quote_bcbs_hmo_shoulder")
    p = _line(doc, BWH, "visit_doctor")["cell"]["prov"]
    sha = doc["sources"] and _line(doc, BWH, "steroid_injection")["cell"]["prov"]["source_sha256"]
    p.update(source_id="brigham_mrf", source_sha256=sha, row_ref=f"brigham_mrf:{sha[:12]}:1")
    _bad(doc, "says insurer_tic but source brigham_mrf is hospital_mrf")


def test_sources_lists_only_what_is_used():
    doc = _fx("quote_bcbs_hmo_shoulder")
    doc["sources"]["mgh_mrf"] = copy.deepcopy(doc["sources"]["brigham_mrf"])
    _bad(doc, "unused")


# --------------------------------------------------------------------------- freshness per request


def test_freshness_is_computed_on_as_of_not_frozen_at_build():
    """Failure review F1 / challenger F4: 40 days without a refetch must read 'stale on our side'
    even though nobody rebuilt the data."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    later = date(2026, 10, 24) + timedelta(days=40)
    doc["as_of"] = later.isoformat()
    _bad(doc, "freshness is not what its inputs give")
    f = q.SourceInfo.model_validate(doc["sources"]["mtauburn_mrf"]).freshness
    assert not f.stale_on_our_side
    assert f.at(later).stale_on_our_side and not f.at(later).late_to_refresh


def test_our_data_page_freshness_is_computed_on_as_of():
    doc = _fx("quote_bcbs_hmo_shoulder")
    page = {"as_of": "2026-10-24", "sources": doc["sources"]}
    q.OurDataResponse.model_validate(page)
    page["sources"]["mtauburn_mrf"]["freshness"]["stale_on_our_side"] = True
    page["sources"]["mtauburn_mrf"]["freshness"]["late_to_refresh"] = False
    with pytest.raises(ValidationError, match="freshness"):
        q.OurDataResponse.model_validate(page)


def test_total_honesty_flags_are_derived():
    """Theater F03: includes_late_source / includes_stale_source must match the summed lines."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    _site(doc, BWH)["receipt"]["totals"]["likely"]["includes_late_source"] = False
    _bad(doc, "includes_late_source")
    doc = _fx("quote_cash_shoulder")
    _site(doc, AFC)["receipt"]["totals"]["likely"]["includes_stale_source"] = False
    _bad(doc, "includes_stale_source")


def test_tic_price_needs_a_tic_release_and_no_not_loaded_notice():
    doc = _fx("quote_bcbs_hmo_shoulder")
    doc["data_version"]["tic_release"] = None
    doc["notices"].append("tic_not_loaded")
    _bad(doc, "a TiC price needs data_version.tic_release")
    doc = _fx("quote_cash_shoulder")
    doc["notices"].append("tic_not_loaded")
    _bad(doc, "tic_not_loaded")


# --------------------------------------------------------------------------- payment <-> price


def test_bcbs_receipt_cannot_sum_a_medicare_rate():
    """Challenger F1/P1: rung 5 (Medicare's rate) in a BCBS total."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    ln = _line(doc, MA, "visit_doctor")
    ln["doctor_fee"].update(rung=5, explanation_key="fee.rung_5_medicare")
    _bad(doc, "rung 5 is not for insurance")


def test_rung_7_shows_only_the_medicare_reference():
    doc = _fx("quote_bcbs_hmo_shoulder")
    ln = _line(doc, MA, "visit_doctor")
    assert ln["doctor_fee"]["rung"] == 7
    ln["cell"] = copy.deepcopy(_line(doc, MA, "visit_facility")["cell"])  # a BCBS MRF rate
    del doc["sources"]["cms_pfs_rvu26d"]  # no other line uses the PFS file now
    _bad(doc, "rung 7 is the Medicare reference")


def test_bcbs_receipt_cannot_use_another_payers_rate():
    doc = _fx("quote_bcbs_hmo_shoulder")
    _line(doc, MA, "visit_facility")["cell"]["prov"]["payer_id"] = "AETNA"
    _bad(doc, "AETNA's rate, not BCBS_MA's")


def test_medicare_receipt_cannot_use_a_commercial_rate():
    doc = _fx("quote_medicare_shoulder")
    _line(doc, BWH, "steroid_injection")["cell"]["prov"]["payer_id"] = "BCBS_MA"
    _bad(doc, "BCBS_MA's rate, not MEDICARE's")


def test_cash_receipt_cannot_use_a_negotiated_rate():
    doc = _fx("quote_cash_shoulder")
    _line(doc, MA, "visit_facility")["cell"]["basis"] = "negotiated"
    _bad(doc, "is not a cash price")


def test_gross_charge_is_never_a_line_price():
    """Challenger P3/P4: the list price almost nobody pays, summed as 'what cash costs'."""
    doc = _fx("quote_cash_shoulder")
    _line(doc, MA, "visit_facility")["cell"]["basis"] = "gross"
    _bad(doc, "only ever list_price")
    doc = _fx("quote_cash_shoulder")
    _line(doc, MA, "visit_facility")["list_price"]["basis"] = "discounted_cash"
    _bad(doc, "list_price is the gross charge")


def test_you_pay_kind_matches_the_payment():
    doc = _fx("quote_bcbs_hmo_shoulder")
    _site(doc, MA)["receipt"]["totals"]["you_pay"]["kind"] = "medicare_20_percent"
    _bad(doc, "is not for insurance")


# --------------------------------------------------------------------------- I7 ranking


def test_sites_are_ranked_by_missing_steps_then_comparable():
    """C3 I7: with a point, by (missing steps, comparable figure)."""
    doc = _fx("quote_bcbs_hmo_shoulder", real=True)
    assert doc["ordering"] == "rank"
    keys = [(s["headline"]["missing"], s["headline"]["comparable"]) for s in doc["sites"]]
    assert len(set(keys)) > 1
    doc["sites"] = doc["sites"][::-1]
    _bad(doc, "rank_key")


def test_no_location_list_is_grouped_by_kind_then_distance():
    """C3 P7: no point -> by kind of site, then distance from City Hall; never by price."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    assert doc["ordering"] == "kind_then_distance"
    doc["sites"] = doc["sites"][::-1]
    _bad(doc, "grouped by kind")
    doc = _fx("quote_bcbs_hmo_shoulder")
    doc["sites"][0]["distance_km"] = None
    _bad(doc, "distance_km is measured from origin")


def test_missing_is_one_per_step_and_derived():
    """C3 I7: totals.missing is the number of steps flagged missing (per step, not per line); a
    missing step adds nothing to the ranking figure."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    sq = _site(doc, BWH)
    sq["receipt"]["totals"]["missing"] -= 1
    sq["headline"]["missing"] -= 1
    _bad(doc, "missing")
    doc = _fx("quote_bcbs_hmo_shoulder")
    sq = _site(doc, BWH)
    st = next(x for x in sq["steps"] if x["missing"])
    st["rank_value"] = 1.0
    _bad(doc, "has a rank value")
    # BWH's visit has two lines (facility + doctor); one priced, one not: still ONE missing step
    resp = _ok(_fx("quote_bcbs_hmo_shoulder"))
    bwh = next(s for s in resp.sites if s.site.site_id == BWH)
    visit = next(st for st in bwh.steps if st.key == "visit")
    assert len(visit.line_ids) == 2 and visit.missing
    assert q.missing_for(bwh) == sum(1 for st in bwh.steps if st.missing)


def test_headline_copies_the_receipt_totals():
    doc = _fx("quote_bcbs_hmo_shoulder", real=True)
    doc["sites"][0]["headline"]["likely_low"] = 1.0
    _bad(doc, "headline must copy receipt.totals")


def test_a_step_figure_needs_its_shape():
    doc = _fx("quote_bcbs_hmo_shoulder")
    st = next(x for x in _site(doc, MA)["steps"] if x["figure"] == "own")
    st["figure"] = "none"
    _bad(doc, "low/high exactly when it has a figure")
    doc = _fx("quote_bcbs_hmo_shoulder")
    st = next(x for x in _site(doc, FR)["steps"] if x["availability"] != "offered")
    st["in_total"] = True
    _bad(doc, "only an offered step is summed")


# --------------------------------------------------------------------------- receipt line rules


def test_display_tier_follows_likelihood():
    """V2: a likely line cannot be drawn as certain."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    _line(doc, MA, "xray_facility")["tier"] = "certain"
    _bad(doc, "!= likelihood")


def test_per_15_minute_lines_are_never_summed():
    """V6: the count of PT sessions is unknown, so the line cannot be in the total."""
    doc = _fx("quote_bcbs_hmo_shoulder")
    _line(doc, MA, "physical_therapy_sessions")["in_total"] = True
    _bad(doc, "in_total needs certain/likely")


def test_tier_basis_picked_iff_no_care_path_step():
    doc = _fx("quote_bcbs_hmo_shoulder")
    _line(doc, MA, "xray_facility")["tier_basis"] = "picked"
    _bad(doc, "tier_basis picked")


def test_estimate_basis_needs_the_estimate_method():
    doc = _fx("quote_bcbs_hmo_shoulder")
    _line(doc, MA, "visit_facility")["cell"]["basis"] = "estimate"
    _bad(doc, "basis estimate")


# --------------------------------------------------------------------------- placeholders + bounds


def test_placeholder_sha_and_npi_are_refused_outside_fixtures():
    doc = _fx("quote_bcbs_hmo_shoulder")
    with pytest.raises(ValidationError, match="placeholder"):
        q.QuoteResponse.model_validate(doc)  # no allow_placeholders context
    with pytest.raises(ValidationError, match="start with 1 or 2"):
        q.NpiPrice.model_validate(
            {
                "npi": "0000000001",
                "display_name": None,
                "money": _line(doc, MA, "xray_facility")["cell"],
            }
        )


@pytest.mark.parametrize(
    "answers",
    [
        {f"Q{i}": ["x"] for i in range(q.MAX_ANSWER_KEYS + 1)},
        {"Q1": ["x"] * (q.MAX_VALUES_PER_ANSWER + 1)},
        {"Q1": ["x" * 41]},
    ],
)
def test_quote_request_answers_are_bounded(answers):
    req = {
        "payment": {"kind": "cash"},
        "care_path_id": "shoulder_chronic_clicking_v1",
        "answers": answers,
        "service_codes": [],
        "picked_by": "person",
        "site_ids": None,
    }
    with pytest.raises(ValidationError):
        q.QuoteRequest.model_validate(req)


# --------------------------------------------------------------------------- sites + catalog


def _sites() -> dict:
    return _fx("sites")


def test_hospital_outpatient_never_bills_as_office_visit():
    """M17."""
    doc = _sites()
    doc["sites"][2]["billing_type"] = "office_visit"
    with pytest.raises(ValidationError, match="cannot bill as office_visit"):
        sites.SitesFile.model_validate(doc, context=CTX)


def test_asc_billing_iff_ambulatory_surgery_center():
    doc = _sites()
    doc["sites"][0]["billing_type"] = "asc"  # an urgent care
    with pytest.raises(ValidationError, match="asc"):
        sites.SitesFile.model_validate(doc, context=CTX)
    doc = _sites()
    doc["sites"][0].update(site_type="ambulatory_surgery_center", billing_type="office_visit")
    with pytest.raises(ValidationError, match="asc"):
        sites.SitesFile.model_validate(doc, context=CTX)
    doc = _sites()
    doc["sites"][0].update(site_type="ambulatory_surgery_center", billing_type="asc")
    sites.SitesFile.model_validate(doc, context=CTX)


def test_site_tins_are_digits_and_sourced():
    doc = _sites()
    doc["sites"][0]["tins"] = ["27-2343207"]
    doc["sites"][0]["tins_source"] = "tic match"
    with pytest.raises(ValidationError, match="9 digits"):
        sites.SitesFile.model_validate(doc, context=CTX)
    doc["sites"][0]["tins"] = ["272343207"]
    sites.SitesFile.model_validate(doc, context=CTX)
    doc["sites"][0]["tins_source"] = None
    with pytest.raises(ValidationError, match="tins_source"):
        sites.SitesFile.model_validate(doc, context=CTX)


def test_registry_only_sites_are_never_quoted():
    doc = _fx("quote_bcbs_hmo_shoulder")
    _site(doc, MA)["site"]["listing_status"] = "registry_only"
    _bad(doc, "listing_status")
    s = _sites()
    s["sites"][0]["listing_status"] = "registry_only"
    sites.SitesFile.model_validate(s, context=CTX)  # allowed in sites.yaml (to-verify queue)


def test_catalog_services_point_at_known_care_paths():
    """M11."""
    cat = _fx("catalog")
    cat["services"][0]["care_paths"] = ["made_up_path_v1"]
    with pytest.raises(ValidationError, match="unknown care paths"):
        q.Catalog.model_validate(cat)
