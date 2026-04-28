/**
 * Central list of onboarding specialties. To add one:
 * 1) Add `yourSpecialty/intake.ts` (isComplete + buildProcedureIntake) and `YourProcedureStep.tsx`.
 * 2) Import them below and append a new object to SPECIALTY_PLUGINS.
 * 3) Ensure backend bundles / CPT mapping exist for that specialty’s intake fields.
 */
import type { SpecialtyPlugin } from '@/lib/specialties/types';
import { buildGastroProcedureIntake, isGastroProcedureComplete } from '@/lib/specialties/gastro/intake';
import { GastroProcedureStep } from '@/lib/specialties/gastro/GastroProcedureStep';
import { buildDermProcedureIntake, isDermProcedureComplete } from '@/lib/specialties/derm/intake';
import { DermProcedureStep } from '@/lib/specialties/derm/DermProcedureStep';

export const SPECIALTY_PLUGINS: readonly SpecialtyPlugin[] = [
  {
    id: 'Gastroenterology',
    label: 'Gastroenterology',
    procedureStep: {
      title: 'Find your procedure',
      description:
        'We match your symptoms and answers to a CPT code so map and list prices use the correct hospital rates for that procedure.',
    },
    isProcedureComplete: isGastroProcedureComplete,
    buildProcedureIntake: buildGastroProcedureIntake,
    ProcedureStep: GastroProcedureStep,
  },
  {
    id: 'Dermatology',
    label: 'Dermatology',
    procedureStep: {
      title: 'Find your procedure',
      description:
        'Answer a few questions about your skin concern. We map your answers to a CPT code for hospital price comparison.',
    },
    isProcedureComplete: isDermProcedureComplete,
    buildProcedureIntake: buildDermProcedureIntake,
    ProcedureStep: DermProcedureStep,
  },
];

/** All rows shown in the specialty dropdown; `available: false` means disabled (coming soon). */
export type SpecialtySelectOption = {
  id: string;
  label: string;
  available: boolean;
};

export const SPECIALTY_SELECT_OPTIONS: readonly SpecialtySelectOption[] = [
  { id: 'Gastroenterology', label: 'Gastroenterology', available: true },
  { id: 'Dermatology', label: 'Dermatology', available: true },
];

export const DEFAULT_SPECIALTY_ID = SPECIALTY_PLUGINS[0].id;

export function getSpecialtyPlugin(id: string): SpecialtyPlugin | undefined {
  return SPECIALTY_PLUGINS.find(p => p.id === id);
}
