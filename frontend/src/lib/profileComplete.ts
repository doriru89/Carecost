import type { InsuranceProfile, UserProfile } from '@/types';

/** Minimum profile fields for pricing and identity. */
export function isUserProfileComplete(p: UserProfile | null | undefined): boolean {
  if (!p?.fullName?.trim() || !p?.zip?.trim()) return false;
  if (!p.dob?.trim()) return false;
  return true;
}

/** Carrier, plan, plan type, deductible, OOP max, and coinsurance (0 allowed) for map estimates. */
export function isInsuranceProfileComplete(i: InsuranceProfile | null | undefined): boolean {
  if (!i?.carrier?.trim() || !i.planName?.trim()) return false;
  if (!i.planType) return false;
  if (i.deductible == null || Number.isNaN(Number(i.deductible)) || i.deductible < 0) return false;
  if (i.oopMax == null || Number.isNaN(Number(i.oopMax)) || i.oopMax < 0) return false;
  if (i.coinsurance == null || Number.isNaN(Number(i.coinsurance)) || i.coinsurance < 0 || i.coinsurance > 100) {
    return false;
  }
  return true;
}
