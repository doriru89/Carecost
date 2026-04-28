import { describe, it, expect } from 'vitest';
import { buildEstimateFallback } from './estimateFallback';
import type { UserProfile, InsuranceProfile } from '@/types';

const aetnaInsurance: InsuranceProfile = {
  carrier: 'Aetna',
  planName: 'Commercial PPO',
  planType: 'PPO',
  deductible: 1500,
  oopMax: 6500,
  coinsurance: 20,
};

const profile: UserProfile = {
  fullName: 'Test User',
  zip: '02215',
};

describe('buildEstimateFallback', () => {
  it('uses insurance.carrier when intakePayload is null', () => {
    const result = buildEstimateFallback(profile, aetnaInsurance, null, 'Gastroenterology', null);
    expect(result.insurance_carrier).toBe('Aetna');
  });

  it('uses profile.zip when intakePayload is null', () => {
    const result = buildEstimateFallback(profile, aetnaInsurance, null, 'Gastroenterology', null);
    expect(result.zip).toBe('02215');
  });

  it('intakePayload overrides fallback when present', () => {
    const intake = { insurance_carrier: 'Blue Cross Blue Shield of Massachusetts', zip: '02101' };
    const result = buildEstimateFallback(profile, aetnaInsurance, intake, 'Gastroenterology', null);
    expect(result.insurance_carrier).toBe('Blue Cross Blue Shield of Massachusetts');
    expect(result.zip).toBe('02101');
  });

  it('falls back to Boston defaults when profile and insurance are null', () => {
    const result = buildEstimateFallback(null, null, null, 'Gastroenterology', null);
    expect(result.zip).toBe('02118');
    expect(result.insurance_carrier).toContain('Blue Cross');
  });

  it('uses selectedCrt bundleId for scenario_id and bundle_id', () => {
    const crt = { bundleId: 'egd_with_biopsy' };
    const result = buildEstimateFallback(null, null, null, 'Gastroenterology', crt);
    expect(result.bundle_id).toBe('egd_with_biopsy');
    expect(result.scenario_id).toBe('egd_with_biopsy');
  });
});
