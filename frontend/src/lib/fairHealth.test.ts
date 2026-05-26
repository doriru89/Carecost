import { describe, expect, it } from 'vitest';
import { computeFairHealthTotal } from './fairHealth';
import type { Benchmark } from '@/api/client';

describe('computeFairHealthTotal', () => {
  it('sums all fair_health components when present', () => {
    const benchmarks: Benchmark[] = [
      { benchmark_source: 'fair_health', component: 'physician_in_network', price: 604, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'facility_hosp_in_network', price: 2133, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'anesthesia_in_network', price: 853, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'pathology_in_network', price: 0, quality_rating: null },
    ];
    const result = computeFairHealthTotal(benchmarks);
    expect(result).not.toBeNull();
    expect(result!.total).toBe(3590);
    expect(result!.components).toHaveLength(3);
  });

  it('returns null when no fair_health benchmarks exist', () => {
    const benchmarks: Benchmark[] = [
      { benchmark_source: 'turquoise', component: 'total', price: 2800, quality_rating: 4.2 },
    ];
    expect(computeFairHealthTotal(benchmarks)).toBeNull();
  });

  it('returns null for empty benchmarks array', () => {
    expect(computeFairHealthTotal([])).toBeNull();
  });

  it('sums partial data — only available components', () => {
    const benchmarks: Benchmark[] = [
      { benchmark_source: 'fair_health', component: 'physician_in_network', price: 500, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'anesthesia_in_network', price: 300, quality_rating: null },
    ];
    const result = computeFairHealthTotal(benchmarks);
    expect(result).not.toBeNull();
    expect(result!.total).toBe(800);
    expect(result!.components).toHaveLength(2);
  });

  it('maps component names to human labels', () => {
    const benchmarks: Benchmark[] = [
      { benchmark_source: 'fair_health', component: 'physician_in_network', price: 604, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'facility_hosp_in_network', price: 2133, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'anesthesia_in_network', price: 853, quality_rating: null },
    ];
    const result = computeFairHealthTotal(benchmarks);
    const labels = result!.components.map(c => c.label);
    expect(labels).toContain('Physician');
    expect(labels).toContain('Facility');
    expect(labels).toContain('Anesthesia');
  });

  it('excludes out-of-network and ASC alternative components', () => {
    const benchmarks: Benchmark[] = [
      { benchmark_source: 'fair_health', component: 'physician_in_network', price: 735, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'physician_oon', price: 1118, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'facility_hosp_in_network', price: 1923, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'facility_asc_in_network', price: 908, quality_rating: null },
      { benchmark_source: 'fair_health', component: 'anesthesia_in_network', price: 770, quality_rating: null },
    ];
    const result = computeFairHealthTotal(benchmarks);
    expect(result!.total).toBe(735 + 1923 + 770);
    expect(result!.components).toHaveLength(3);
    expect(result!.components.every(c => !c.label.includes('oon') && !c.label.includes('asc'))).toBe(true);
  });
});
