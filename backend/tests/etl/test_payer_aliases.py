"""Payer alias table (bug E4). Every raw string below is copied from a real 2026 hospital MRF."""

from __future__ import annotations

import pytest

from app.etl.payers import PayerResolver, clean_payer


@pytest.fixture(scope="module")
def r() -> PayerResolver:
    return PayerResolver.load()


def test_clean_payer_strips_internal_ids_and_case():
    assert clean_payer("AETNA [1001]") == "AETNA"
    assert clean_payer("  BCBS   - MA [10001] ") == "BCBS - MA"
    assert clean_payer("CARELON BEHAVIORAL HEALTH MEDICAID REPLACEMENT [35") == (
        "CARELON BEHAVIORAL HEALTH MEDICAID REPLACEMENT"
    )
    assert clean_payer("Mgbhp") == "MGBHP"


@pytest.mark.parametrize(
    "payer, plan, payer_id, lob",
    [
        # MGB files
        ("AETNA [1001]", "HB AMC AETNA HMO", "AETNA", "commercial"),
        ("BLUE CROSS BLUE SHIELD [110001]", "HB AMC BLUE CROSS PPO", "BCBS_MA", "commercial"),
        ("MGB HEALTH PLAN [150001]", "HB AMC MGBHP COMMERCIAL HMO", "MGB_HP", "commercial"),
        (
            "TUFTS HEALTH PLAN [170001]",
            "HB BWF TUFTS + COMM CARE ALLIANCE MCARE",
            "TUFTS_HP",
            "medicare_advantage",
        ),
        ("MEDICARE [2001]", "HB BWH MEDICARE", "MEDICARE", "medicare"),
        (
            "MEDICAID MASSHEALTH [300001]",
            "HB XR MEDICAID LIMITED CMSP 100%",
            "MASSHEALTH",
            "medicaid",
        ),
        (
            "UNITED HEALTHCARE [1016]",
            "HB BWH UNITED MEDICARE REPLACEMENT",
            "UHC",
            "medicare_advantage",
        ),
        # BMC / CHA / Tufts
        (
            "FALLON HEALTH MEDICAID REPLACEMENT [350008]",
            "HB XR MASSHEALTH 100% TMC",
            "FALLON",
            "medicaid_managed",
        ),
        ("FALLON [8008]", "BMC HB FALLON COMMERCIAL (130% OF MEDICARE)", "FALLON", "commercial"),
        ("CIGNA [50005]", "CHA HB CIGNA HEALTHCARE", "CIGNA", "commercial"),
        ("MEDICAID MASSHEALTH [300001]", "HB XR MASSHEALTH 100% TMC", "MASSHEALTH", "medicaid"),
        (
            "TUFTS HEALTH PUBLIC PLAN CONNECTORCARE [100264]",
            "HB XR THPP CONNECTOR PLANS QHP SUBSIDIZED TMC",
            "TUFTS_HP",
            "connector",
        ),
        # JSON files (title-case names)
        ("Bcbs", "Hmo", "BCBS_MA", "commercial"),
        (
            "Harvard Pilgrim Healthcare",
            "Self Insured Non Lcu All Commercial Plans",
            "HARVARD_PILGRIM",
            "commercial",
        ),
        ("Unicare", "Gic Wellpoint All Commercial Plans", "WELLPOINT", "commercial"),
        ("Masshealth", "Aco Medicaid Managed Care Plan", "MASSHEALTH", "medicaid_managed"),
        ("Aetna", "Medicare Managed Care Plan", "AETNA", "medicare_advantage"),
        ("MGB/Allways", "PPO Outpatient", "MGB_HP", "commercial"),
        ("MGB/Allways", "HMO QHP Outpatient", "MGB_HP", "connector"),
        ("Mgbhp", "Commercial & Qualified Hmo", "MGB_HP", "commercial"),
    ],
)
def test_payer_and_line_of_business(r, payer, plan, payer_id, lob):
    res = r.resolve(payer, plan)
    assert (res.payer_id, res.line_of_business) == (payer_id, lob)
    assert not res.excluded, res.exclude_reason


def test_uhc_hphc_alliance_is_its_own_payer_not_harvard_pilgrim(r):
    """E4: plan-name reconciliation used to relabel these UHC rows as HARVARD_PILGRIM."""
    for payer in (
        "UNITED HEALTHCARE [1016]",
        "HARVARD PILGRIM [120001]",
        "UNITED HEALTHCARE ALTERNATE [1020]",
    ):
        res = r.resolve(payer, "HB AMC HPHC ALLIANCE PPO PREFERRED A")
        assert res.payer_id == "UHC_HPHC_ALLIANCE"
        assert res.product == "PPO"


