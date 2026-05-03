"""Service-specific plan rules for OOP estimation.

Rules are loaded from data/registries/plan_rules.yaml (SSOT shared with frontend).

Rule types:
  - "preventive"    → $0 (ACA mandate, no cost-sharing)
  - "copay_only"    → flat copay, deductible does NOT apply
  - "ded_coinsurance" → deductible applies, then coinsurance %
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.registries import get_plan_rules


@dataclass(frozen=True)
class PlanRule:
    rule_type: str  # "preventive" | "copay_only" | "ded_coinsurance"
    summary: str
    note: str | None = None


def _rules_by_scenario() -> dict[str, PlanRule]:
    cfg = get_plan_rules()
    return {sid: PlanRule(r.rule_type, r.summary, r.note) for sid, r in cfg.scenario_rules.items()}


def _rules_by_cpt() -> dict[str, PlanRule]:
    cfg = get_plan_rules()
    return {cpt: PlanRule(r.rule_type, r.summary, r.note) for cpt, r in cfg.cpt_rules.items()}


def _default_rule() -> PlanRule:
    cfg = get_plan_rules()
    return PlanRule(cfg.default_rule.rule_type, cfg.default_rule.summary, cfg.default_rule.note)


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
    by_scenario = _rules_by_scenario()
    if scenario_id and scenario_id in by_scenario:
        return by_scenario[scenario_id]

    # CPT-level rule
    by_cpt = _rules_by_cpt()
    if cpt_code and cpt_code in by_cpt:
        rule = by_cpt[cpt_code]
        if rule.rule_type == "copay_only" and plan_config:
            if plan_config.get("deductible_applies_to_specialist", False):
                return PlanRule(
                    "ded_coinsurance",
                    "Deductible then coinsurance",
                    "This plan applies deductible to specialist visits.",
                )
        return rule

    return _default_rule()


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
