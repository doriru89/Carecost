import GiProcedureWizard from '@/components/GiProcedureWizard';
import type { GiProcedureSelection } from '@/lib/giDecisionTree';
import type { ProcedureStepProps } from '@/lib/specialties/types';

/** GI: symptom tree → CPT / bundle for estimates. */
export function GastroProcedureStep({
  procedureState,
  setProcedureState,
  symptomNotes,
  setSymptomNotes,
}: ProcedureStepProps) {
  return (
    <GiProcedureWizard
      value={procedureState as GiProcedureSelection | null}
      onChange={setProcedureState}
      symptomNotes={symptomNotes}
      onSymptomNotesChange={setSymptomNotes}
    />
  );
}
