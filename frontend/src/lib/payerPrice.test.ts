import { describe, expect, it } from 'vitest';
import { carrierKeyFromLabel, getPayerPrice, computeYourPlanEstimate, getAllPriceSources } from './payerPrice';
import type { HospitalApi } from '@/api/client';

const mockHospital: HospitalApi = {
  name: 'Test Hospital',
  hospital_id: 'test',
  lat: 42.36,
  lng: -71.06,
  doctor_count: 5,
  bcbs_price: 1278,
  aetna_price: 1349,
  harvard_pilgrim_price: 1644,
  uhc_price: 1644,
  de_identified_min: 1010,
  de_identified_max: 3264,
  gross_charge: 1222,
  discounted_cash: 305,
  cpt: '43235',
  cpt_desc: 'EGD diagnostic/biopsy',
};

describe('carrierKeyFromLabel', () => {
  it('maps BCBS variants to bcbs', () => {
    expect(carrierKeyFromLabel('Blue Cross Blue Shield of Massachusetts')).toBe('bcbs');
    expect(carrierKeyFromLabel('BCBS MA')).toBe('bcbs');
  });

  it('maps Aetna to aetna', () => {
    expect(carrierKeyFromLabel('Aetna')).toBe('aetna');
  });

  it('maps Harvard Pilgrim to harvard_pilgrim', () => {
    expect(carrierKeyFromLabel('Harvard Pilgrim Health Care')).toBe('harvard_pilgrim');
  });

  it('maps UHC/United to uhc', () => {
    expect(carrierKeyFromLabel('UnitedHealthcare')).toBe('uhc');
    expect(carrierKeyFromLabel('UHC')).toBe('uhc');
  });

  it('falls back to bcbs for unknown', () => {
    expect(carrierKeyFromLabel('Some Unknown Carrier')).toBe('bcbs');
  });
});

describe('getPayerPrice', () => {
  it('returns bcbs_price for BCBS carrier', () => {
    expect(getPayerPrice(mockHospital, 'Blue Cross')).toBe(1278);
  });

  it('returns aetna_price for Aetna carrier', () => {
    expect(getPayerPrice(mockHospital, 'Aetna')).toBe(1349);
  });

  it('returns harvard_pilgrim_price for Harvard Pilgrim', () => {
    expect(getPayerPrice(mockHospital, 'Harvard Pilgrim')).toBe(1644);
  });

  it('returns uhc_price for UHC', () => {
    expect(getPayerPrice(mockHospital, 'UnitedHealthcare')).toBe(1644);
  });

  it('returns null when payer field is null (no silent BCBS fallback)', () => {
    const h = { ...mockHospital, aetna_price: null };
    expect(getPayerPrice(h, 'Aetna')).toBeNull();
  });

  it('returns null when both payer and bcbs are null', () => {
    const h = { ...mockHospital, aetna_price: null, bcbs_price: null };
    expect(getPayerPrice(h, 'Aetna')).toBeNull();
  });
});

describe('computeYourPlanEstimate', () => {
  it('returns 0 when deductible exceeds price', () => {
    expect(computeYourPlanEstimate(1278, 2000, 20)).toBe(0);
  });

  it('computes (price - deductible) * coinsurance%', () => {
    // (2500 - 500) * 20/100 = 400
    expect(computeYourPlanEstimate(2500, 500, 20)).toBe(400);
  });

  it('handles zero deductible', () => {
    // 1000 * 20/100 = 200
    expect(computeYourPlanEstimate(1000, 0, 20)).toBe(200);
  });

  it('rounds to nearest dollar', () => {
    // (1278 - 500) * 20/100 = 155.6 → 156
    expect(computeYourPlanEstimate(1278, 500, 20)).toBe(156);
  });
});

describe('getAllPriceSources', () => {
  const fullHospital: HospitalApi = {
    ...mockHospital,
    bcbs_tic_rate: 1644,
    bcbs_tic_billing_class: 'institutional',
    turquoise_bundled_price: 2800,
    masscomparecare_total_paid: 1900,
  };

  it('returns all 8 sources when hospital has complete data', () => {
    const sources = getAllPriceSources(fullHospital, 'Blue Cross');
    expect(sources.length).toBe(8);
    expect(sources.filter(s => s.kind === 'negotiated')).toHaveLength(1);
    expect(sources.filter(s => s.kind === 'tic')).toHaveLength(1);
    expect(sources.filter(s => s.kind === 'de_identified')).toHaveLength(2);
    expect(sources.filter(s => s.kind === 'gross')).toHaveLength(1);
    expect(sources.filter(s => s.kind === 'cash')).toHaveLength(1);
    expect(sources.filter(s => s.kind === 'benchmark')).toHaveLength(2);
  });

  it('omits null sources silently', () => {
    const sparse: HospitalApi = {
      ...mockHospital,
      aetna_price: null,
      bcbs_tic_rate: undefined,
      turquoise_bundled_price: undefined,
      masscomparecare_total_paid: undefined,
      discounted_cash: null,
      gross_charge: null,
    };
    // Aetna carrier with null aetna_price → no negotiated source
    const sources = getAllPriceSources(sparse, 'Aetna');
    expect(sources.filter(s => s.kind === 'negotiated')).toHaveLength(0);
    // Only de_identified_min + de_identified_max remain
    expect(sources).toHaveLength(2);
  });

  it('returns empty array when hospital has no data', () => {
    const empty: HospitalApi = {
      name: 'Empty Hospital',
      hospital_id: 'empty',
      lat: 42.36, lng: -71.06,
      doctor_count: 0,
      bcbs_price: null,
      aetna_price: null,
      harvard_pilgrim_price: null,
      uhc_price: null,
      de_identified_min: null,
      de_identified_max: null,
      gross_charge: null,
      discounted_cash: null,
      cpt: '43235',
      cpt_desc: 'EGD diagnostic',
    };
    expect(getAllPriceSources(empty, 'BCBS')).toHaveLength(0);
  });

  it('labels negotiated source with correct carrier name', () => {
    const sources = getAllPriceSources(fullHospital, 'Harvard Pilgrim');
    const neg = sources.find(s => s.kind === 'negotiated');
    expect(neg).toBeDefined();
    expect(neg!.label).toContain('Harvard Pilgrim');
  });

  it('includes TiC billing_class in source metadata', () => {
    const sources = getAllPriceSources(fullHospital, 'BCBS');
    const tic = sources.find(s => s.kind === 'tic');
    expect(tic).toBeDefined();
    expect(tic!.billing_class).toBe('institutional');
  });
});
