import { describe, expect, it } from 'vitest';
import { carrierKeyFromLabel, getPayerPrice, getAllPriceSources, filterRatesBySetting } from './payerPrice';
import type { HospitalApi } from '@/api/client';

const mockHospital: HospitalApi = {
  name: 'Test Hospital',
  hospital_id: 'test',
  system_name: 'Test System',
  metro_area: 'boston',
  neighborhood: 'Back Bay',
  lat: 42.36,
  lng: -71.06,
  doctor_count: 5,
  cpt: '43239',
  cpt_desc: 'EGD diagnostic/biopsy',
  gross_charge: 1222,
  discounted_cash: 305,
  de_identified_min: 1010,
  de_identified_max: 3264,
  payer_rates: [
    { payer_id: 'bcbs', negotiated_rate: 1278, plan_name: 'BCBS PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
    { payer_id: 'bcbs', negotiated_rate: 1644, plan_name: 'BCBS TiC', source_origin: 'tic', billing_class: 'institutional', setting: 'facility' },
    { payer_id: 'aetna', negotiated_rate: 1349, plan_name: 'Aetna PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
    { payer_id: 'harvard_pilgrim', negotiated_rate: 1644, plan_name: 'HP PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'outpatient' },
    { payer_id: 'uhc', negotiated_rate: 1644, plan_name: 'UHC PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
  ],
  benchmarks: [
    { benchmark_source: 'turquoise', component: 'total', price: 2800, quality_rating: 4.2 },
    { benchmark_source: 'masscomparecare', component: 'total', price: 1900, quality_rating: null },
    { benchmark_source: 'fair_health', component: 'physician_in_network', price: 941, quality_rating: null },
    { benchmark_source: 'fair_health', component: 'facility_hosp_in_network', price: 2350, quality_rating: null },
  ],
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

  it('returns null for unknown carrier', () => {
    expect(carrierKeyFromLabel('Some Unknown Carrier')).toBeNull();
    expect(carrierKeyFromLabel('Oscar Health')).toBeNull();
  });
});

describe('getPayerPrice', () => {
  it('returns negotiated rate for matching payer_id', () => {
    expect(getPayerPrice(mockHospital, 'Blue Cross')).toBe(1278);
  });

  it('returns aetna rate for Aetna carrier', () => {
    expect(getPayerPrice(mockHospital, 'Aetna')).toBe(1349);
  });

  it('prefers MRF over TiC source_origin', () => {
    expect(getPayerPrice(mockHospital, 'BCBS')).toBe(1278);
  });

  it('falls back to TiC when no MRF exists', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'bcbs', negotiated_rate: 1644, plan_name: 'TiC', source_origin: 'tic', billing_class: 'institutional', setting: 'facility' },
      ],
    };
    expect(getPayerPrice(h, 'BCBS')).toBe(1644);
  });

  it('returns null for empty payer_rates (NOT $0)', () => {
    const h: HospitalApi = { ...mockHospital, payer_rates: [] };
    expect(getPayerPrice(h, 'BCBS')).toBeNull();
  });

  it('returns 0 (not null) when negotiated_rate is 0', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'bcbs', negotiated_rate: 0, plan_name: 'BCBS PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
      ],
    };
    const result = getPayerPrice(h, 'BCBS');
    expect(result).toBe(0);
    expect(result).not.toBeNull();
  });

  it('returns 0 for rate=0 with MRF source preference', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'bcbs', negotiated_rate: 0, plan_name: 'BCBS MRF', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'bcbs', negotiated_rate: 500, plan_name: 'BCBS TiC', source_origin: 'tic', billing_class: 'institutional', setting: 'facility' },
      ],
    };
    expect(getPayerPrice(h, 'BCBS')).toBe(0);
  });

  it('returns null for unknown payer with no matching rates', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'aetna', negotiated_rate: 1349, plan_name: '', source_origin: 'mrf', billing_class: '', setting: 'both' },
      ],
    };
    expect(getPayerPrice(h, 'Some Unknown Carrier')).toBeNull();
  });
});

