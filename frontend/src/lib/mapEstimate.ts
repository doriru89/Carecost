import type { CostEstimate } from '@/types';
import type { ProviderEstimateApi } from '@/api/client';

/** Map API estimate row to CostEstimate for map + ProviderCard. */
export function apiEstimateToCostEstimate(e: ProviderEstimateApi): CostEstimate {
  const minDollars = Math.round(e.oop_range.min / 100);
  const maxDollars = Math.round(e.oop_range.max / 100);
  const allowedMin = Math.round(e.allowed_amount_range.min / 100);
  const allowedMax = Math.round(e.allowed_amount_range.max / 100);

  let otherMin: number | undefined;
  let otherMax: number | undefined;
  if (e.other_insurers_oop_range) {
    otherMin = Math.round(e.other_insurers_oop_range.min / 100);
    otherMax = Math.round(e.other_insurers_oop_range.max / 100);
  }

  return {
    providerId: String(e.provider_id),
    procedureName: `Allowed $${allowedMin.toLocaleString()}–$${allowedMax.toLocaleString()} (est.)`,
    patientResponsibility: maxDollars,
    oopMin: minDollars,
    oopMax: maxDollars,
    otherInsurersOopMin: otherMin,
    otherInsurersOopMax: otherMax,
    payerUsed: e.payer_used ?? undefined,
    allowedMinDollars: allowedMin,
    allowedMaxDollars: allowedMax,
    note: [
      `Your OOP range (demo): $${minDollars.toLocaleString()}–$${maxDollars.toLocaleString()}.`,
      ...e.assumptions,
      e.provenance.map(p => `${p.field}: ${p.source} (${p.kind}, ${Math.round(p.confidence * 100)}%)`).join(' · '),
      'Call your plan to verify coverage and cost.',
    ].join(' '),
  };
}

/**
 * Single dollar amount on map pins: your-plan **max OOP** when &gt; 0; otherwise
 * **negotiated allowed** (~$) so pins still show a number when OOP math rounds to $0
 * but payer rates exist. Re-seed the database if everything is still "—" (missing `prices` rows for bundle).
 */
export function formatPinPrice(e: CostEstimate): string {
  const oop = e.oopMax ?? e.patientResponsibility;
  if (oop > 0) return `$${oop.toLocaleString()}`;
  const allowed = e.allowedMaxDollars ?? e.allowedMinDollars;
  if (allowed != null && allowed > 0) return `~$${allowed.toLocaleString()}`;
  return '—';
}
