"""Tests for plan_rules.py — the OOP rule engine."""

from app.services.plan_rules import get_plan_rule, estimate_patient_cost_cents


BCBS_HMO_CONFIG = {
    "deductible_individual": 500,
    "oop_max_individual": 4000,
    "coinsurance_in_network": 0.10,
    "copay_specialist": 40,
    "deductible_applies_to_specialist": False,
}

BCBS_PPO_CONFIG = {
    "deductible_individual": 1500,
    "oop_max_individual": 6000,
    "coinsurance_in_network": 0.20,
    "copay_specialist": 50,
    "deductible_applies_to_specialist": True,
}


class TestGetPlanRule:
    def test_preventive_screening_returns_preventive(self) -> None:
        rule = get_plan_rule("colonoscopy_screening", "45378")
        assert rule.rule_type == "preventive"

    def test_office_visit_99213_returns_copay_for_hmo(self) -> None:
        rule = get_plan_rule(None, "99213", BCBS_HMO_CONFIG)
        assert rule.rule_type == "copay_only"

    def test_office_visit_99213_returns_ded_coinsurance_for_ppo(self) -> None:
        """PPO with deductible_applies_to_specialist=True overrides copay_only."""
        rule = get_plan_rule(None, "99213", BCBS_PPO_CONFIG)
        assert rule.rule_type == "ded_coinsurance"

    def test_diagnostic_returns_ded_coinsurance(self) -> None:
        rule = get_plan_rule("colonoscopy_diagnostic", "45380")
        assert rule.rule_type == "ded_coinsurance"


class TestEstimatePatientCostCents:
    def test_preventive_is_zero(self) -> None:
        result = estimate_patient_cost_cents(
            127900,
            BCBS_HMO_CONFIG,
            scenario_id="colonoscopy_screening",
            cpt_code="45378",
        )
        assert result["scenario_a"] == 0
        assert result["scenario_b"] == 0
        assert result["rule_type"] == "preventive"

    def test_copay_only_for_office_visit(self) -> None:
        result = estimate_patient_cost_cents(
            25000,
            BCBS_HMO_CONFIG,
            scenario_id=None,
            cpt_code="99213",
        )
        assert result["scenario_a"] == 4000  # $40 copay in cents
        assert result["scenario_b"] == 4000
        assert result["rule_type"] == "copay_only"

    def test_ded_coinsurance_scenario_a(self) -> None:
        """Scenario A: full deductible remaining."""
        result = estimate_patient_cost_cents(
            127900,
            BCBS_HMO_CONFIG,
            scenario_id="colonoscopy_diagnostic",
            cpt_code="45380",
        )
        # ded=500*100=50000, rate=127900
        # ded_portion = min(50000, 127900) = 50000
        # coins = int((127900 - 50000) * 0.10) = int(7790) = 7790
        # pays = min(50000 + 7790, 400000) = 57790
        assert result["scenario_a"] == 57790
        assert result["rule_type"] == "ded_coinsurance"

    def test_ded_coinsurance_scenario_b(self) -> None:
        """Scenario B: deductible fully met."""
        result = estimate_patient_cost_cents(
            127900,
            BCBS_HMO_CONFIG,
            scenario_id="colonoscopy_diagnostic",
            cpt_code="45380",
        )
        # coins = int(127900 * 0.10) = 12790
        assert result["scenario_b"] == 12790

    def test_oop_max_caps_cost(self) -> None:
        """Very high rate should be capped at OOP max."""
        result = estimate_patient_cost_cents(
            5000000,
            BCBS_HMO_CONFIG,  # $50,000 rate
            scenario_id=None,
            cpt_code="45380",
        )
        assert result["scenario_a"] <= 400000  # $4,000 OOP max in cents
