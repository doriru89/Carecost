import type { Benchmark } from '@/api/client';

export type FairHealthComponent = {
  label: string;
  amount: number;
};

export type FairHealthBreakdown = {
  total: number;
  components: FairHealthComponent[];
};

export const COMPONENT_LABELS: Record<string, string> = {
  physician_in_network: 'Physician',
  facility_hosp_in_network: 'Facility',
  anesthesia_in_network: 'Anesthesia',
  pathology_in_network: 'Pathology',
};

/** Sum FAIR Health 80th percentile in-network hospital components from benchmarks[]. Returns null if none found. */
export function computeFairHealthTotal(benchmarks: Benchmark[]): FairHealthBreakdown | null {
  const fh = benchmarks.filter(
    b => b.benchmark_source === 'fair_health' && b.price != null && b.price > 0 && b.component in COMPONENT_LABELS
  );
  if (fh.length === 0) return null;

  const components: FairHealthComponent[] = [];
  let total = 0;
  for (const b of fh) {
    components.push({ label: COMPONENT_LABELS[b.component], amount: b.price! });
    total += b.price!;
  }
  return { total, components };
}
