/**
 * Browser-local GI continuity (per logged-in email or guest). Not a substitute for server-side PHI storage.
 */

import type { GiProcedureSelection } from '@/lib/giDecisionTree';

const STORAGE_VERSION = 1 as const;
const PREFIX = 'carecost_gi_continuity_v';

export type StoredGiProcedure = {
  bundleId: string;
  scenarioId: string;
  cptCode: string;
  title: string;
  description?: string;
  pathIds?: string[];
};

export type GiContinuitySnapshot = {
  v: typeof STORAGE_VERSION;
  updatedAt: string;
  careFocus: string;
  insuranceCarrier?: string;
  symptomNotes: string;
  procedure: StoredGiProcedure | null;
};

function key(userEmail: string | null | undefined): string {
  const id = (userEmail ?? '').trim() || 'guest';
  return `${PREFIX}${STORAGE_VERSION}_${id}`;
}

export function loadGiContinuity(userEmail: string | null | undefined): GiContinuitySnapshot | null {
  try {
    const raw = localStorage.getItem(key(userEmail));
    if (!raw) return null;
    const p = JSON.parse(raw) as GiContinuitySnapshot;
    if (p.v !== STORAGE_VERSION || typeof p.updatedAt !== 'string') return null;
    return p;
  } catch {
    return null;
  }
}

export function saveGiContinuity(
  userEmail: string | null | undefined,
  patch: Partial<Omit<GiContinuitySnapshot, 'v'>> & Pick<GiContinuitySnapshot, 'careFocus' | 'symptomNotes' | 'procedure'>,
): void {
  try {
    const prev = loadGiContinuity(userEmail);
    const next: GiContinuitySnapshot = {
      v: STORAGE_VERSION,
      updatedAt: new Date().toISOString(),
      careFocus: patch.careFocus ?? prev?.careFocus ?? 'Gastroenterology',
      insuranceCarrier: patch.insuranceCarrier ?? prev?.insuranceCarrier,
      symptomNotes: patch.symptomNotes ?? prev?.symptomNotes ?? '',
      procedure: patch.procedure !== undefined ? patch.procedure : prev?.procedure ?? null,
    };
    localStorage.setItem(key(userEmail), JSON.stringify(next));
  } catch {
    /* quota / private mode */
  }
}

export function selectionToStored(sel: GiProcedureSelection): StoredGiProcedure {
  return {
    bundleId: sel.bundleId,
    scenarioId: sel.scenarioId,
    cptCode: sel.cptCode,
    title: sel.title,
    description: sel.description,
    pathIds: sel.pathIds,
  };
}

export function clearGiContinuity(userEmail: string | null | undefined): void {
  try {
    localStorage.removeItem(key(userEmail));
  } catch {
    /* ignore */
  }
}

/** Clear both guest and a specific user (e.g. on logout). */
export function clearAllGiContinuityForLogout(userEmail: string | null | undefined): void {
  clearGiContinuity(null);
  clearGiContinuity(userEmail);
}
