/**
 * GI and Derm procedure lists derived from bundles.json (SSOT).
 * Data-only module — no React dependencies.
 */

import registry from '@/generated/bundles.json';

export interface CrtOption {
  cpt: string;
  label: string;
  desc: string;
  bundleId: string;
}

export const GI_PROCEDURES: CrtOption[] = Object.entries(registry.bundles)
  .filter(([, b]) => b.specialty === 'Gastroenterology')
  .map(([bundleId, b]) => ({
    cpt: b.cpt,
    label: b.label,
    desc: b.description,
    bundleId,
  }));

export const DERM_PROCEDURE_LIST: { cpt: string; label: string; bundleId: string }[] =
  Object.entries(registry.bundles)
    .filter(([, b]) => b.specialty === 'Dermatology')
    .map(([bundleId, b]) => ({
      cpt: b.cpt,
      label: b.label,
      bundleId,
    }));
