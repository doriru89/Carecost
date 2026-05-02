import { GI_PROCEDURES as EGD_PROCEDURES } from '@/lib/procedures';

export type SelectedCrt = { cpt: string; label: string; bundleId: string };

const CRT_KEY = 'carecost_selectedCrt';

export function saveCrt(val: SelectedCrt | null): void {
  if (val) sessionStorage.setItem(CRT_KEY, JSON.stringify(val));
  else sessionStorage.removeItem(CRT_KEY);
}

export function loadCrt(intakePayload: Record<string, unknown> | null): SelectedCrt | null {
  const stored = sessionStorage.getItem(CRT_KEY);
  if (stored) {
    try { return JSON.parse(stored); } catch { /* corrupt data — fall through */ }
  }
  if (typeof intakePayload?.cpt_code === 'string' && intakePayload.cpt_code) {
    const match = EGD_PROCEDURES.find(p => p.cpt === intakePayload.cpt_code);
    if (match) return { cpt: match.cpt, label: match.label, bundleId: match.bundleId };
    return {
      cpt: intakePayload.cpt_code as string,
      label: (intakePayload.procedure_label as string) ?? (intakePayload.cpt_code as string),
      bundleId: (intakePayload.bundle_id as string) ?? (intakePayload.cpt_code as string),
    };
  }
  return null;
}
