/**
 * C4b (Austin 2026-10-25): what a person reads first. Pure functions over the contract's HeadlineRange,
 * QuoteOption and StepSummary; every dollar shown is a contract number (never a sum made here).
 *
 * The range rule (final): the headline is `headline_range.low`–`high`, the certain + likely steps. Possible
 * steps (`may_also_order`) are listed on their own and are never in it. `from_only` = the doctor's fee has
 * no public source: "from $X — the doctor bills separately", never the full price.
 */
import { t } from "@/contracts/copy";
import { CHEAPEST_BASIS_KEY, HEADLINE_BASIS_KEY, ORDERING_BY_OPTION, STEP_FIGURE } from "@/contracts/exhaustive";
import type {
  HeadlineRange,
  MayAlsoOrder,
  Money,
  QuoteOption,
  QuoteResponse,
  ReceiptLine,
  SiteQuote,
  SourceInfo,
  StepSummary,
} from "@/generated/contracts/quote_api";
import { range } from "./format";

/** "$193–$207", or "from $149 — the doctor bills separately" (whole dollars: a headline, not a line). */
export function headlineText(hr: HeadlineRange): string {
  if (hr.from_only) return t("headline.from", { low: range(hr.low, hr.low, false), note: t("headline.doctor_bills_separately") });
  return range(hr.low, hr.high, false);
}

const lower = (s: string) => (s ? s[0].toLowerCase() + s.slice(1) : s);