describe('getAllPriceSources', () => {
  it('returns sources from payer_rates + standard fields + benchmarks (FAIR Health components excluded)', () => {
    const sources = getAllPriceSources(mockHospital, 'Blue Cross');
    expect(sources.length).toBeGreaterThanOrEqual(6);
    expect(sources.filter(s => s.kind === 'negotiated').length).toBeGreaterThanOrEqual(1);
    expect(sources.filter(s => s.kind === 'de_identified')).toHaveLength(2);
    expect(sources.filter(s => s.kind === 'gross')).toHaveLength(1);
    expect(sources.filter(s => s.kind === 'cash')).toHaveLength(1);
    expect(sources.filter(s => s.kind === 'benchmark').length).toBeGreaterThanOrEqual(2);
    expect(sources.filter(s => s.label.includes('FAIR Health')).length).toBe(0);
  });

  it('omits null rates silently', () => {
    const sparse: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'aetna', negotiated_rate: null, plan_name: '', source_origin: 'mrf', billing_class: '', setting: 'both' },
      ],
      discounted_cash: null,
      gross_charge: null,
      benchmarks: [],
    };
    const sources = getAllPriceSources(sparse, 'Aetna');
    expect(sources.filter(s => s.kind === 'negotiated')).toHaveLength(0);
    expect(sources).toHaveLength(2);
  });

  it('returns empty array when hospital has no data', () => {
    const empty: HospitalApi = {
      ...mockHospital,
      payer_rates: [],
      de_identified_min: null,
      de_identified_max: null,
      gross_charge: null,
      discounted_cash: null,
      benchmarks: [],
    };
    expect(getAllPriceSources(empty, 'BCBS')).toHaveLength(0);
  });

  it('labels user carrier negotiated rate correctly', () => {
    const sources = getAllPriceSources(mockHospital, 'Harvard Pilgrim');
    const neg = sources.find(s => s.kind === 'negotiated' && s.label.includes('HARVARD_PILGRIM'));
    expect(neg).toBeDefined();
    expect(neg!.label).toContain('negotiated rate');
  });

  it('includes billing_class in payer rate sources', () => {
    const sources = getAllPriceSources(mockHospital, 'BCBS');
    const neg = sources.find(s => s.kind === 'negotiated' && s.label.includes('BCBS'));
    expect(neg).toBeDefined();
    expect(neg!.billing_class).toBe('institutional');
  });

  it('deduplicates same payer+source+rate across plan variants', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'harvard_pilgrim', negotiated_rate: 762, plan_name: 'HPHC PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'harvard_pilgrim', negotiated_rate: 762, plan_name: 'HPHC HMO/POS', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'harvard_pilgrim', negotiated_rate: 762, plan_name: 'HPHC Alliance PPO A', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'harvard_pilgrim', negotiated_rate: 762, plan_name: 'HPHC Alliance PPO B', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'harvard_pilgrim', negotiated_rate: 762, plan_name: 'HPHC Non Preferred B', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
      ],
      benchmarks: [],
      discounted_cash: null,
      de_identified_min: null,
      de_identified_max: null,
      gross_charge: null,
    };
    const sources = getAllPriceSources(h, 'Harvard Pilgrim');
    expect(sources).toHaveLength(1);
    expect(sources[0].price).toBe(762);
    expect(sources[0].plan_count).toBe(5);
  });

  it('preserves distinct rates for same payer', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'uhc', negotiated_rate: 762, plan_name: 'UHC PPO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'uhc', negotiated_rate: 762, plan_name: 'UHC HMO', source_origin: 'mrf', billing_class: 'institutional', setting: 'both' },
        { payer_id: 'uhc', negotiated_rate: 1584, plan_name: 'UHC Navigate', source_origin: 'mrf', billing_class: 'institutional', setting: 'outpatient' },
      ],
      benchmarks: [],
      discounted_cash: null,
      de_identified_min: null,
      de_identified_max: null,
      gross_charge: null,
    };
    const sources = getAllPriceSources(h, 'UHC');
    expect(sources).toHaveLength(2);
    expect(sources.find(s => s.price === 762)?.plan_count).toBe(2);
    expect(sources.find(s => s.price === 1584)?.plan_count).toBe(1);
  });
});

