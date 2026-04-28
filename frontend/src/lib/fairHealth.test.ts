import { describe, expect, it } from 'vitest';
import { computeFairHealthTotal } from './fairHealth';

describe('computeFairHealthTotal', () => {
  it('sums all 4 components when present', () => {
    const result = computeFairHealthTotal({
      fh_physician_in_network: 604,
      fh_facility_hosp_in_network: 2133,
      fh_anesthesia_in_network: 853,
      fh_pathology_in_network: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.total).toBe(3590); // 604+2133+853
    expect(result!.components).toHaveLength(3); // pathology=0 excluded
  });

  it('returns null when all fields are null', () => {
    const result = computeFairHealthTotal({
      fh_physician_in_network: null,
      fh_facility_hosp_in_network: null,
      fh_anesthesia_in_network: null,
      fh_pathology_in_network: null,
    });
    expect(result).toBeNull();
  });

  it('sums partial data — only available components', () => {
    const result = computeFairHealthTotal({
      fh_physician_in_network: 500,
      fh_facility_hosp_in_network: null,
      fh_anesthesia_in_network: 300,
      fh_pathology_in_network: null,
    });
    expect(result).not.toBeNull();
    expect(result!.total).toBe(800);
    expect(result!.components).toHaveLength(2);
  });

  it('labels components correctly', () => {
    const result = computeFairHealthTotal({
      fh_physician_in_network: 604,
      fh_facility_hosp_in_network: 2133,
      fh_anesthesia_in_network: 853,
      fh_pathology_in_network: null,
    });
    const labels = result!.components.map(c => c.label);
    expect(labels).toContain('Physician');
    expect(labels).toContain('Facility');
    expect(labels).toContain('Anesthesia');
    expect(labels).not.toContain('Pathology');
  });
});
