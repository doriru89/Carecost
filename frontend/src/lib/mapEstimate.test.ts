import { describe, expect, it } from 'vitest';
import { apiEstimateToCostEstimate } from './mapEstimate';

describe('apiEstimateToCostEstimate', () => {
  it('maps cents to dollars in note and patientResponsibility', () => {
    const out = apiEstimateToCostEstimate({
      provider_id: '1',
      allowed_amount_range: { min: 500000, max: 800000, currency: 'USD' },
      oop_range: { min: 5000, max: 15000 },
      provenance: [
        { field: 'allowed_amount_max', source: 'mrf_sample', confidence: 0.9, kind: 'FACT' },
      ],
      assumptions: ['Demo assumption'],
    });
    expect(out.patientResponsibility).toBe(150);
    expect(out.procedureName).toContain('Allowed $5,000');
    expect(out.note).toContain('Demo assumption');
    expect(out.note).toContain('FACT');
  });
});
