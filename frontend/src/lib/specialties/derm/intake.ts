import type { DermProcedureSelection } from './dermDecisionTree';

export function isDermProcedureComplete(state: unknown): boolean {
  if (state == null || typeof state !== 'object') return false;
  const s = state as Partial<DermProcedureSelection>;
  return Boolean(s.bundleId && s.scenarioId && s.cptCode);
}

export function buildDermProcedureIntake(
  state: unknown,
  ctx: { symptomNotes: string },
): Record<string, unknown> {
  const sel = state as DermProcedureSelection | null;
  if (!sel) return {};
  return {
    specialty: 'Dermatology',
    scenario_id: sel.scenarioId,
    bundle_id: sel.bundleId,
    cpt_code: sel.cptCode,
    procedure_label: sel.title,
    symptom_decision_path: sel.pathIds.join(' → '),
    ...(ctx.symptomNotes.trim() ? { free_text: ctx.symptomNotes.trim() } : {}),
  };
}