describe('getPayerPrice with settingFilter', () => {
  it('without filter returns same as before (backward compatible)', () => {
    expect(getPayerPrice(mockHospital, 'Blue Cross')).toBe(1278);
    expect(getPayerPrice(mockHospital, 'Blue Cross', undefined)).toBe(1278);
    expect(getPayerPrice(mockHospital, 'Blue Cross', 'all')).toBe(1278);
  });

  it('setting filter narrows to matching rates', () => {
    expect(getPayerPrice(mockHospital, 'Blue Cross', 'both')).toBe(1278);
    expect(getPayerPrice(mockHospital, 'Blue Cross', 'facility')).toBe(1644);
  });

  it('returns null when no rates match the filter', () => {
    expect(getPayerPrice(mockHospital, 'Blue Cross', 'outpatient')).toBeNull();
  });

  it('MRF preference still applies after setting filter', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'bcbs', negotiated_rate: 900, plan_name: 'TiC', source_origin: 'tic', billing_class: 'institutional', setting: 'outpatient' },
        { payer_id: 'bcbs', negotiated_rate: 1200, plan_name: 'MRF', source_origin: 'mrf', billing_class: '', setting: 'outpatient' },
      ],
    };
    expect(getPayerPrice(h, 'BCBS', 'outpatient')).toBe(1200);
  });
});

describe('getAllPriceSources with settingFilter', () => {
  it('respects setting filter', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [
        { payer_id: 'bcbs', negotiated_rate: 1000, plan_name: 'A', source_origin: 'mrf', billing_class: '', setting: 'both' },
        { payer_id: 'aetna', negotiated_rate: 2000, plan_name: 'B', source_origin: 'mrf', billing_class: '', setting: 'outpatient' },
      ],
      benchmarks: [],
      discounted_cash: null,
      de_identified_min: null,
      de_identified_max: null,
      gross_charge: null,
    };
    const both = getAllPriceSources(h, 'BCBS', 'both');
    expect(both.filter(s => s.kind === 'negotiated')).toHaveLength(1);
    expect(both.find(s => s.kind === 'negotiated')?.price).toBe(1000);
  });
});

describe('FAIR Health deduplication', () => {
  it('excludes composited FAIR Health components from getAllPriceSources', () => {
    const h: HospitalApi = {
      ...mockHospital,
      payer_rates: [],
      discounted_cash: null,
      de_identified_min: null,
      de_identified_max: null,
      gross_charge: null,
      benchmarks: [
        { benchmark_source: 'fair_health', component: 'physician_in_network', price: 604, quality_rating: null },
        { benchmark_source: 'fair_health', component: 'facility_hosp_in_network', price: 2133, quality_rating: null },
        { benchmark_source: 'fair_health', component: 'anesthesia_in_network', price: 853, quality_rating: null },
        { benchmark_source: 'fair_health', component: 'physician_oon', price: 1118, quality_rating: null },
        { benchmark_source: 'turquoise', component: 'total', price: 2800, quality_rating: 4.2 },
      ],
    };
    const sources = getAllPriceSources(h, 'BCBS');
    const fhSources = sources.filter(s => s.label.includes('FAIR Health'));
    expect(fhSources).toHaveLength(1);
    expect(fhSources[0].label).toContain('physician oon');
    expect(sources.find(s => s.label.includes('turquoise'))).toBeDefined();
  });
});

describe('filterRatesBySetting', () => {
  const rates = [
    { setting: 'both', price: 100 },
    { setting: 'outpatient', price: 200 },
    { setting: 'facility', price: 300 },
  ];

  it('returns all when filter is undefined or "all"', () => {
    expect(filterRatesBySetting(rates)).toHaveLength(3);
    expect(filterRatesBySetting(rates, 'all')).toHaveLength(3);
  });

  it('filters to matching setting', () => {
    expect(filterRatesBySetting(rates, 'both')).toHaveLength(1);
    expect(filterRatesBySetting(rates, 'outpatient')[0].price).toBe(200);
  });

  it('returns empty for nonexistent setting', () => {
    expect(filterRatesBySetting(rates, 'inpatient')).toHaveLength(0);
  });

  it('facility_only matches both outpatient and facility', () => {
    expect(filterRatesBySetting(rates, 'facility_only')).toHaveLength(2);
    expect(filterRatesBySetting(rates, 'facility_only').map(r => r.setting)).toEqual(['outpatient', 'facility']);
  });
});
