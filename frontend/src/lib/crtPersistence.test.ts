import { describe, it, expect, beforeEach } from 'vitest';
import { saveCrt, loadCrt } from './crtPersistence';

const testCrt = { cpt: '43239', label: 'EGD with biopsy', bundleId: 'egd_with_biopsy' };

describe('CRT persistence', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('saves selectedCrt to sessionStorage', () => {
    saveCrt(testCrt);
    const stored = sessionStorage.getItem('carecost_selectedCrt');
    expect(stored).toBeTruthy();
    expect(JSON.parse(stored!)).toEqual(testCrt);
  });

  it('restores selectedCrt from sessionStorage', () => {
    sessionStorage.setItem('carecost_selectedCrt', JSON.stringify(testCrt));
    const result = loadCrt(null);
    expect(result).toEqual(testCrt);
  });

  it('falls back to intakePayload when sessionStorage empty', () => {
    const intake = { cpt_code: '43239', procedure_label: 'EGD with biopsy', bundle_id: 'egd_with_biopsy' };
    const result = loadCrt(intake);
    expect(result).toEqual({ cpt: '43239', label: 'EGD with biopsy', bundleId: 'egd_with_biopsy' });
  });

  it('prefers sessionStorage over intakePayload', () => {
    const otherCrt = { cpt: '43249', label: 'EGD with dilation', bundleId: 'egd_dilation' };
    sessionStorage.setItem('carecost_selectedCrt', JSON.stringify(otherCrt));
    const intake = { cpt_code: '43239', procedure_label: 'EGD with biopsy', bundle_id: 'egd_with_biopsy' };
    const result = loadCrt(intake);
    expect(result).toEqual(otherCrt);
  });

  it('returns null when both empty', () => {
    const result = loadCrt(null);
    expect(result).toBeNull();
  });

  it('clears sessionStorage when null is saved', () => {
    saveCrt(testCrt);
    expect(sessionStorage.getItem('carecost_selectedCrt')).toBeTruthy();
    saveCrt(null);
    expect(sessionStorage.getItem('carecost_selectedCrt')).toBeNull();
  });
});
