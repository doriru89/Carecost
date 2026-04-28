import type { PlanConfig } from './hospitalRatesCsv';

export type OopResult = {
  ruleType: 'preventive' | 'copay_only' | 'ded_coinsurance';
  estimate: number; // dollars, scenario A (full deductible remaining)
  estimateB: number; // dollars, scenario B (deductible met)
  explanation: string;
};

const PREVENTIVE_SCENARIOS = new Set(['colonoscopy_screening']);
const COPAY_CPTS = new Set(['99213', '99214', '99203']);

/** Compute OOP estimate using service-specific plan rules. All amounts in dollars. */
export function computeOop(
  negotiatedRate: number,
  plan: PlanConfig,
  scenarioId: string | null,
  cptCode: string | null,
): OopResult {
  // Rule 1: Preventive = $0
  if (scenarioId && PREVENTIVE_SCENARIOS.has(scenarioId)) {
    return {
      ruleType: 'preventive',
      estimate: 0,
      estimateB: 0,
      explanation: 'Preventive screening covered at 100% under ACA. No cost-sharing.',
    };
  }

  // Rule 2: Copay-only (office visits)
  if (cptCode && COPAY_CPTS.has(cptCode)) {
    return {
      ruleType: 'copay_only',
      estimate: plan.copaySpecialist,
      estimateB: plan.copaySpecialist,
      explanation: `Your plan applies a flat $${plan.copaySpecialist} specialist copay. Deductible does not apply.`,
    };
  }

  // Rule 3: Deductible + coinsurance
  const ded = plan.deductible;
  const coinsPct = plan.coinsurancePct / 100;

  // Scenario A: full deductible remaining
  const dedPortion = Math.min(ded, negotiatedRate);
  const coinsA = Math.round((negotiatedRate - dedPortion) * coinsPct);
  const paysA = plan.oopMax > 0
    ? Math.min(dedPortion + coinsA, plan.oopMax)
    : dedPortion + coinsA;

  // Scenario B: deductible met
  const coinsB = Math.round(negotiatedRate * coinsPct);
  const paysB = plan.oopMax > 0 ? Math.min(coinsB, plan.oopMax) : coinsB;

  return {
    ruleType: 'ded_coinsurance',
    estimate: paysA,
    estimateB: paysB,
    explanation: `$${plan.deductible} deductible then ${plan.coinsurancePct}% coinsurance on $${negotiatedRate.toLocaleString()} negotiated rate.`,
  };
}
