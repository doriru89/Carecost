import _planConfigs from '../generated/plan_configs.json';

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
  deductibleAppliesToSpecialist?: boolean;
};

export const PLAN_CONFIGS: PlanConfig[] = _planConfigs as PlanConfig[];

/** Get plan configs available for a given carrier key. */
export function getPlansForCarrier(carrierKey: string): PlanConfig[] {
  return PLAN_CONFIGS.filter(p => p.carrierKey === carrierKey);
}
