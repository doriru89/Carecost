import type { HospitalApi } from '@/api/client';

/** Map an insurance carrier label to a payer key. */
export function carrierKeyFromLabel(carrier: string): string {
  const c = carrier.toLowerCase();
  if (c.includes('blue cross') || c.includes('bcbs')) return 'bcbs';
  if (c.includes('aetna')) return 'aetna';
  if (c.includes('harvard') || c.includes('pilgrim')) return 'harvard_pilgrim';
  if (c.includes('united') || c.includes('uhc') || c.includes('unitedhealth')) return 'uhc';
  return 'bcbs';
}

/** Get the negotiated price for the user's payer from payer_rates[]. MRF preferred, TiC fallback. */
export function getPayerPrice(hospital: HospitalApi, carrier: string): number | null {
  const payerId = carrierKeyFromLabel(carrier);
  const rates = hospital.payer_rates.filter(r => r.payer_id === payerId && r.negotiated_rate != null);
  if (rates.length === 0) return null;
  const mrf = rates.find(r => r.source_origin === 'mrf');
  if (mrf) return mrf.negotiated_rate;
  const tic = rates.find(r => r.source_origin === 'tic');
  if (tic) return tic.negotiated_rate;
  return rates[0].negotiated_rate;
}

export type PriceSource = {
  label: string;
  price: number;
  kind: 'negotiated' | 'tic' | 'de_identified' | 'gross' | 'cash' | 'benchmark';
  billing_class?: string;
  source?: string;
};

/** Return ALL available price sources for a hospital, from payer_rates + benchmarks + standard fields. */
export function getAllPriceSources(hospital: HospitalApi, carrier: string): PriceSource[] {
  const payerId = carrierKeyFromLabel(carrier);
  const sources: PriceSource[] = [];

  for (const r of hospital.payer_rates) {
    if (r.negotiated_rate == null) continue;
    const kind: PriceSource['kind'] = r.source_origin === 'tic' ? 'tic' : 'negotiated';
    const label = r.payer_id === payerId
      ? `${r.payer_id.toUpperCase()} negotiated rate`
      : `${r.payer_id.toUpperCase()} (${r.source_origin})`;
    sources.push({ label, price: r.negotiated_rate, kind, billing_class: r.billing_class });
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
    const srcLabel = b.benchmark_source === 'fair_health'
      ? `FAIR Health ${b.component.replace(/_/g, ' ')}`
      : `${b.benchmark_source} ${b.component}`;
    sources.push({ label: srcLabel, price: b.price, kind: 'benchmark' });
  }

  return sources;
}