/** A plain list: "a", "a and b", "a, b and c". */
export function plainList(items: string[]): string {
  const xs = items.map(lower);
  if (xs.length <= 1) return xs.join("");
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

/** The one plain line under a headline: what the range covers. No `includes` = the doctor visit only. */
export function includesText(hr: HeadlineRange): string {
  return hr.includes.length ? t("headline.includes", { items: plainList(hr.includes) }) : t("headline.visit_only");
}

/** The basis line under a headline, or null when the figure is the place's own prices (complete). */
export function basisText(hr: HeadlineRange): string | null {
  const k = HEADLINE_BASIS_KEY[hr.basis];
  return k ? t(k) : null;
}

/** "about $X–$Y (typical price nearby)": an elsewhere / elsewhere_estimate figure, never this place's own price. */
export function nearbyText(low: number, high: number, cents = false): string {
  return t("nearby.about", { range: range(low, high, cents) });
}

/** One possible step's figure in plain words, by where it comes from (MayAlsoOrder.figure). */
export function mayAlsoFigure(m: MayAlsoOrder): string {
  if (m.low == null || m.high == null) return t("may_also.no_price");
  switch (STEP_FIGURE[m.figure]) {
    case "own":
      return m.figure === "estimate" ? `${range(m.low, m.high, false)} · ${t("receipt.estimate_tag").toLowerCase()}` : range(m.low, m.high, false);
    case "nearby":
      return nearbyText(m.low, m.high);
    case "none":
      return t("may_also.no_price");
  }
}

export interface MayAlsoGroup {
  /** exclusive_group id: its members are alternatives ("one of these") */
  group: string | null;
  items: MayAlsoOrder[];
}

/** Possible steps in path order; members of one exclusive_group are kept together as "one of these". */
export function mayAlsoGroups(list: MayAlsoOrder[]): MayAlsoGroup[] {
  const out: MayAlsoGroup[] = [];
  const byGroup = new Map<string, MayAlsoGroup>();
  for (const m of list) {
    if (m.exclusive_group) {
      const g = byGroup.get(m.exclusive_group);
      if (g) g.items.push(m);
      else {
        const ng = { group: m.exclusive_group, items: [m] };
        byGroup.set(m.exclusive_group, ng);
        out.push(ng);
      }
    } else out.push({ group: null, items: [m] });
  }
  return out;
}

/** The honest words next to "cheapest place for this" (D-UI-1). */
export function cheapestText(basis: QuoteOption["cheapest_basis"]): string | null {
  return basis ? t(CHEAPEST_BASIS_KEY[basis]) : null;
}

export interface OptionGroup {
  /** null: the quote has no entry options (one group of every site) */
  option: QuoteOption | null;
  /** this option's sites, in the server's order (distance by default, or price) */
  sites: SiteQuote[];
  /** the engine's cheapest_site_id, when it is in this response */
  cheapest: SiteQuote | null;
  /** 2–3 alternates: the next sites in the server's order, the cheapest left out */
  alternates: SiteQuote[];
}

export const ALTERNATES = 3;

/**
 * D-UI-1 / D-UI-3: the first screen, one block per entry option. The cheapest is the engine's
 * `cheapest_site_id` (lowest headline low within the best completeness basis present): the frontend never
 * picks one itself. A quote without options is one group with no cheapest mark.
 */
export function optionGroups(quote: QuoteResponse): OptionGroup[] {
  if (quote.options.length === 0) {
    return [{ option: null, sites: quote.sites, cheapest: null, alternates: quote.sites.slice(0, ALTERNATES) }];
  }
  return quote.options.map((option) => {
    const sites = quote.sites.filter((s) => s.option_id === option.id);
    const cheapest = sites.find((s) => s.site.site_id === option.cheapest_site_id) ?? null;
    const alternates = sites.filter((s) => s !== cheapest).slice(0, ALTERNATES);
    return { option, sites, cheapest, alternates };
  });
}

export function byOption(quote: QuoteResponse): boolean {
  return ORDERING_BY_OPTION[quote.ordering];
}

/** "A: Urgent care or primary care" etc. Options are lettered in the server's order. */
export function optionLetter(quote: QuoteResponse, optionId: string | null): string | null {
  if (!optionId) return null;
  const i = quote.options.findIndex((o) => o.id === optionId);
  return i < 0 ? null : String.fromCharCode(65 + i);
}

/** The option a site is in, when the quote has options. */
export function siteOption(quote: QuoteResponse, sq: SiteQuote): QuoteOption | null {
  return quote.options.find((o) => o.id === sq.option_id) ?? null;
}

/** An option's own range, "$136–$413", or null when it has none (unpriced, or no site with a range). */
export function optionRangeText(o: QuoteOption): string | null {
  return o.low != null && o.high != null ? range(o.low, o.high, false) : null;
}

/* ---------------- the plain source footnote (D-UI-2, Fact / Inferred / Assumed in plain words) ---------------- */

export type FootnoteKind = "fact" | "estimate" | "nearby" | "none";

export interface Footnote {
  kind: FootnoteKind;
  text: string;
}

/**
 * Where one line's number came from, in plain words:
 * - fact: their own published price (hospital file, posted page), their insurer's file, or a government fee;
 * - estimate: an estimate from nearby places of the same kind (P5);
 * - none: not published / no dollar amount.
 */
export function lineFootnote(line: ReceiptLine, sources: Record<string, SourceInfo>): Footnote {
  const c = line.cell;
  if (!c || (c.kind !== "money" && c.kind !== "conflict")) return { kind: "none", text: t("footnote.not_published") };
  const m: Money = c.kind === "money" ? c : c.a;
  if (m.basis === "estimate" || m.prov.method === "estimate_peer_range") return { kind: "estimate", text: t("footnote.estimate") };
  const kind = sources[m.prov.source_id]?.source_kind ?? m.prov.source_kind;
  switch (kind) {
    case "hospital_mrf":
    case "clinic_posted":
      return { kind: "fact", text: t("footnote.own_published") };
    case "insurer_tic":
      return { kind: "fact", text: t("footnote.insurer_file") };
    case "medicare_pfs":
    case "medicare_opps":
    case "medicare_asc":
    case "masshealth_fs":
      return { kind: "fact", text: t("footnote.government") };
    case "chia_rp":
      return { kind: "none", text: t("footnote.not_published") };
  }
}

/** A step's figure as a footnote (subtotal rows, the map): own / estimate / typical nearby / none. */
export function stepFootnote(st: StepSummary): Footnote {
  if (st.flat_visit_rate) return { kind: "fact", text: t("flat.adds_zero") };
  switch (st.figure) {
    case "own":
      return { kind: "fact", text: t("footnote.own_figure") };
    case "estimate":
      return { kind: "estimate", text: t("footnote.estimate") };
    case "elsewhere":
    case "elsewhere_estimate":
      return { kind: "nearby", text: t("footnote.nearby") };
    case "none":
      return { kind: "none", text: t("footnote.not_published") };
  }
}

/** The doctor bills separately: a doctor's line at a place that sends two bills (hospital clinic, surgery center). */
export function doctorBillsSeparately(line: ReceiptLine, sq: SiteQuote): boolean {
  return line.component === "professional" && sq.site.billing_type !== "office_visit";
}

/** A flat-visit-rate line (C4b item 5): it keeps its amount, adds $0, and is never summed. */
export function isFlatVisitRate(line: ReceiptLine): boolean {
  return line.price_notes.includes("price.flat_visit_rate");
}

/* ---------------- the map: one item at a time (P3, D-UI-3) ---------------- */

/** What the map prices: one option's headline per site, or one step's price. Never a mix. */
export type MapItem = { kind: "headline"; optionId: string | null } | { kind: "step"; key: string };

export interface MapChoice {
  id: string;
  label: string;
  item: MapItem;
}

/** "option:<id>" / "option:*" for a headline item, the step key otherwise. */
export function mapItemId(item: MapItem): string {
  return item.kind === "headline" ? `option:${item.optionId ?? "*"}` : item.key;
}

/**
 * The headline items of a care-path quote: one per priced option (A, B), or one "whole visit" item when the
 * path has no options. Only when some site has a headline range.
 */
export function headlineMapChoices(quote: QuoteResponse): MapChoice[] {
  if (!quote.care_path || !quote.sites.some((s) => s.headline_range)) return [];
  if (quote.options.length === 0) return [{ id: "option:*", label: t("map.item_headline"), item: { kind: "headline", optionId: null } }];
  return quote.options
    .filter((o) => o.priced && o.sites_with_range > 0)
    .map((o) => ({
      id: `option:${o.id}`,
      label: t("map.item_option", { letter: optionLetter(quote, o.id) ?? "" }),
      item: { kind: "headline", optionId: o.id },
    }));
}

export type HeadlinePin = { kind: "price"; text: string; estimated: boolean; partial: boolean } | { kind: "no_price" };

/**
 * One site's pin for an option's headline. `null` = the site is not in that option (no pin). No headline
 * range = a pin with no price, never a cheap-looking one. from_only reads "from $X".
 */
export function headlinePin(sq: SiteQuote, optionId: string | null): HeadlinePin | null {
  if (optionId != null && sq.option_id !== optionId) return null;
  const hr = sq.headline_range;
  if (!hr) return { kind: "no_price" };
  const text = hr.from_only ? `from ${range(hr.low, hr.low, false)}` : range(hr.low, hr.high, false);
  return { kind: "price", text, estimated: hr.basis === "includes_estimate", partial: hr.basis === "partial" };
}
