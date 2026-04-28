import { describe, expect, it } from 'vitest';
import { computeOop } from './oopRules';
import type { PlanConfig } from './hospitalRatesCsv';

const bcbsHmo: PlanConfig = {
  id: 'bcbs_hmo', payer: 'BCBS', carrierKey: 'bcbs',
  planName: 'Blue Cross HMO Blue', planType: 'HMO',
  deductible: 500, oopMax: 4000, coinsurancePct: 10, copaySpecialist: 40,
};

const bcbsPpo: PlanConfig = {
  id: 'bcbs_ppo', payer: 'BCBS', carrierKey: 'bcbs',
  planName: 'Blue Cross PPO', planType: 'PPO',
  deductible: 1500, oopMax: 6000, coinsurancePct: 20, copaySpecialist: 50,
};

describe('computeOop', () => {
  it('returns $0 for preventive screening colonoscopy', () => {
    const result = computeOop(1279, bcbsHmo, 'colonoscopy_screening', '45378');
    expect(result.ruleType).toBe('preventive');
    expect(result.estimate).toBe(0);
    expect(result.explanation).toContain('ACA');
  });

  it('returns copay for office visit (HMO, 99213)', () => {
    const result = computeOop(250, bcbsHmo, null, '99213');
    expect(result.ruleType).toBe('copay_only');
    expect(result.estimate).toBe(40); // $40 copay
    expect(result.explanation).toContain('copay');
  });

  it('returns ded+coinsurance for diagnostic (45380)', () => {
    const result = computeOop(1279, bcbsHmo, 'colonoscopy_diagnostic', '45380');
    expect(result.ruleType).toBe('ded_coinsurance');
    // Scenario A: min(500 + (1279-500)*0.10, 4000) = 500 + 77.9 = 577.9 → 578
    expect(result.estimate).toBe(578);
  });

  it('caps at OOP max', () => {
    const result = computeOop(50000, bcbsHmo, null, '45380');
    expect(result.estimate).toBeLessThanOrEqual(4000);
  });

  it('PPO office visit still uses copay (not ded+coinsurance)', () => {
    const result = computeOop(250, bcbsPpo, null, '99213');
    expect(result.ruleType).toBe('copay_only');
    expect(result.estimate).toBe(50); // PPO copay is $50
  });
});
