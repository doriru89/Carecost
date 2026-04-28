import type { HospitalApi } from '@/api/client';

type PayerField = 'bcbs_price' | 'aetna_price' | 'harvard_pilgrim_price' | 'uhc_price';

const CARRIER_TO_FIELD: Record<string, PayerField> = {
  bcbs: 'bcbs_price',
  aetna: 'aetna_price',
  harvard_pilgrim: 'harvard_pilgrim_price',
  uhc: 'uhc_price',
};

/** Map an insurance carrier label to a payer key. */
export function carrierKeyFromLabel(carrier: string): string {
  const c = carrier.toLowerCase();
  if (c.includes('blue cross') || c.includes('bcbs')) return 'bcbs';
  if (c.includes('aetna')) return 'aetna';
  if (c.includes('harvard') || c.includes('pilgrim')) return 'harvard_pilgrim';
  if (c.includes('united') || c.includes('uhc') || c.includes('unitedhealth')) return 'uhc';
  return 'bcbs';
}

/** Get the negotiated price for the user's payer. Returns null if unavailable — NO fallback. */
export function getPayerPrice(hospital: HospitalApi, carrier: string): number | null {
  const key = carrierKeyFromLabel(carrier);
  const field = CARRIER_TO_FIELD[key] ?? 'bcbs_price';
  return (hospital[field] as number | null) ?? null;
}

export type PriceSource = {
  label: string;
  price: number;
  kind: 'negotiated' | 'tic' | 'de_identified' | 'gross' | 'cash' | 'benchmark';
  billing_class?: string;
  source?: string;
};

/** Return ALL available price sources for a hospital, labeled by what they are. */
export function getAllPriceSources(hospital: HospitalApi, carrier: string): PriceSource[] {
  const carrierPrice = getPayerPrice(hospital, carrier);
  const carrierKey = carrierKeyFromLabel(carrier);
  const carrierLabel = {
    bcbs: 'BCBS', aetna: 'Aetna', harvard_pilgrim: 'Harvard Pilgrim', uhc: 'UHC',
  }[carrierKey] ?? carrier;

  const sources: (PriceSource | null)[] = [
    carrierPrice != null
      ? { label: `${carrierLabel} negotiated rate`, price: carrierPrice, kind: 'negotiated' }
      : null,
    hospital.bcbs_tic_rate != null
      ? { label: 'BCBS TiC (insurer-reported)', price: hospital.bcbs_tic_rate, kind: 'tic', billing_class: hospital.bcbs_tic_billing_class }
      : null,
    hospital.discounted_cash != null
      ? { label: 'Cash / self-pay price', price: hospital.discounted_cash, kind: 'cash' }
      : null,
    hospital.de_identified_min != null
      ? { label: 'De-identified min (all payers)', price: hospital.de_identified_min, kind: 'de_identified' }
      : null,
    hospital.de_identified_max != null
      ? { label: 'De-identified max (all payers)', price: hospital.de_identified_max, kind: 'de_identified' }
      : null,
    hospital.gross_charge != null
      ? { label: 'Gross charge (list price)', price: hospital.gross_charge, kind: 'gross' }
      : null,
    hospital.turquoise_bundled_price != null
      ? { label: 'Turquoise bundled estimate', price: hospital.turquoise_bundled_price, kind: 'benchmark' }
      : null,
    hospital.masscomparecare_total_paid != null
      ? { label: 'MassCompareCare claims-paid', price: hospital.masscomparecare_total_paid, kind: 'benchmark' }
      : null,
    hospital.fh_physician_in_network != null
      ? { label: 'FAIR Health physician (in-network)', price: hospital.fh_physician_in_network, kind: 'benchmark' }
      : null,
    hospital.fh_facility_hosp_in_network != null
      ? { label: 'FAIR Health facility (hospital)', price: hospital.fh_facility_hosp_in_network, kind: 'benchmark' }
      : null,
    hospital.fh_anesthesia_in_network != null
      ? { label: 'FAIR Health anesthesia', price: hospital.fh_anesthesia_in_network, kind: 'benchmark' }
      : null,
    hospital.fh_pathology_in_network != null
      ? { label: 'FAIR Health pathology', price: hospital.fh_pathology_in_network, kind: 'benchmark' }
      : null,
  ];

  return sources.filter((s): s is PriceSource => s != null);
}

/** Estimate patient cost: (negotiated_rate - deductible) * coinsurance%. */
export function computeYourPlanEstimate(
  payerPrice: number,
  deductible: number,
  coinsurancePct: number,
): number {
  const afterDeductible = Math.max(0, payerPrice - deductible);
  return Math.round(afterDeductible * coinsurancePct / 100);
}
