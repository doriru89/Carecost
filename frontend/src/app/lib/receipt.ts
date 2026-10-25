/**
 * Pure receipt logic: grouping by tier, source hover text, freshness labels, cash-discount check.
 * Components render what these return; nothing here invents a number (every dollar comes from a
 * contract Money).
 */
import { hasCopy, t } from "@/contracts/copy";
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

/**
 * C2 data-quality notice (data/etl/data_quality_notices.yaml) -> its copy key. A kind the copy file does
 * not know yet falls back to the generic sentence, never to the raw kind.
 */
export function dataNoticeKey(kind: string): string {
  const key = `data_notice.${kind}`;
  return hasCopy(key) ? key : "data_notice.generic";
}

export function cellHasDollars(line: ReceiptLine): boolean {
  return line.cell != null && CELL_HAS_DOLLARS[line.cell.kind];
}

/** Both ends of a range are cited (P1 problem 2): prov for the low end, prov_high for the high end. */
export function moneySourceIds(m: Money): string[] {
  return m.prov_high && m.prov_high.source_id !== m.prov.source_id ? [m.prov.source_id, m.prov_high.source_id] : [m.prov.source_id];
}

/** The high end needs its own chip when it comes from another row than the low end. */
export function highEndProv(m: Money): Money["prov_high"] {
  if (!m.prov_high || m.low === m.high) return null;
  const a = m.prov;
  const b = m.prov_high;
  return a.source_id === b.source_id && a.row_ref === b.row_ref && a.row_id === b.row_id ? null : b;
}

/** Every source id one line points at, for chips and the freshness marks next to a number. */
export function lineSourceIds(line: ReceiptLine): string[] {
  const ids = new Set<string>();
  const c = line.cell;
  if (c) {
    if (c.kind === "money") moneySourceIds(c).forEach((id) => ids.add(id));
    else if (c.kind === "conflict") {
      moneySourceIds(c.a).forEach((id) => ids.add(id));
      moneySourceIds(c.b).forEach((id) => ids.add(id));
    } else if (c.kind === "not_published" || c.kind === "percent_only") ids.add(c.searched.source_id);
  }
  return [...ids];
}

/**
 * The list row's total: `headline` (C3 item 9), which every site carries; the full receipt is only on
 * the first `full_receipts` sites of a no-location list. Equal to receipt.totals.likely when present.
 */
export function totalText(sq: SiteQuote): string | null {
  const h = sq.headline;
  return h.likely_low != null && h.likely_high != null ? range(h.likely_low, h.likely_high, false) : null;
}

/** For cards: the low end of the total, or null when nothing can be summed. */
export function totalLow(sq: SiteQuote): number | null {
  return sq.headline.likely_low;
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
  // price_source_id is null when the site has its own price source we do not read yet (P1 problem 9)
  const ids = new Set<string>(sq.site.price_source_id ? [sq.site.price_source_id] : []);
  for (const line of sq.receipt?.lines ?? []) {
    lineSourceIds(line).forEach((id) => ids.add(id));
    if (line.list_price) moneySourceIds(line.list_price).forEach((id) => ids.add(id));
    line.doctor_fee?.by_npi?.forEach((n) => moneySourceIds(n.money).forEach((id) => ids.add(id)));
    line.elsewhere.forEach((e) => {
      if (e.cell.kind === "money") moneySourceIds(e.cell).forEach((id) => ids.add(id));
    });
  }
  for (const r of sq.other_payers) {
    r.points.forEach((p) => moneySourceIds(p.money).forEach((id) => ids.add(id)));
    if (r.cash?.kind === "money") moneySourceIds(r.cash).forEach((id) => ids.add(id));
  }
  return [...ids];
}

export type HiddenReason = "medicare_reference" | "listed_rate" | "listed_price" | "unusual";

/**
 * Whether a line's dollar figure must be folded away instead of shown as this place's price, and why.
 * - P2 / C3: rung 7 (`fee.rung_7_medicare_reference`) is a Medicare figure. For anyone not paying with
 *   Medicare it is never shown as the price: only as a labelled reference, collapsed by default.
 * - P6: availability unknown (an insurer row is never evidence the place offers it): the line's number
 *   is not this place's price; the rough range is the step's "elsewhere" or the line's peer range.
 * - P8: every row of the line is outside 1/3x-3x of its peers: "price looks unusual, being checked".
 * null = show the cell as usual.
 */
export function priceHidden(line: ReceiptLine, payment: Payment): HiddenReason | null {
  const c = line.cell;
  if (!c || (c.kind !== "money" && c.kind !== "conflict")) return null;
  if (line.doctor_fee?.explanation_key === "fee.rung_7_medicare_reference" && payment.kind !== "medicare") return "medicare_reference";
  if (line.availability === "unknown" && line.at === "this_site") return payment.kind === "insurance" ? "listed_rate" : "listed_price";
  if (line.unusual?.whole_line) return "unusual";
  return null;
}

/**
 * A chain's short name for the R12 line. The contract carries only `chain_id` (asked of C3: a display
 * name); unknown ids read "This chain".
 */
const CHAIN_NAMES: Record<string, string> = { afc_urgent_care: "AFC" };
export function chainName(chainId: string | null): string {
  return (chainId && CHAIN_NAMES[chainId]) ?? "This chain";
}

/**
 * P6 wording for a line or step that is not "offered". "Your insurer lists a rate" is said only to a
 * person paying with insurance: for Medicare, MassHealth or self-pay the engine's insurer_lists_rate
 * reason (a TiC row exists) reads as "doesn't say whether it offers this".
 */
export function availabilityKey(reason: ReceiptLine["availability_reason"], payment: Payment): string | null {
  if (!reason) return null;
  if (reason === "insurer_lists_rate" && payment.kind !== "insurance") return "receipt.availability.no_evidence";
  return `receipt.availability.${reason}`;
}
