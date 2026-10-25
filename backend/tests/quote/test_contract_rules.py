"""Negative tests for the contract rules stream C added (each fails when its rule is deleted)."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.etl.contracts import Money, Provenance
from app.quote.contracts import QuoteResponse
from tests.quote.conftest import fixture_doc

TUFTS = "mount_auburn_hospital"  # a hospital in the Cambridge golden quote


def _ok(doc):
    return QuoteResponse.model_validate(doc)


def _line(doc, site, line_id):
    sq = next(s for s in doc["sites"] if s["site"]["site_id"] == site)
    return next(ln for ln in sq["receipt"]["lines"] if ln["line_id"] == line_id)


@pytest.fixture
def bcbs():
    doc = fixture_doc("quote_bcbs_hmo_shoulder")
    _ok(doc)
    return copy.deepcopy(doc)


def test_a_range_needs_prov_high(bcbs):
    """P1 #2: both ends of a range are cited."""
    cell = _line(bcbs, TUFTS, "visit_doctor")["cell"]
    assert cell["low"] < cell["high"]
    del cell["prov_high"]
    with pytest.raises(ValidationError, match="needs prov_high"):
        _ok(bcbs)


def test_a_point_has_no_prov_high(bcbs):
    cell = _line(bcbs, TUFTS, "xray_facility")["cell"]
    assert cell["low"] == cell["high"]
    cell["prov_high"] = cell["prov"]
    with pytest.raises(ValidationError, match="a point has none"):
        _ok(bcbs)


def test_prov_high_source_must_be_listed(bcbs):
    cell = _line(bcbs, TUFTS, "visit_doctor")["cell"]
    hi = cell["prov_high"]
    hi["source_id"] = "tic_made_up"
    hi["row_ref"] = "tic_made_up:" + hi["row_ref"].split(":", 1)[1]
    with pytest.raises(ValidationError, match="tic_made_up not in sources"):
        _ok(bcbs)


def test_both_ends_are_the_same_payers():
    p = dict(
        source_id="tic_x", source_kind="insurer_tic", source_file="f.json",
        source_sha256="a" * 64, source_date=None, method="stated", row_ref=f"tic_x:{'a' * 12}:1",
        payer_id="BCBS_MA", row_id="0123456789abcdef:0",
    )  # fmt: skip
    lo = Provenance(**p)
    hi = Provenance(**{**p, "payer_id": "AETNA"})
    with pytest.raises(ValidationError, match="same payer"):
        Money(low=1, high=2, basis="negotiated", prov=lo, prov_high=hi)


def test_a_tic_number_needs_row_id():
    """P1 #1: a TiC row_ref is shared by every provider group listed with it."""
    p = dict(
        source_id="tic_x", source_kind="insurer_tic", source_file="f.json",
        source_sha256="a" * 64, source_date=None, method="stated", row_ref=f"tic_x:{'a' * 12}:1",
        payer_id="BCBS_MA",
    )  # fmt: skip
    with pytest.raises(ValidationError, match="needs row_id"):
        Provenance(**p)
    Provenance(**p, row_id="0123456789abcdef:0")


def test_care_path_quote_carries_both_copy_keys(bcbs):
    """P1 #13 / D33."""
    bcbs["copy_keys"] = ["copy.not_a_diagnosis"]
    with pytest.raises(ValidationError, match="copy_keys"):
        _ok(bcbs)


def test_manual_pick_carries_no_copy_keys():
    doc = fixture_doc("quote_masshealth_manual")
    _ok(doc)
    doc["copy_keys"] = ["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"]
    with pytest.raises(ValidationError, match="copy_keys"):
        _ok(doc)


def test_site_without_a_loaded_price_source_is_allowed():
    """P1 #9: price_source_id None, and no source is invented for it."""
    doc = fixture_doc("quote_cash_shoulder")
    nulls = [s for s in doc["sites"] if s["site"]["price_source_id"] is None]
    assert nulls
    _ok(doc)


def _payer_row(**kw):
    from app.etl.contracts import RateRow

    base = dict(
        row_id="0123456789abcdef:0", nk_hash="0123456789abcdef", nk_ordinal=0,
        source_id="tufts_mrf", source_kind="hospital_mrf", entity_id="tufts", row_kind="payer_rate",
        billing_npis="", code_type="CPT", code="73030", modifiers="", rev_code="0320", cdm_code="",
        description="X-ray shoulder", setting="outpatient", billing_class="facility",
        component="facility", component_rule="rev_code", payer_raw="BCBS", plan_raw="HMO",
        payer_id="BCBS_MA", line_of_business="commercial", product="HMO",
        methodology="fee_schedule", methodology_raw="fee schedule", dollar_basis="dollar",
        negotiated_dollar=110.42, negotiated_pct=None, negotiated_algorithm="", amount=110.42,
        amount_method="stated", gross=333.0, gross_rule="same_row", discounted_cash=233.1,
        min_negotiated=None, max_negotiated=None, median_amount=None, p10_amount=None,
        p90_amount=None, allowed_count="", above_gross=False, ambiguous_multi_rate=False,
        payer_plan_mismatch=False, excluded=False, exclude_reason="", additional_generic_notes="",
        additional_payer_notes="", source_file="f.zip", source_sha256="d" * 64, source_date=None,
        stage_row=7, row_ref=f"tufts_mrf:{'d' * 12}:7",
    )  # fmt: skip
    return RateRow(**{**base, **kw})


def test_cash_and_gross_on_a_payer_row_carry_no_payer():
    """P1 #8 at the source: RateRow.provenance(basis) on a payer_rate row."""
    from app.etl.contracts import PriceBasis

    row = _payer_row()
    assert row.provenance(PriceBasis.negotiated).payer_id == "BCBS_MA"
    assert row.provenance().payer_id == "BCBS_MA"  # default basis is negotiated
    assert row.provenance(PriceBasis.discounted_cash).payer_id is None
    assert row.provenance(PriceBasis.gross).payer_id is None
    assert row.provenance(PriceBasis.fee_schedule).payer_id is None
    assert _payer_row(row_kind="chargemaster").provenance().payer_id is None


def test_engine_store_uses_the_same_payer_rule(store):
    """The engine prices with RateStore.prov, not RateRow.provenance: both call number_payer,
    so the rule cannot drift between them."""
    from app.etl.contracts import PriceBasis

    payer_rows = [r for r in store.rows if r.row_kind == "payer_rate" and r.payer_id
                  and r.discounted_cash is not None and r.gross is not None]  # fmt: skip
    assert payer_rows
    r = payer_rows[0]
    assert store.prov(r, PriceBasis.negotiated).payer_id == r.payer_id
    assert store.prov(r, PriceBasis.discounted_cash).payer_id is None
    assert store.prov(r, PriceBasis.gross).payer_id is None
