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
# Negative rule tests mutate the earlier hand-made BCBS / cash quotes (see test_quote_rules.py).
HANDMADE = Path(__file__).resolve().parent / "handmade"


PLACEHOLDERS = {"allow_placeholders": True}  # fixtures carry placeholder shas / NPIs


def _fixture(name: str) -> dict:
    hand = HANDMADE / f"{name}.json"
    doc = json.loads((hand if hand.exists() else FIX / f"{name}.json").read_text())
    doc.pop("_fixture")
    doc.pop("_schema")
    return doc


def _quote(doc: dict) -> q.QuoteResponse:
    return q.QuoteResponse.model_validate(doc, context=PLACEHOLDERS)


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


def test_ci_runs_the_typescript_contract_locks():
    """Theater F3: the satisfies-maps only bind if CI compiles them."""
    ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
    steps = ci["jobs"]["test-frontend"]["steps"]
    assert any(st.get("run") == "npm run typecheck:contracts" for st in steps)
    pkg = json.loads((REPO / "frontend" / "package.json").read_text())
    assert pkg["scripts"]["typecheck:contracts"] == "tsc -p tsconfig.contracts.json"
    tsconfig = json.loads((REPO / "frontend" / "tsconfig.contracts.json").read_text())
    assert {"src/generated/contracts", "src/contracts"} <= set(tsconfig["include"])
    test = (REPO / "frontend" / "src" / "contracts" / "exhaustive.test.ts").read_text()
    assert 'from "./exhaustive"' in test  # vitest (CI) imports the locks


def test_no_switch_on_contract_kinds_outside_src_contracts():
    """UI code narrows contract unions through src/contracts/exhaustive.ts, never its own switch
    with a default branch that silently swallows a new Gap kind / tier / reply kind."""
    import re

    rx = re.compile(r"switch\s*\([^)]*\.(kind|tier|disposition|reason)\s*\)")
    src = REPO / "frontend" / "src"
    bad = [
        str(p.relative_to(src))
        for p in src.rglob("*.ts*")
        if "contracts" not in p.relative_to(src).parts[:2] and rx.search(p.read_text())
    ]
    assert not bad, f"switch on a contract kind outside src/contracts: {bad}"


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
        "history",  # the person's own earlier messages (P5b), not personal data fields
        "focus",
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
        "picked_by": "person",
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


class _Site(dict):
    """A BCBS fixture site that validates inside its whole response (sources live there)."""

    def __init__(self, i: int):
        self.resp = _fixture("quote_bcbs_hmo_shoulder")
        super().__init__(self.resp["sites"][i])
        self.resp["sites"][i] = self


def _bcbs_site(i: int = 0) -> _Site:
    return _Site(i)


def _check(site: _Site) -> None:
    _quote(site.resp)


def _line(receipt: dict, line_id: str) -> dict:
    return next(ln for ln in receipt["lines"] if ln["line_id"] == line_id)


def test_ai_suggested_line_can_never_count_in_total():
    site = _bcbs_site()
    ln = _line(site["receipt"], "injection_drug_ai")
    ln["in_total"] = True
    with pytest.raises(ValidationError, match="AI-suggested"):
        _check(site)


def test_not_in_public_data_tier_iff_no_number_gap():
    site = _bcbs_site()
    _line(site["receipt"], "xray_reading")["tier"] = "likely"
    with pytest.raises(ValidationError, match="not_in_public_data"):
        _check(site)
    site = _bcbs_site()
    _line(site["receipt"], "xray_facility")["tier"] = "not_in_public_data"
    with pytest.raises(ValidationError, match="not_in_public_data"):
        _check(site)


def test_total_must_equal_sum_of_in_total_lines():
    site = _bcbs_site()
    site["receipt"]["totals"]["likely"]["high"] += 1
    with pytest.raises(ValidationError, match="sum of lines"):
        _check(site)


def test_possible_line_cannot_be_summed():
    site = _bcbs_site()
    ln = _line(site["receipt"], "mri")
    ln["in_total"] = True
    with pytest.raises(ValidationError, match="in_total"):
        _check(site)


def test_every_line_is_summed_or_excluded_with_a_reason():
    site = _bcbs_site()
    site["receipt"]["totals"]["excluded"] = site["receipt"]["totals"]["excluded"][1:]
    with pytest.raises(ValidationError, match="neither in the total nor excluded"):
        _check(site)


