export interface Provider {
  id: string;
  name: string;
  specialty: string[];
  address: string;
  lat: number;
  lng: number;
  phone?: string;
  inNetwork?: boolean;
  distance?: number;
  hospital?: string;
}

export interface CostEstimate {
  providerId: string;
  procedureCode?: string;
  procedureName?: string;
  totalCost?: number;
  deductibleApplied?: number;
  copay?: number;
  coinsurance?: number;
  /** Upper end of estimated OOP band for your plan (USD whole dollars). */
  patientResponsibility: number;
  /** Lower end of your-plan OOP band (USD). */
  oopMin?: number;
  /** Upper end of your-plan OOP band (USD). */
  oopMax?: number;
  /** Min of other payers' OOP lower bounds (USD). */
  otherInsurersOopMin?: number;
  /** Max of other payers' OOP upper bounds (USD). */
  otherInsurersOopMax?: number;
  /** Backend payer key used for primary estimate. */
  payerUsed?: string;
  /** Negotiated allowed amount (USD) from payer rate row — used when OOP band is $0 on pin. */
  allowedMinDollars?: number;
  allowedMaxDollars?: number;
  note?: string;
}

export interface UserProfile {
  fullName: string;
  dob?: string;
  zip: string;
  phone?: string;
  /** Set after full onboarding wizard. */
  onboardingCompleted?: boolean;
}

export interface InsuranceProfile {
  carrier: string;
  planName: string;
  memberId?: string;
  planType: 'PPO' | 'HMO' | 'EPO' | 'Other';
  deductible: number;
  oopMax: number;
  copay?: number;
  coinsurance?: number;
}

export interface OnboardingData {
  profile: UserProfile;
  insurance: InsuranceProfile;
  careFocus: string;
}
