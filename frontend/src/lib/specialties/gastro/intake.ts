import type { GiProcedureSelection } from '@/lib/giDecisionTree';

export function isGastroProcedureComplete(state: unknown): boolean {
  if (state == null || typeof state !== 'object') return false;
  const s = state as Partial<GiProcedureSelection>;
  return Boolean(s.bundleId && s.scenarioId && s.cptCode);
}

export function buildGastroProcedureIntake(
  state: unknown,
  ctx: { symptomNotes: string },
): Record<string, unknown> {
  const sel = state as GiProcedureSelection | null;
  if (!sel) return {};
  return {
    scenario_id: sel.scenarioId,
    bundle_id: sel.bundleId,
    cpt_code: sel.cptCode,
    procedure_label: sel.title,
    symptom_decision_path: sel.pathIds.join(' → '),
    ...(ctx.symptomNotes.trim() ? { free_text: ctx.symptomNotes.trim() } : {}),
  };
}
