import { describe, expect, it } from 'vitest';
import { buildPriceDisplay } from './ProviderCard';
import type { CostEstimate } from '@/types';

describe('buildPriceDisplay — $0 handling', () => {
  it('shows "$0" when hospitalPayerPrice is 0 (not "—")', () => {
    const result = buildPriceDisplay(0, undefined, undefined, undefined);
    expect(result.label).toBe('$0');
    expect(result.sectionTitle).toBe('Negotiated rate');
  });

  it('shows "$0" with plan estimate when hospitalPayerPrice is 0', () => {
    const result = buildPriceDisplay(0, 500, 20, undefined);
    expect(result.label).toBe('$0');
    expect(result.sectionTitle).toBe('Your plan');
  });

  it('shows "$0" when estimate allowedMaxDollars is 0 (fallback path)', () => {
    const estimate: CostEstimate = {
      providerId: 'test',
      patientResponsibility: 0,
      allowedMaxDollars: 0,
    };
    const result = buildPriceDisplay(null, undefined, undefined, estimate);
    expect(result.label).toBe('$0');
    expect(result.label).not.toBe('—');
  });

  it('shows "$0" with plan for allowedMaxDollars=0 and full plan config', () => {
    const estimate: CostEstimate = {
      providerId: 'test',
      patientResponsibility: 0,
      allowedMaxDollars: 0,
    };
    const result = buildPriceDisplay(null, 500, 20, estimate);
    expect(result.label).toBe('$0');
    expect(result.sectionTitle).toBe('Your plan');
  });

  it('still shows "—" when no price data at all', () => {
    const result = buildPriceDisplay(null, undefined, undefined, undefined);
    expect(result.label).toBe('—');
  });

  it('still shows "—" when estimate has no allowed amount', () => {
    const estimate: CostEstimate = {
      providerId: 'test',
      patientResponsibility: 0,
    };
    const result = buildPriceDisplay(null, undefined, undefined, estimate);
    expect(result.label).toBe('—');
  });

  it('shows actual price when hospitalPayerPrice > 0', () => {
    const result = buildPriceDisplay(1279, undefined, undefined, undefined);
    expect(result.label).toBe('$1,279');
    expect(result.sectionTitle).toBe('Negotiated rate');
  });
});
