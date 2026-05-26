import type { HospitalApi } from '@/api/client';
import { COMPONENT_LABELS } from '@/lib/fairHealth';

export const SETTING_LABELS: Record<string, string> = {
  both: 'Bundled',
  outpatient: 'Facility only',
  facility: 'Facility only',
};

export const PAYER_DISPLAY: Record<string, string> = {
  bcbs: 'Blue Cross Blue Shield',
  aetna: 'Aetna',
  harvard_pilgrim: 'Harvard Pilgrim',
  uhc: 'UnitedHealthcare',
};

export const PAYER_SHORT: Record<string, string> = {
  bcbs: 'BCBS',
  aetna: 'Aetna',
  harvard_pilgrim: 'Harvard Pilgrim',
  uhc: 'UHC',
};

/** Map an insurance carrier label to a payer key. Returns null if no match found. */
export function carrierKeyFromLabel(carrier: string): string | null {
  const c = carrier.toLowerCase();
  if (c.includes('blue cross') || c.includes('bcbs')) return 'bcbs';
  if (c.includes('aetna')) return 'aetna';
  if (c.includes('harvard') || c.includes('pilgrim')) return 'harvard_pilgrim';
  if (c.includes('united') || c.includes('uhc') || c.includes('unitedhealth')) return 'uhc';
  return null;
}

/** Get the negotiated price for the user's payer from payer_rates[]. MRF preferred, TiC fallback. */
export function getPayerPrice(hospital: HospitalApi, carrier: string, settingFilter?: string): number | null {
  const payerId = carrierKeyFromLabel(carrier);
  const filtered = filterRatesBySetting(hospital.payer_rates, settingFilter);
  const rates = filtered.filter(r => r.payer_id === payerId && r.negotiated_rate != null);
  if (rates.length === 0) return null;
  const mrf = rates.find(r => r.source_origin === 'mrf');
  if (mrf) return mrf.negotiated_rate;
  const tic = rates.find(r => r.source_origin === 'tic');
  if (tic) return tic.negotiated_rate;
  return rates[0].negotiated_rate;
}

/** Filter payer_rates by setting. 'facility_only' matches both outpatient and facility. */
export function filterRatesBySetting<T extends { setting: string }>(rates: T[], settingFilter?: string): T[] {
  if (!settingFilter || settingFilter === 'all') return rates;
  if (settingFilter === 'facility_only') return rates.filter(r => r.setting === 'outpatient' || r.setting === 'facility');
  return rates.filter(r => r.setting === settingFilter);
}

export type PriceSource = {
  label: string;
  price: number;
  kind: 'negotiated' | 'tic' | 'de_identified' | 'gross' | 'cash' | 'benchmark';
  billing_class?: string;
  source?: string;
  plan_count?: number;
  setting?: string;
  payer_id?: string;
  plan_name?: string;
};

/** Return ALL available price sources for a hospital, from payer_rates + benchmarks + standard fields. */
export function getAllPriceSources(hospital: HospitalApi, carrier: string, settingFilter?: string): PriceSource[] {
  const payerId = carrierKeyFromLabel(carrier);
  const sources: PriceSource[] = [];
  const filteredRates = filterRatesBySetting(hospital.payer_rates, settingFilter);

  const rateGroups = new Map<string, { rate: typeof hospital.payer_rates[0]; count: number; plans: string[] }>();
  for (const r of filteredRates) {
    if (r.negotiated_rate == null) continue;
    const key = `${r.payer_id}|${r.source_origin}|${r.negotiated_rate}`;
    const existing = rateGroups.get(key);
    if (existing) {
      existing.count++;
      if (r.plan_name) existing.plans.push(r.plan_name);
    } else {
      rateGroups.set(key, { rate: r, count: 1, plans: r.plan_name ? [r.plan_name] : [] });
    }
  }

  for (const { rate: r, count, plans } of rateGroups.values()) {
    const kind: PriceSource['kind'] = r.source_origin === 'tic' ? 'tic' : 'negotiated';
    const label = r.payer_id === payerId
      ? `${r.payer_id.toUpperCase()} negotiated rate`
      : `${r.payer_id.toUpperCase()} (${r.source_origin})`;
    sources.push({ label, price: r.negotiated_rate!, kind, billing_class: r.billing_class, plan_count: count, setting: r.setting, payer_id: r.payer_id, plan_name: count === 1 ? plans[0] : plans.join(', ') });
  }

  if (hospital.discounted_cash != null)
    sources.push({ label: 'Cash / self-pay price', price: hospital.discounted_cash, kind: 'cash' });
  if (hospital.de_identified_min != null)
    sources.push({ label: 'De-identified min (all payers)', price: hospital.de_identified_min, kind: 'de_identified' });
  if (hospital.de_identified_max != null)
    sources.push({ label: 'De-identified max (all payers)', price: hospital.de_identified_max, kind: 'de_identified' });
  if (hospital.gross_charge != null)
    sources.push({ label: 'Gross charge (list price)', price: hospital.gross_charge, kind: 'gross' });

  for (const b of hospital.benchmarks) {
    if (b.price == null) continue;
    if (b.benchmark_source === 'fair_health' && b.component in COMPONENT_LABELS) continue;
    const srcLabel = b.benchmark_source === 'fair_health'
      ? `FAIR Health ${b.component.replace(/_/g, ' ')}`
      : `${b.benchmark_source} ${b.component}`;
    sources.push({ label: srcLabel, price: b.price, kind: 'benchmark' });
  }

  return sources;
}