@pytest.mark.parametrize(
    "payer, plan, reason, payer_id",
    [
        ("AETNA DENTAL [99009]", "CHA HB CATCH-ALL CONTRACT", "dental", "AETNA"),
        ("BCBS - MA DENTAL [99006]", "CHA HB CATCH-ALL CONTRACT", "dental", "BCBS_MA"),
        ("BCBS OUT OF STATE [6002]", "BMC HB BLUE CROSS", "out_of_state", "BCBS_OTHER"),
        ("BCBS - OUT OF STATE [10002]", "CHA HB BCBS PPO", "out_of_state", "BCBS_OTHER"),
        ("BLUE CROSS OF RI [100266]", "HB XR BCBSMA PPO PPA TMC", "out_of_state", "BCBS_OTHER"),
        ("BLUE CROSS OF NH [100265]", "HB XR BCBSMA HMO TMC", "out_of_state", "BCBS_OTHER"),
        ("BCBS", "Indemnity, PPA, HMO Blue Out of State", "out_of_state", "BCBS_OTHER"),
        ("ZZZAETNA [1001]", "BMC HB AETNA", "retired_contract", "AETNA"),
        ("ZZZUNITED [1008]", "BMC HB UNITED HEALTHCARE COMMERCIAL", "retired_contract", "UHC"),
        ("HUMANA [50008]", "CHA HB CATCH-ALL CONTRACT", "catch_all", "HUMANA"),
        ("UBH HPHC [8016]", "BMC HB MEDICARE", "behavioral_carveout", "UHC"),
        ("BCBS - MA [10001]", "CHA HB UNITED BEHAVIORAL HEALTH", "behavioral_carveout", "BCBS_MA"),
        ("WC LIBERTY MUTUAL WORK COMP [700016]", "HB XR WC TMC", "workers_comp", None),
        (
            "WELLSENSE NH [350010]",
            "HB XR NON-CONTRACTED 35% OF BILLED CHARGES TMC",
            "out_of_state",
            "WELLSENSE",
        ),
        ("NEIGHBORHOOD HEALTH PLAN [50011]", "CHA HB CATCH-ALL CONTRACT", "catch_all", "MGB_HP"),
        ("MEDICAID NH [309996]", "HB XR MEDICAID OOS TMC", "out_of_state", None),
        ("MEDICAID OUT OF STATE [309999]", "HB XR MEDICAID OOS TMC", "out_of_state", None),
        ("AETNA [1001]", "HB AMC TRANSPLANT AETNA", "transplant", "AETNA"),
        ("INTERNATIONAL COMMERCIAL [140001]", "HB AMC UNITED PPO / POS", "international", None),
    ],
)
def test_exclusions_keep_payer_but_flag(r, payer, plan, reason, payer_id):
    res = r.resolve(payer, plan)
    assert res.excluded and res.exclude_reason == reason
    assert res.payer_id == payer_id


def test_payer_plan_mismatch_is_flagged_not_overridden(r):
    """'UNITED [2025]' filed under plan 'BMC HB HARVARD PILGRIM': payer column wins, flag set."""
    res = r.resolve("UNITED [2025]", "BMC HB HARVARD PILGRIM")
    assert res.payer_id == "UHC" and res.payer_plan_mismatch
    assert not r.resolve("AETNA [1001]", "HB AMC AETNA HMO").payer_plan_mismatch


def test_unknown_payer_is_none_not_a_guess(r):
    res = r.resolve("ALLARACARE [100163]", "HB XR ALLARACARE TMC")
    assert res.payer_id is None and not res.excluded


@pytest.mark.parametrize(
    "payer",
    [
        # TiC reporting_entity_name values (docs/etl/payer_alias_proposals.csv, approved D30)
        "UnitedHealthcare of New England, Inc.",
        "UnitedHealthcare Insurance Company",
    ],
)
def test_one_word_unitedhealthcare_resolves_to_uhc(r, payer):
    """D30: `\\bUNITED\\b` alone missed UNITEDHEALTHCARE (no word break after UNITED)."""
    assert r.resolve(payer, "").payer_id == "UHC"