def test_complete_flag_is_honest():
    site = _bcbs_site()
    assert site["receipt"]["totals"]["complete"] is False  # doctor fee is reference-only
    site["receipt"]["totals"]["complete"] = True
    with pytest.raises(ValidationError, match="complete"):
        _check(site)


def test_reference_rungs_are_never_summed():
    """C4b 3d: rung 7 is no longer sent for BCBS (the handmade line is a gap now); rung 8, the
    other reference rung, is still never summed."""
    i, ln = next((i, x) for i in range(3) for x in _bcbs_site(i)["receipt"]["lines"]
                 if x["in_total"] and x["doctor_fee"])  # fmt: skip
    site = _bcbs_site(i)
    ln = _line(site["receipt"], ln["line_id"])
    ln["doctor_fee"] = {"rung": 8, "explanation_key": "fee.rung_8_chia_badge",
                        "chia_badge": {"payer_id": "BCBS_MA", "band": "above_median",
                                       "report_year": 2024}}  # fmt: skip
    with pytest.raises(ValidationError, match="rungs 7-8"):
        _check(site)


def test_doctor_fee_rules():
    ok = {
        "rung": 2,
        "explanation_key": "fee.rung_2_group",
        "group_name": None,
        "group_tin": None,
        "npi_count": None,
        "chia_badge": None,
        "by_npi": None,
    }
    q.DoctorFee.model_validate(ok)
    with pytest.raises(ValidationError):
        q.DoctorFee.model_validate({**ok, "explanation_key": "fee.rung_5_medicare"})
    with pytest.raises(ValidationError):
        q.DoctorFee.model_validate({**ok, "rung": None})
    by_npi = _line(_bcbs_site(1)["receipt"], "visit_doctor")["doctor_fee"]["by_npi"]
    same = [by_npi[0], {**by_npi[0], "npi": "0000000003"}]
    with pytest.raises(ValidationError, match="D6"):
        q.DoctorFee.model_validate({**ok, "by_npi": same}, context=PLACEHOLDERS)
    with pytest.raises(ValidationError, match="rung 8 needs chia_badge"):
        q.DoctorFee.model_validate({**ok, "rung": 8, "explanation_key": "fee.rung_8_chia_badge"})


def _rung6(site: _Site) -> dict:
    """C3: Brigham's doctor fee as a peer estimate (rung 6): p25-p75 of BCBS's own rates for the
    same line at >= 5 groups of hospital doctors, both ends cited, the PeerRange on the line."""
    from tests.contracts.migrate_c3 import derive_site

    ln = _line(site["receipt"], "visit_doctor")
    cell = copy.deepcopy(ln["cell"])
    cell.update(low=90.66, high=135.97, basis="estimate")
    for k in ("prov", "prov_high"):
        cell[k] = {**(cell.get(k) or cell["prov"]), "method": "estimate_peer_range"}
    ln["cell"] = cell
    ln["estimate"] = {
        "low": 90.66,
        "high": 135.97,
        "median": 110.0,
        "n_groups": 5,
        "kind": "hospital_outpatient",
        "scope": "same_kind",
        "payer_id": "BCBS_MA",
    }
    ln["doctor_fee"] = {**ln["doctor_fee"], "rung": 6, "explanation_key": "fee.rung_6_estimate",
                        "by_npi": None, "npi_count": None}  # fmt: skip
    t = site["receipt"]["totals"]["likely"]
    t.update(low=90.66, high=135.97, includes_estimate=True)
    derive_site(site)
    return ln


def test_rung_6_money_must_be_marked_estimate():
    site = _bcbs_site(1)
    _rung6(site)
    _check(site)
    site = _bcbs_site(1)
    ln = _rung6(site)
    ln["cell"]["prov"]["method"] = "stated"
    with pytest.raises(ValidationError, match="basis estimate <=> estimate_peer_range"):
        _check(site)
    # an estimate needs its peer range, and a rung-6 doctor fee needs an estimated cell
    site = _bcbs_site(1)
    ln = _rung6(site)
    ln["estimate"] = None
    with pytest.raises(ValidationError, match="estimated cell <=> its PeerRange"):
        _check(site)
    site = _bcbs_site(1)
    tic_cell = copy.deepcopy(_line(site["receipt"], "visit_doctor")["cell"])
    ln = _rung6(site)
    ln["cell"], ln["estimate"] = tic_cell, None
    with pytest.raises(ValidationError, match="rung 6 <=> an estimated cell"):
        _check(site)
    site = _bcbs_site(1)
    ln = _rung6(site)
    ln["estimate"]["low"] = 80.0
    with pytest.raises(ValidationError, match="p25-p75"):
        _check(site)


