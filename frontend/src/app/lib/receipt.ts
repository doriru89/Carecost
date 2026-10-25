/**
 * Pure receipt logic: grouping by tier, source hover text, freshness labels, cash-discount check.
 * Components render what these return; nothing here invents a number (every dollar comes from a
 * contract Money).
 */
import { t } from "@/contracts/copy";
import { CELL_HAS_DOLLARS, TIER_ORDER } from "@/contracts/exhaustive";
import type {
  CertaintyTier,
  Money,
  Payment,
  QuoteResponse,
  ReceiptLine,
  SiteQuote,
  SourceInfo,
} from "@/generated/contracts/quote_api";
import { isoDate, range } from "./format";

export interface TierSection {
  tier: CertaintyTier;
  lines: ReceiptLine[];
}

/** D8: sections strongest first; empty tiers are dropped. Order inside a tier is the engine's. */
export function sections(lines: ReceiptLine[]): TierSection[] {
  const tiers = (Object.keys(TIER_ORDER) as CertaintyTier[]).sort((a, b) => TIER_ORDER[a] - TIER_ORDER[b]);
  return tiers
    .map((tier) => ({ tier, lines: lines.filter((l) => l.tier === tier) }))
    .filter((s) => s.lines.length > 0);
}

/** The §2.2 hover sentence for a number's chip, from the response's own source record. */
export function sourceHover(info: SourceInfo | undefined, sourceId: string): string {
  if (!info) return `Source ${sourceId}`;
  const date = info.freshness.last_updated ?? info.freshness.fetched_at;
  return t(`source_hover.${info.source_kind}`, { publisher: info.publisher, date: isoDate(date) });
}

export type FreshnessState = "current" | "late" | "stale";

/** (a) and (b) are never merged: a stale-on-our-side source is never called late (contract rule). */
export function freshnessState(info: SourceInfo | undefined): FreshnessState {
  if (!info) return "current";
  if (info.freshness.stale_on_our_side) return "stale";
  if (info.freshness.late_to_refresh) return "late";
  return "current";
}

export function freshnessLabel(state: FreshnessState): string {
  return t(state === "late" ? "fresh.late_label" : state === "stale" ? "fresh.stale_label" : "fresh.current_label");
}

export function freshnessDetail(info: SourceInfo): string {
  const f = info.freshness;
  if (f.stale_on_our_side)
    return `We last downloaded it ${isoDate(f.fetched_at)} and were due again ${isoDate(f.our_refresh_due)}. ${t(`fresh.ours.${f.our_rule}`)}`;
  if (f.late_to_refresh)
    return `The publisher's file is dated ${isoDate(f.last_updated)}; a newer one was due by ${isoDate(f.expected_by)}. ${t(`fresh.source.${f.source_rule}`)}`;
  return `File dated ${isoDate(f.last_updated)} · we downloaded it ${isoDate(f.fetched_at)}.`;
}

/** P1 problem 16: a cash price identical to the gross charge is not a discount. */
export function noCashDiscount(line: ReceiptLine, payment: Payment): boolean {
  if (payment.kind !== "cash" || !line.list_price || line.cell?.kind !== "money") return false;
  return line.cell.low === line.list_price.low && line.cell.high === line.list_price.high;
}

export function cellHasDollars(line: ReceiptLine): boolean {
  return line.cell != null && CELL_HAS_DOLLARS[line.cell.kind];
}

/** Every source id one line points at, for chips and the freshness marks next to a number. */
export function lineSourceIds(line: ReceiptLine): string[] {
  const ids = new Set<string>();
  const c = line.cell;
  if (c) {
    if (c.kind === "money") ids.add(c.prov.source_id);
    else if (c.kind === "conflict") {
      ids.add(c.a.prov.source_id);
      ids.add(c.b.prov.source_id);
    } else if (c.kind === "not_published" || c.kind === "percent_only") ids.add(c.searched.source_id);
  }
  return [...ids];
}

export function totalText(sq: SiteQuote): string | null {
  const l = sq.receipt.totals.likely;
  return l ? range(l.low, l.high, false) : null;
}

/** For pins and cards: the low end of the total, or null when nothing can be summed. */
export function totalLow(sq: SiteQuote): number | null {
  return sq.receipt.totals.likely?.low ?? null;
}

export function moneyText(m: Money): string {
  return range(m.low, m.high);
}

/** Response-level summary used by tests and the payment-switch timer. */
export function quoteKey(q: QuoteResponse): string {
  const p = q.payment;
  return `${p.kind === "insurance" ? `${p.payer_id}:${p.product}` : p.kind}|${q.care_path?.id ?? q.service_codes.join(",")}`;
}

/** Sources one site's receipt points at (its lines, list prices, range bar, by-NPI, its own price source). */
export function siteSourceIds(sq: SiteQuote): string[] {
  const ids = new Set<string>([sq.site.price_source_id]);
  for (const line of sq.receipt.lines) {
    lineSourceIds(line).forEach((id) => ids.add(id));
    if (line.list_price) ids.add(line.list_price.prov.source_id);
    line.doctor_fee?.by_npi?.forEach((n) => ids.add(n.money.prov.source_id));
    line.elsewhere.forEach((e) => {
      if (e.cell.kind === "money") ids.add(e.cell.prov.source_id);
    });
  }
  for (const r of sq.other_payers) {
    r.points.forEach((p) => ids.add(p.money.prov.source_id));
    if (r.cash?.kind === "money") ids.add(r.cash.prov.source_id);
  }
  return [...ids];
}
