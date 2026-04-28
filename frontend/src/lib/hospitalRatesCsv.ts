export type InsurerFromRates = {
  key: string;
  label: string;
  priceColumn: string;
};

export const INSURERS_FROM_RATES: InsurerFromRates[] = [
  { key: 'bcbs', label: 'Blue Cross Blue Shield (BCBS)', priceColumn: 'bcbs_price' },
  { key: 'aetna', label: 'Aetna', priceColumn: 'aetna_price' },
  { key: 'harvard_pilgrim', label: 'Harvard Pilgrim', priceColumn: 'harvard_pilgrim_price' },
  { key: 'uhc', label: 'UnitedHealthcare (UHC)', priceColumn: 'uhc_price' },
];

export const BCBS_PLAN_OPTIONS: string[] = [
  'CHA HB BCBS HMO BLUE',
  'CHA HB BCBS INDEMNITY',
  'CHA HB BCBS PPO',
  'HB BWF MEDICAID',
  'MGH BCBS HMO BLUE',
  'MGH BCBS PPO BLUE',
];

export const BCBS_INSURER_KEY = 'bcbs';

export function isBcbsInsurerKey(key: string): boolean {
  return key.toLowerCase() === BCBS_INSURER_KEY;
}

/** Plan configs for auto-fill when user selects a carrier + plan type. */
export type PlanConfig = {
  id: string;
  payer: string;
  carrierKey: string;
  planName: string;
  planType: 'PPO' | 'HMO';
  deductible: number;
  oopMax: number;
  coinsurancePct: number;
  copaySpecialist: number;
};

export const PLAN_CONFIGS: PlanConfig[] = [
  { id: 'bcbs_ppo', payer: 'Blue Cross Blue Shield (BCBS)', carrierKey: 'bcbs', planName: 'Blue Cross PPO', planType: 'PPO', deductible: 1500, oopMax: 6000, coinsurancePct: 20, copaySpecialist: 50 },
  { id: 'bcbs_hmo', payer: 'Blue Cross Blue Shield (BCBS)', carrierKey: 'bcbs', planName: 'Blue Cross HMO Blue', planType: 'HMO', deductible: 500, oopMax: 4000, coinsurancePct: 10, copaySpecialist: 40 },
  { id: 'aetna_ppo', payer: 'Aetna', carrierKey: 'aetna', planName: 'Aetna Open Access PPO', planType: 'PPO', deductible: 2000, oopMax: 7000, coinsurancePct: 20, copaySpecialist: 50 },
  { id: 'hp_ppo', payer: 'Harvard Pilgrim', carrierKey: 'harvard_pilgrim', planName: 'Harvard Pilgrim Choice PPO', planType: 'PPO', deductible: 1500, oopMax: 6000, coinsurancePct: 20, copaySpecialist: 50 },
  { id: 'hp_hmo', payer: 'Harvard Pilgrim', carrierKey: 'harvard_pilgrim', planName: 'Harvard Pilgrim Best Buy HMO', planType: 'HMO', deductible: 500, oopMax: 4000, coinsurancePct: 10, copaySpecialist: 40 },
  { id: 'uhc_ppo', payer: 'UnitedHealthcare (UHC)', carrierKey: 'uhc', planName: 'UnitedHealthcare Choice Plus PPO', planType: 'PPO', deductible: 2000, oopMax: 7500, coinsurancePct: 20, copaySpecialist: 50 },
];

/** Get plan configs available for a given carrier key. */
export function getPlansForCarrier(carrierKey: string): PlanConfig[] {
  return PLAN_CONFIGS.filter(p => p.carrierKey === carrierKey);
}