def test_includes_estimate_is_derived_from_the_summed_lines():
    site = _bcbs_site(1)
    _rung6(site)
    site["receipt"]["totals"]["likely"]["includes_estimate"] = False
    with pytest.raises(ValidationError, match="includes_estimate"):
        _check(site)


def test_an_estimate_must_be_built_from_the_same_payers_rates():
    """P5: same payer only. The PeerRange and the rows it cites must be BCBS's own."""
    site = _bcbs_site(1)
    ln = _rung6(site)
    ln["estimate"]["payer_id"] = "AETNA"
    with pytest.raises(ValidationError, match="built from BCBS_MA's rates"):
        _check(site)
    site = _bcbs_site(1)
    ln = _rung6(site)
    ln["cell"]["prov"]["payer_id"] = "AETNA"
    ln["cell"]["prov_high"]["payer_id"] = "AETNA"
    with pytest.raises(ValidationError, match="not BCBS_MA's"):
        _check(site)


def test_unknown_availability_is_never_summed():
    """C3 R2: a line without offer evidence cannot be in the total."""
    site = _bcbs_site(0)
    ln = _line(site["receipt"], "xray_facility")
    ln["availability"], ln["availability_reason"] = "unknown", "insurer_lists_rate"
    with pytest.raises(ValidationError, match="only an offered line is summed"):
        _check(site)
    site = _bcbs_site(0)
    _line(site["receipt"], "xray_facility")["availability_reason"] = "no_evidence"
    with pytest.raises(ValidationError, match="availability_reason exactly when not offered"):
        _check(site)


def test_an_unusual_line_is_never_summed():
    site = _bcbs_site(0)
    ln = _line(site["receipt"], "xray_facility")
    ln["unusual"] = {"peer_median": 400.0, "n_groups": 6, "whole_line": True, "set_aside": []}
    with pytest.raises(ValidationError, match="unusual price is never summed"):
        _check(site)


def test_not_offered_needs_no_cell():
    site = _bcbs_site(2)
    ln = _line(site["receipt"], "mri")
    ln["cell"] = copy.deepcopy(_line(_bcbs_site(0)["receipt"], "mri")["cell"])
    with pytest.raises(ValidationError, match="not_offered needs cell=None"):
        _check(site)


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


def test_freshness_notices_must_match_the_sources():
    resp = _fixture("quote_bcbs_hmo_shoulder")
    resp["notices"].remove("late_to_refresh_sources")
    with pytest.raises(ValidationError, match="late_to_refresh_sources"):
        _quote(resp)
    cash = _fixture("quote_cash_shoulder")
    cash["notices"].remove("stale_on_our_side_sources")
    with pytest.raises(ValidationError, match="stale_on_our_side_sources"):
        _quote(cash)


def test_chat_red_flag_and_pause_never_call_the_llm():
    from tests.contracts.chat_ctx import context

    for name in ("chat_red_flag", "chat_ai_paused"):
        doc = {**_fixture(name), "llm_called": True}
        with pytest.raises(ValidationError, match="before any LLM"):
            chat.ChatResponse.model_validate(doc, context=context(doc, calls=1))


def test_clarify_asks_at_most_two_questions():
    from tests.contracts.chat_ctx import context

    doc = _fixture("chat_clarify")
    doc["reply"]["questions"] = doc["reply"]["questions"] * 2
    with pytest.raises(ValidationError, match="at most 2 items"):
        chat.ChatResponse.model_validate(doc, context=context(doc))


def test_payer_and_product_registries_exist():
    """Payer ids in contracts are payer_aliases.yaml keys, never a hard-coded enum."""
    pa = yaml.safe_load((REPO / "data" / "etl" / "payer_aliases.yaml").read_text())
    assert "BCBS_MA" in pa["payers"] and "HMO" in pa["products"]
