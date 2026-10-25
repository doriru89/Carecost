import type { SiteQuote } from "@/generated/contracts/quote_api";
import { miles, type UserLocation } from "./geo";
import { openStatus, type BostonNow, type OpenStatus } from "./hours";

export type SortMode = "price" | "nearest" | "open_today";

export interface SiteView {
  sq: SiteQuote;
  /** I7 rank from the engine (0 = best) */
  rank: number;
  distance: number | null;
  open: OpenStatus;
}

export function siteViews(sites: SiteQuote[], loc: UserLocation | null, now: BostonNow): SiteView[] {
  return sites.map((sq, rank) => ({
    sq,
    rank,
    distance: loc ? miles(loc, sq.site.coords) : null,
    open: openStatus(sq.site.hours, now),
  }));
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
