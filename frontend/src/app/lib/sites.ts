import type { SiteQuote, SiteSummary } from "@/generated/contracts/quote_api";
import { miles, type UserLocation } from "./geo";
import { openStatus, type BostonNow, type OpenStatus } from "./hours";

export type SortMode = "price" | "nearest" | "open_today";

/**
 * Which sites the response holds (C2, C3). `near`: the max_sites closest to the person's point.
 * `all`: no location was sent, so the server returned every admitted site grouped by kind and ordered by
 * distance from Boston City Hall (P7); the list never calls them "nearest" or "best value".
 * `fixture`: mock mode's committed test data.
 */
export type SiteScope = { kind: "near"; label: string } | { kind: "all" } | { kind: "fixture" };

export interface SiteView {
  sq: SiteQuote;
  /** I7 rank from the engine (0 = best) */
  rank: number;
  distance: number | null;
  /** P7: miles from Boston City Hall (the server's distance_km) when the list has no location */
  cityHallMiles?: number | null;
  open: OpenStatus;
}

const KM_PER_MILE = 1.609344;

export function siteViews(sites: SiteQuote[], loc: UserLocation | null, now: BostonNow): SiteView[] {
  return sites.map((sq, rank) => ({
    sq,
    rank,
    distance: loc ? miles(loc, sq.site.coords) : null,
    cityHallMiles: !loc && sq.distance_km != null ? sq.distance_km / KM_PER_MILE : null,
    open: openStatus(sq.site.hours, now),
  }));
}

export interface KindGroup {
  kind: SiteSummary["kind"];
  views: SiteView[];
}

/**
 * P7: a no-location list (ordering kind_then_distance) is shown in groups of one kind each, in the
 * server's order (urgent care, offices, hospital clinics, surgery centers; nearest City Hall first
 * inside). Consecutive runs, so a sort inside the groups keeps every group together.
 */
export function kindGroups(views: SiteView[]): KindGroup[] {
  const out: KindGroup[] = [];
  for (const v of views) {
    const last = out[out.length - 1];
    if (last && last.kind === v.sq.site.kind) last.views.push(v);
    else out.push({ kind: v.sq.site.kind, views: [v] });
  }
  return out;
}

/** Sort inside each kind group, keeping the groups in the server's order (P7). */
export function sortWithinKinds(views: SiteView[], mode: SortMode): SiteView[] {
  return sortWithinGroups(views, mode, (v) => v.sq.site.kind);
}

/** C4b: sort inside each entry option (option_then_*), keeping the options in the server's order. */
export function sortWithinOptions(views: SiteView[], mode: SortMode): SiteView[] {
  return sortWithinGroups(views, mode, (v) => v.sq.option_id ?? "");
}

function sortWithinGroups(views: SiteView[], mode: SortMode, key: (v: SiteView) => string): SiteView[] {
  const order = new Map<string, number>();
  for (const v of views) if (!order.has(key(v))) order.set(key(v), order.size);
  return sortSites(views, mode).sort((a, b) => order.get(key(a))! - order.get(key(b))!);
}

export interface OptionRun {
  optionId: string | null;
  views: SiteView[];
}

/** Consecutive runs of one entry option (the list's group headers for option_then_* orderings). */
export function optionRuns(views: SiteView[]): OptionRun[] {
  const out: OptionRun[] = [];
  for (const v of views) {
    const last = out[out.length - 1];
    if (last && last.optionId === v.sq.option_id) last.views.push(v);
    else out.push({ optionId: v.sq.option_id, views: [v] });
  }
  return out;
}

/**
 * "Price" keeps the engine's I7 order (completeness band, then total), so a site that is cheap
 * only because a price is missing never jumps ahead. "Nearest" needs a location; without one it
 * falls back to the I7 order. "Open today" puts sites open today first, I7 order inside.
 */
export function sortSites(views: SiteView[], mode: SortMode): SiteView[] {
  const byRank = (a: SiteView, b: SiteView) => a.rank - b.rank;
  const out = [...views];
  if (mode === "price") return out.sort(byRank);
  if (mode === "nearest")
    return out.sort((a, b) =>
      a.distance == null || b.distance == null ? byRank(a, b) : a.distance - b.distance || byRank(a, b),
    );
  return out.sort((a, b) => Number(b.open.openToday) - Number(a.open.openToday) || byRank(a, b));
}
