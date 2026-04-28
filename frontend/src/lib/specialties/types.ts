import type { ComponentType } from 'react';

/** Props passed to every specialty’s procedure questionnaire step (wizard). */
export type ProcedureStepProps = {
  procedureState: unknown;
  setProcedureState: (value: unknown) => void;
  symptomNotes: string;
  setSymptomNotes: (value: string) => void;
};

/**
 * One specialty’s onboarding slice: metadata, intake mapping, and UI for the procedure step.
 * Add a new specialty by implementing this shape and appending to SPECIALTY_PLUGINS in registry.tsx.
 */
export type SpecialtyPlugin = {
  id: string;
  label: string;
  procedureStep: {
    title: string;
    description?: string;
  };
  isProcedureComplete: (procedureState: unknown) => boolean;
  /** Fields merged into intake after base profile/insurance; omit keys you don’t need. */
  buildProcedureIntake: (
    procedureState: unknown,
    ctx: { symptomNotes: string },
  ) => Record<string, unknown>;
  ProcedureStep: ComponentType<ProcedureStepProps>;
};
