/**
 * P3 (Austin, 2026-10-25): "地图view需要显示cpt才显示价格". The map shows a price only for ONE selected
 * service. A care path with no single service selected shows places, not prices; the list keeps the
 * path total.
 *
 * Built on today's quote contract: a quote is "one service" when it is a manual pick (no care path)
 * whose codes are exactly the codes one catalog service sends. The pin then shows that receipt's own
 * engine total; the frontend never adds lines up itself. A per-step price inside a care path needs
 * per-step totals from the engine (C3's new contract, D5) and is not attempted here.
 */
import type { Catalog, CatalogService } from "@/generated/contracts/catalog";
import type { QuoteResponse } from "@/generated/contracts/quote_api";

/** The codes a quote for one catalog service sends: its primary codes, else its first code. */
export function serviceCodes(s: CatalogService): string[] {
  const primary = s.codes.filter((c) => c.role === "primary").map((c) => c.code);
  return primary.length ? primary : s.codes.map((c) => c.code).slice(0, 1);
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && [...a].sort().join(",") === [...b].sort().join(",");

/** The one service this quote prices, or null (a care path, several services, or no catalog). */
export function mapService(quote: QuoteResponse, catalog: Catalog | null): CatalogService | null {
  if (quote.care_path || !catalog || quote.service_codes.length === 0) return null;
  return catalog.services.find((s) => sameSet(serviceCodes(s), quote.service_codes)) ?? null;
}
