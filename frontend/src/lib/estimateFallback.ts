import type { UserProfile, InsuranceProfile } from '@/types';

export function buildEstimateFallback(
  profile: UserProfile | null,
  insurance: InsuranceProfile | null,
  intakePayload: Record<string, unknown> | null,
  selectedSpecialty: string,
  selectedCrt: { bundleId: string } | null,
): Record<string, unknown> {
  const fallback: Record<string, unknown> = {
    zip: profile?.zip || '',
    insurance_carrier: insurance?.carrier || 'Blue Cross Blue Shield of Massachusetts',
    care_focus: selectedSpecialty,
    scenario_id: selectedCrt?.bundleId ?? '',
    bundle_id: selectedCrt?.bundleId ?? '',
  };
  return { ...fallback, ...(intakePayload ?? {}) };
}
