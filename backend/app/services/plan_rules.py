"""Service-specific plan rules for OOP estimation.

Not all services follow the same cost-sharing path. This module maps
each service type to its cost-sharing rule, so the OOP calculator
applies the correct logic per service.

Rule types:
  - "preventive"    → $0 (ACA mandate, no cost-sharing)
  - "copay_only"    → flat copay, deductible does NOT apply
  - "ded_coinsurance" → deductible applies, then coinsurance %
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanRule:
    rule_type: str  # "preventive" | "copay_only" | "ded_coinsurance"
    summary: str
    note: str | None = None


# Service category → rule mapping
# Keys are scenario_ids or CPT codes; looked up in order: scenario_id → CPT → default
_RULES_BY_SCENARIO: dict[str, PlanRule] = {
    # Preventive — $0 under ACA
    "colonoscopy_screening": PlanRule(
        "preventive",
        "Covered at 100% — no cost-sharing",
        "Preventive screening colonoscopy (age 45+, average risk) is covered at $0 under ACA Section 2713. "
        "If a polyp is found and removed, some plans reclassify as diagnostic — cost-sharing may apply retroactively.",
    ),
}

_RULES_BY_CPT: dict[str, PlanRule] = {
    # Office visits — copay only (for plans where deductible doesn't apply to specialist)
    "99213": PlanRule(
        "copay_only",
        "Specialist copay",
        "Office visit — copay applies, deductible typically does not.",
    ),
    "99214": PlanRule(
        "copay_only",
        "Specialist copay",
        "Office visit — copay applies, deductible typically does not.",
    ),
}

_DEFAULT_RULE = PlanRule("ded_coinsurance", "Deductible then coinsurance")


def get_plan_rule(
    scenario_id: str | None,
    cpt_code: str | None,
    plan_config: dict[str, Any] | None = None,
) -> PlanRule:
    """Look up the cost-sharing rule for a service.

    Priority: scenario_id override → CPT-based rule → default.
    Plan config can further refine (e.g., HMO specialist = no deductible).
    """
    # Scenario-level override (e.g., preventive colonoscopy)
    if scenario_id and scenario_id in _RULES_BY_SCENARIO:
        return _RULES_BY_SCENARIO[scenario_id]

    # CPT-level rule
    if cpt_code and cpt_code in _RULES_BY_CPT:
        rule = _RULES_BY_CPT[cpt_code]
        # Check if plan says deductible DOES apply to specialist (overrides copay_only)
        if rule.rule_type == "copay_only" and plan_config:
            if plan_config.get("deductible_applies_to_specialist", False):
                return PlanRule(
                    "ded_coinsurance",
                    "Deductible then coinsurance",
                    "This plan applies deductible to specialist visits.",
                )
        return rule

    return _DEFAULT_RULE


def estimate_patient_cost_cents(
    negotiated_rate_cents: int,
    plan_config: dict[str, Any],
    scenario_id: str | None = None,
    cpt_code: str | None = None,
    deductible_remaining_cents: int | None = None,
) -> dict[str, Any]:
    """Calculate patient OOP cost using service-specific rules.

    Returns dict with:
      scenario_a: cost if full deductible remaining
      scenario_b: cost if deductible fully met
      rule: the PlanRule applied
      note: explanation text
    """
    rule = get_plan_rule(scenario_id, cpt_code, plan_config)

    ded = plan_config.get("deductible_individual", 0) * 100  # dollars → cents
    oop_max = plan_config.get("oop_max_individual", 0) * 100
    coinsurance = plan_config.get("coinsurance_in_network", 0.20)
    copay_specialist = plan_config.get("copay_specialist", 0) * 100

    if rule.rule_type == "preventive":
        return {
            "scenario_a": 0,
            "scenario_b": 0,
            "rule_type": rule.rule_type,
            "summary": rule.summary,
            "note": rule.note,
        }

    if rule.rule_type == "copay_only":
        cost = copay_specialist
        return {
            "scenario_a": cost,
            "scenario_b": cost,
            "rule_type": rule.rule_type,
            "summary": f"${copay_specialist // 100} specialist copay",
            "note": rule.note,
        }

    # ded_coinsurance: two scenarios
    # Scenario A: full deductible remaining
    ded_portion_a = min(ded, negotiated_rate_cents)
    coins_a = int((negotiated_rate_cents - ded_portion_a) * coinsurance)
    pays_a = min(ded_portion_a + coins_a, oop_max) if oop_max else ded_portion_a + coins_a

    # Scenario B: deductible fully met
    coins_b = int(negotiated_rate_cents * coinsurance)
    pays_b = min(coins_b, oop_max) if oop_max else coins_b

    return {
        "scenario_a": pays_a,
        "scenario_b": pays_b,
        "rule_type": rule.rule_type,
        "summary": rule.summary,
        "note": rule.note,
    }
