import { describe, expect, it } from 'vitest';
import { buildPriceDisplay } from './ProviderCard';
import type { CostEstimate } from '@/types';
import type { OopResult } from '@/lib/oopRules';

describe('buildPriceDisplay — format-only', () => {
  it('shows "$0" when hospitalPayerPrice is 0 (not "—")', () => {
    const result = buildPriceDisplay(0, undefined);
    expect(result.label).toBe('$0');
    expect(result.sectionTitle).toBe('Negotiated rate');
  });

  it('shows "$0" with OOP result for preventive', () => {
    const oop: OopResult = {
      ruleType: 'preventive',
      estimate: 0,
      estimateB: 0,
      explanation: 'ACA preventive',
    };
    const result = buildPriceDisplay(0, undefined, oop);
    expect(result.label).toBe('$0');
    expect(result.sectionTitle).toBe('Your plan');
  });

  it('shows "$0" when estimate allowedMaxDollars is 0 (fallback path)', () => {
    const estimate: CostEstimate = {
      providerId: 'test',
      patientResponsibility: 0,
      allowedMaxDollars: 0,
    };
    const result = buildPriceDisplay(null, estimate);
    expect(result.label).toBe('$0');
    expect(result.label).not.toBe('—');
  });

  it('still shows "—" when no price data at all', () => {
    const result = buildPriceDisplay(null, undefined);
    expect(result.label).toBe('—');
  });

  it('still shows "—" when estimate has no allowed amount', () => {
    const estimate: CostEstimate = {
      providerId: 'test',
      patientResponsibility: 0,
    };
    const result = buildPriceDisplay(null, estimate);
    expect(result.label).toBe('—');
  });

  it('shows actual price when hospitalPayerPrice > 0 and no OOP', () => {
    const result = buildPriceDisplay(1279, undefined);
    expect(result.label).toBe('$1,279');
    expect(result.sectionTitle).toBe('Negotiated rate');
  });

  it('shows OOP estimate when OopResult provided', () => {
    const oop: OopResult = {
      ruleType: 'ded_coinsurance',
      estimate: 578,
      estimateB: 128,
      explanation: '$500 deductible then 10% coinsurance',
    };
    const result = buildPriceDisplay(1279, undefined, oop);
    expect(result.label).toBe('$578');
    expect(result.sectionTitle).toBe('Your plan');
    expect(result.tooltip).toContain('deductible');
  });

  it('shows copay estimate for copay_only rule', () => {
    const oop: OopResult = {
      ruleType: 'copay_only',
      estimate: 40,
      estimateB: 40,
      explanation: 'Flat $40 specialist copay',
    };
    const result = buildPriceDisplay(250, undefined, oop);
    expect(result.label).toBe('$40');
    expect(result.sectionTitle).toBe('Your plan');
  });

  it('shows CTA tooltip when no OOP result for hospital price', () => {
    const result = buildPriceDisplay(1279, undefined);
    expect(result.tooltip).toContain('insurance');
  });
});
