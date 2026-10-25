/**
 * C3 steps (P3, P4, P9): one StepSummary per step of the quote at each site. Pure functions; every dollar
 * shown comes from a contract number (StepSummary.low/high, PeerRange, MightAdd), never from a sum made
 * here.
 */
import type { QuoteResponse, ReceiptLine, SiteQuote, StepSummary } from "@/generated/contracts/quote_api";
import { range } from "./format";

/** The step keys of a quote in path order (every site carries the same steps). */
export function stepKeys(quote: QuoteResponse): string[] {
  const seen = new Set<string>();
  for (const sq of quote.sites) for (const st of sq.steps) seen.add(st.key);
  return [...seen];
}

const humanize = (key: string) => {
  const s = key.replace(/_/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : key;
};

/** The base name of a line: the engine names hospital lines "<step>: the hospital's fee" etc. */
export const baseName = (l: ReceiptLine) => l.plain_name.split(/: the (?:hospital's|center's|doctor's) /)[0].replace(/ \(at your primary care office\)$/, "");

/**
 * A readable name per step key. C4b: `StepSummary.plain_name` (the map label). Older responses without it
 * fall back to the receipts: the line whose id is the step key, else any line of the step without its "the
 * hospital's fee" suffix, else the key itself.
 */
export function stepLabels(quote: QuoteResponse): Record<string, string> {
  const out: Record<string, string> = {};
  const lines = quote.sites.flatMap((sq) => sq.receipt?.lines ?? []);
  for (const sq of quote.sites) for (const st of sq.steps) if (st.plain_name && !out[st.key]) out[st.key] = st.plain_name;
  for (const key of stepKeys(quote)) {
    if (out[key]) continue;
    const own = lines.filter((l) => l.step_id === key || (quote.care_path == null && l.codes.join(",") === key));
    const exact = own.find((l) => l.line_id === key);
    out[key] = exact ? baseName(exact) : own[0] ? baseName(own[0]) : humanize(key);
  }
  return out;
}

export function stepOf(sq: SiteQuote, key: string): StepSummary | undefined {
  return sq.steps.find((s) => s.key === key);
}

/** Expected steps (certain / likely). Possible ones are never in the headline (P9). */
export const isExpected = (st: StepSummary) => st.likelihood === "certain" || st.likelihood === "likely";

/**
 * P4: steps this site does not do (or does not say it does), priced at the places that do; and (C4b)
 * `elsewhere_estimate` steps: offered here with no own price, shown at the typical price nearby. Neither is
 * ever this place's own price.
 */
export function elsewhereSteps(sq: SiteQuote): StepSummary[] {
  return sq.steps.filter((st) => st.figure === "elsewhere" || st.figure === "elsewhere_estimate");
}

/**
 * The step keys worth a map chip: steps some site prices itself (own or estimate). A step nobody
 * prices (e.g. a referral at your own primary care office) has nothing to put on a pin.
 */
export function mapStepKeys(quote: QuoteResponse): string[] {
  return stepKeys(quote).filter((k) =>
    quote.sites.some((sq) => {
      const st = stepOf(sq, k);
      return st != null && st.availability === "offered" && (st.figure === "own" || st.figure === "estimate");
    }),
  );
}

/** What one map pin says for one step at one site (P3, P6). `null` = no pin at all. */
export type StepPin =
  | { kind: "price"; text: string; estimated: boolean }
  | { kind: "no_price"; unusual: boolean };

/**
 * P3 / P6: a pin only where the site says it offers the step. Availability unknown (an insurer row is
 * never evidence) or not offered: no pin. Offered with its own or an estimated figure: that price.
 * Offered with no figure (no dollar amount, or every row set aside as unusual): a pin with no price,
 * never a cheap-looking one.
 */
export function stepPin(st: StepSummary | undefined): StepPin | null {
  if (!st || st.availability !== "offered") return null;
  // C4c: a from step (the doctor's bill has no number) reads "from $X", never a full price
  if ((st.figure === "own" || st.figure === "estimate") && st.low != null && st.high != null)
    return { kind: "price", text: st.from_only ? `from ${range(st.low, st.low, false)}` : range(st.low, st.high, false), estimated: st.estimated };
  return { kind: "no_price", unusual: st.unusual };
}
