"""Wave-2 API contracts: generated files are committed and current; invariants hold.

Regenerate with ``python -m app.api_contracts`` (from backend/).
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

from app import api_contracts as api
from app.chat import contracts as chat
from app.etl import contracts as etl
from app.quote import contracts as q

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "contracts" / "fixtures"


def _fixture(name: str) -> dict:
    doc = json.loads((FIX / f"{name}.json").read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return doc


# --------------------------------------------------------------------------- drift


@pytest.mark.parametrize("path", sorted(api.expected_files()), ids=lambda p: p.name)
def test_generated_file_is_committed_and_current(path):
    expected = api.expected_files()[path]
    assert path.exists(), f"{path.name} missing: run python -m app.api_contracts"
    assert path.read_text() == expected, f"{path.name} is stale: run python -m app.api_contracts"


def test_no_orphan_generated_ts_files():
    committed = {p.name for p in api.TS_DIR.glob("*.ts")}
    assert committed == {spec["ts"] for spec in api.SPECS.values() if spec["ts"]}


def test_api_schemas_reuse_etl_cell_definitions():
    """Money / Gap / Provenance come from app.etl.contracts, never a parallel copy."""
    quote_defs = api.build_schema("quote_api.schema.json")["$defs"]
    etl_defs = TypeAdapter(etl.Cell).json_schema(mode="serialization")["$defs"]
    for name in (
        "Money",
        "Provenance",
        "NotPublished",
        "NotLoaded",
        "NoSource",
        "PercentOnly",
        "Conflict",
    ):
        assert set(quote_defs[name]["properties"]) == set(etl_defs[name]["properties"]), name
    # serialization mode: kind is required, so TypeScript can narrow Cell
    assert "kind" in quote_defs["Money"]["required"]
    assert quote_defs["Cell"] == {
        "oneOf": [
            {"$ref": f"#/$defs/{n}"}
            for n in ("Money", "NotPublished", "NotLoaded", "NoSource", "PercentOnly", "Conflict")
        ]
    }


def test_ts_has_every_gap_kind_and_tier():
    ts = (api.TS_DIR / "quote_api.ts").read_text()
    for k in etl.GapKind:
        assert f'kind: "{k.value}";' in ts
    assert (
        'export type CertaintyTier = "certain" | "likely" | "possible" | "not_in_public_data";'
        in ts
    )


def test_frontend_exhaustiveness_locks_cover_every_member():
    """The TS compiler is the real gate (npm run typecheck:contracts); this catches a lock file
    that someone deleted or emptied."""
    locks = (REPO / "frontend" / "src" / "contracts" / "exhaustive.ts").read_text()
    for k in etl.GapKind:
        assert f"{k.value}:" in locks
    for t in ("certain", "likely", "possible", "not_in_public_data"):
        assert f"{t}:" in locks
    for d in ("call_911", "er_today", "seen_today", "routine"):
        assert f"{d}:" in locks
    assert 'satisfies { [K in Gap["kind"]]' in locks


# --------------------------------------------------------------------------- registries


def test_dispositions_equal_redflags_json():
    rf = json.loads((REPO / "data" / "redflags" / "redflags.json").read_text())
    import typing

    assert set(typing.get_args(chat.Disposition)) == {d["id"] for d in rf["dispositions"]}


def test_ladder_has_eight_rungs_and_a_self_pay_key():
    import typing

    keys = set(typing.get_args(q.LadderExplanation))
    assert set(q.RUNG_EXPLANATION) == set(range(1, 9))
    assert keys == set(q.RUNG_EXPLANATION.values()) | {"fee.self_pay_no_source"}


def test_payment_has_the_four_ways_to_pay():
    import typing

    kinds = {
        typing.get_args(m.model_fields["kind"].annotation)[0]
        for m in typing.get_args(typing.get_args(q.Payment)[0])
    }
    assert kinds == {"insurance", "medicare", "masshealth", "cash"}


def test_no_personal_data_fields_except_chat_email():
    """No name / dob / address / location / phone of the *user* in any request."""
    banned = {
        "name",
        "first_name",
        "last_name",
        "dob",
        "birth",
        "age",
        "address",
        "zip",
        "lat",
        "lon",
        "latitude",
        "longitude",
        "location",
        "phone",
        "ip",
        "member_id",
        "ssn",
        "gender",
        "sex",
    }
    for model in (q.QuoteRequest, chat.ChatRequest):
        fields = set(model.model_fields)
        for m in (q.InsurancePayment, q.MedicarePayment, q.MassHealthPayment, q.CashPayment):
            fields |= set(m.model_fields)
        assert not fields & banned, (model.__name__, fields & banned)
    assert set(chat.ChatRequest.model_fields) - {
        "conversation_id",
        "text",
        "payment",
        "answers",
        "locale",
    } == {"email"}


def test_fixtures_cannot_pass_as_data():
    """`_fixture` is not a field anywhere, so a fixture file fed to a validator is rejected."""
    doc = json.loads((FIX / "quote_bcbs_hmo_shoulder.json").read_text())
    doc.pop("_schema")
    with pytest.raises(ValidationError):
        q.QuoteResponse.model_validate(doc)


# --------------------------------------------------------------------------- request rules


def _req(**kw):
    base = {
        "payment": {"kind": "cash"},
        "care_path_id": None,
        "answers": {},
        "service_codes": [],
        "site_ids": None,
    }
    base.update(kw)
    return base


def test_quote_request_needs_exactly_one_of_path_or_codes():
    q.QuoteRequest.model_validate(_req(care_path_id="shoulder_chronic_clicking_v1"))
    q.QuoteRequest.model_validate(_req(service_codes=["73030"]))
    with pytest.raises(ValidationError):
        q.QuoteRequest.model_validate(_req())
    with pytest.raises(ValidationError):
        q.QuoteRequest.model_validate(
            _req(care_path_id="shoulder_chronic_clicking_v1", service_codes=["73030"])
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"service_codes": ["7303"]},
        {"care_path_id": "x_v1", "answers": {"age": ["40"]}},
        {"care_path_id": "x_v1", "answers": {"Q1": ["My shoulder hurts"]}},
        {"care_path_id": "x_v1", "site_ids": ["Mount Auburn"]},
        {"care_path_id": "x_v1", "lat": 42.3},
        {
            "care_path_id": "x_v1",
            "payment": {"kind": "insurance", "payer_id": "bcbs", "product": "HMO", "network": None},
        },
    ],
)
def test_quote_request_rejects_free_text_location_and_bad_ids(bad):
    with pytest.raises(ValidationError):
        q.QuoteRequest.model_validate(_req(**bad))


def test_chat_request_requires_email_and_caps_text():
    req = _fixture("chat_request_first_message")
    chat.ChatRequest.model_validate(req)
    with pytest.raises(ValidationError):
        chat.ChatRequest.model_validate({k: v for k, v in req.items() if k != "email"})
    with pytest.raises(ValidationError):
        chat.ChatRequest.model_validate({**req, "email": "not-an-email"})
    with pytest.raises(ValidationError):
        chat.ChatRequest.model_validate({**req, "text": "x" * (chat.MAX_TEXT_CHARS + 1)})


# --------------------------------------------------------------------------- receipt invariants


def _bcbs_site(i: int = 0) -> dict:
    return copy.deepcopy(_fixture("quote_bcbs_hmo_shoulder")["sites"][i])


def _line(receipt: dict, line_id: str) -> dict:
    return next(ln for ln in receipt["lines"] if ln["line_id"] == line_id)


def test_ai_suggested_line_can_never_count_in_total():
    site = _bcbs_site()
    ln = _line(site["receipt"], "injection_drug_ai")
    ln["in_total"] = True
    with pytest.raises(ValidationError, match="AI-suggested"):
        q.SiteQuote.model_validate(site)


def test_not_in_public_data_tier_iff_no_number_gap():
    site = _bcbs_site()
    _line(site["receipt"], "xray_reading")["tier"] = "likely"
    with pytest.raises(ValidationError, match="not_in_public_data"):
        q.SiteQuote.model_validate(site)
    site = _bcbs_site()
    _line(site["receipt"], "xray_facility")["tier"] = "not_in_public_data"
    with pytest.raises(ValidationError, match="not_in_public_data"):
        q.SiteQuote.model_validate(site)


def test_total_must_equal_sum_of_in_total_lines():
    site = _bcbs_site()
    site["receipt"]["totals"]["likely"]["high"] += 1
    with pytest.raises(ValidationError, match="sum of lines"):
        q.SiteQuote.model_validate(site)


def test_possible_line_cannot_be_summed():
    site = _bcbs_site()
    ln = _line(site["receipt"], "mri")
    ln["in_total"] = True
    with pytest.raises(ValidationError, match="in_total"):
        q.SiteQuote.model_validate(site)


def test_every_line_is_summed_or_excluded_with_a_reason():
    site = _bcbs_site()
    site["receipt"]["totals"]["excluded"] = site["receipt"]["totals"]["excluded"][1:]
    with pytest.raises(ValidationError, match="neither in the total nor excluded"):
        q.SiteQuote.model_validate(site)


def test_complete_flag_is_honest():
    site = _bcbs_site()
    assert site["receipt"]["totals"]["complete"] is False  # doctor fee is reference-only
    site["receipt"]["totals"]["complete"] = True
    with pytest.raises(ValidationError, match="complete"):
        q.SiteQuote.model_validate(site)


def test_reference_rungs_are_never_summed():
    site = _bcbs_site()
    ln = _line(site["receipt"], "visit_doctor")
    assert ln["doctor_fee"]["rung"] == 7
    ln["in_total"] = True
    with pytest.raises(ValidationError, match="rungs 7-8"):
        q.SiteQuote.model_validate(site)


def test_doctor_fee_rules():
    ok = {
        "rung": 2,
        "explanation_key": "fee.rung_2_group",
        "group_name": None,
        "group_tin": None,
        "npi_count": None,
        "multiple": None,
        "chia_badge": None,
        "by_npi": None,
    }
    q.DoctorFee.model_validate(ok)
    with pytest.raises(ValidationError):
        q.DoctorFee.model_validate({**ok, "explanation_key": "fee.rung_5_medicare"})
    with pytest.raises(ValidationError, match="rung 6"):
        q.DoctorFee.model_validate({**ok, "rung": 6, "explanation_key": "fee.rung_6_estimate"})
    with pytest.raises(ValidationError):
        q.DoctorFee.model_validate({**ok, "rung": None})
    by_npi = _line(_bcbs_site(1)["receipt"], "visit_doctor")["doctor_fee"]["by_npi"]
    same = [by_npi[0], {**by_npi[0], "npi": "0000000003"}]
    with pytest.raises(ValidationError, match="D6"):
        q.DoctorFee.model_validate({**ok, "by_npi": same})


def test_rung_6_money_must_be_marked_estimate():
    site = _bcbs_site(1)
    ln = _line(site["receipt"], "visit_doctor")
    ln["doctor_fee"] = {
        **ln["doctor_fee"],
        "rung": 6,
        "explanation_key": "fee.rung_6_estimate",
        "by_npi": None,
        "multiple": {"low": 2.4, "high": 3.6, "n_codes": 5, "payer_id": "BCBS_MA"},
    }
    with pytest.raises(ValidationError, match="estimate_medicare_multiple"):
        q.SiteQuote.model_validate(site)
    ln["cell"]["prov"]["method"] = "estimate_medicare_multiple"
    site["receipt"]["totals"]["likely"]["includes_estimate"] = True
    q.SiteQuote.model_validate(site)


def test_not_offered_needs_elsewhere_and_no_cell():
    site = _bcbs_site(2)
    ln = _line(site["receipt"], "mri")
    ln["elsewhere"] = []
    with pytest.raises(ValidationError, match="not_offered"):
        q.SiteQuote.model_validate(site)


def _fresh(**kw):
    base = {
        "last_updated": "2026-03-27",
        "expected_by": "2027-03-27",
        "late_to_refresh": False,
        "source_rule": "hospital_mrf_365_days",
        "fetched_at": "2026-10-24",
        "our_refresh_due": "2026-11-24",
        "stale_on_our_side": False,
        "our_rule": "hospital_monthly",
    }
    base.update(kw)
    return base


def test_freshness_sides_need_their_deadlines():
    from app.sites.contracts import Freshness

    Freshness.model_validate(_fresh())
    with pytest.raises(ValidationError, match="expected_by"):
        Freshness.model_validate(_fresh(expected_by=None, late_to_refresh=True))
    with pytest.raises(ValidationError, match="our_refresh_due"):
        Freshness.model_validate(_fresh(our_refresh_due=None, stale_on_our_side=True))


def test_never_blame_the_publisher_while_we_are_stale():
    from app.sites.contracts import Freshness

    with pytest.raises(ValidationError, match="cannot blame the publisher"):
        Freshness.model_validate(_fresh(late_to_refresh=True, stale_on_our_side=True))


@pytest.mark.parametrize(
    "kw, late, stale",
    [
        # hospital MRF: late only after 365 days (not the old 180)
        (
            dict(
                source_rule="hospital_mrf_365_days",
                last_updated=date(2026, 3, 27),
                our_rule="hospital_monthly",
                fetched_at=date(2026, 10, 24),
            ),
            False,
            False,
        ),
        (
            dict(
                source_rule="hospital_mrf_365_days",
                last_updated=date(2025, 10, 1),
                our_rule="hospital_monthly",
                fetched_at=date(2026, 10, 20),
            ),
            True,
            False,
        ),
        # we stopped fetching: stale on our side, and we do not blame the hospital
        (
            dict(
                source_rule="hospital_mrf_365_days",
                last_updated=date(2025, 10, 1),
                our_rule="hospital_monthly",
                fetched_at=date(2026, 8, 1),
            ),
            False,
            True,
        ),
        # TiC: late after 45 days
        (
            dict(
                source_rule="tic_45_days",
                last_updated=date(2026, 9, 1),
                our_rule="tic_monthly",
                fetched_at=date(2026, 10, 20),
            ),
            True,
            False,
        ),
        (
            dict(
                source_rule="tic_45_days",
                last_updated=date(2026, 9, 20),
                our_rule="tic_monthly",
                fetched_at=date(2026, 10, 20),
            ),
            False,
            False,
        ),
        # clinic page with no date: never late; sites are checked weekly
        (
            dict(
                source_rule="posted_page_date_365_days",
                last_updated=None,
                our_rule="sites_weekly",
                fetched_at=date(2026, 10, 10),
            ),
            False,
            True,
        ),
        # fee schedule: explicit next release; no newer release known -> never stale
        (
            dict(
                source_rule="fee_schedule_quarterly",
                last_updated=date(2026, 7, 1),
                expected_by=date(2026, 10, 1),
                our_rule="fee_schedule_per_release",
                fetched_at=date(2026, 7, 2),
                our_refresh_due=date(2026, 10, 1),
            ),
            False,
            True,
        ),
        (
            dict(
                source_rule="fee_schedule_annual",
                last_updated=date(2026, 1, 1),
                expected_by=date(2027, 1, 1),
                our_rule="fee_schedule_per_release",
                fetched_at=date(2026, 1, 5),
            ),
            False,
            False,
        ),
    ],
)
def test_freshness_compute_cadences(kw, late, stale):
    from app.sites.contracts import Freshness

    f = Freshness.compute(as_of=date(2026, 10, 24), **kw)
    assert (f.late_to_refresh, f.stale_on_our_side) == (late, stale)


def test_site_rollups_and_sources_behind_must_match_the_chips():
    resp = _fixture("quote_bcbs_hmo_shoulder")
    bad = copy.deepcopy(resp)
    bad["sites"][1]["site"]["any_source_late"] = False  # Brigham's TiC chip is late
    with pytest.raises(ValidationError, match="any_source_late"):
        q.QuoteResponse.model_validate(bad)
    bad = copy.deepcopy(resp)
    bad["data_version"]["sources_behind"] = []
    with pytest.raises(ValidationError, match="sources_behind"):
        q.QuoteResponse.model_validate(bad)
    bad = copy.deepcopy(resp)
    bad["notices"].remove("late_to_refresh_sources")
    with pytest.raises(ValidationError, match="late_to_refresh_sources"):
        q.QuoteResponse.model_validate(bad)
    cash = _fixture("quote_cash_shoulder")
    cash["notices"].remove("stale_on_our_side_sources")
    with pytest.raises(ValidationError, match="stale_on_our_side_sources"):
        q.QuoteResponse.model_validate(cash)


def test_chat_red_flag_and_pause_never_call_the_llm():
    doc = _fixture("chat_red_flag")
    with pytest.raises(ValidationError, match="before any LLM"):
        chat.ChatResponse.model_validate({**doc, "llm_called": True})
    doc = _fixture("chat_ai_paused")
    with pytest.raises(ValidationError, match="before any LLM"):
        chat.ChatResponse.model_validate({**doc, "llm_called": True})


def test_clarify_asks_at_most_two_questions():
    doc = _fixture("chat_clarify")
    doc["reply"]["questions"] = doc["reply"]["questions"] * 2
    with pytest.raises(ValidationError):
        chat.ChatResponse.model_validate(doc)


def test_payer_and_product_registries_exist():
    """Payer ids in contracts are payer_aliases.yaml keys, never a hard-coded enum."""
    pa = yaml.safe_load((REPO / "data" / "etl" / "payer_aliases.yaml").read_text())
    assert "BCBS_MA" in pa["payers"] and "HMO" in pa["products"]
