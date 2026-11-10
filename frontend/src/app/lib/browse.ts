/**
 * Browse without the AI (Austin 2026-11-09): a service or CPT code from a dropdown, filters on the places,
 * and the map with prices on it from the first screen. Pure functions; the pins follow the same rules as
 * the map everywhere else (P3: one item at a time; P6: a pin only where the place says it offers it).
 */
import type { Catalog, CatalogService } from "@/generated/contracts/catalog";
import type { QuoteResponse, SiteQuote, SiteSummary } from "@/generated/contracts/quote_api";
import { headlinePin, type HeadlinePin, type MapItem } from "./headline";
import { serviceCodes } from "./mapPrice";
import type { SiteView } from "./sites";
import { stepOf, stepPin, type StepPin } from "./steps";

/** The service the map prices before the person picks one: a new-patient visit, priced at the most places. */
export const DEFAULT_BROWSE_SERVICE = "svc_99203";

export type KindFilter = "all" | SiteSummary["kind"];
export type ShowFilter = "offered" | "priced";

/** A dropdown value: one service ("svc:<id>") or a whole care path ("path:<id>"). */
export type BrowseValue = `svc:${string}` | `path:${string}`;

/** What one place's pin says for the chosen item; null = no pin (the place does not say it offers it). */
export function pinFor(sq: SiteQuote, item: MapItem | null): StepPin | HeadlinePin | null {
  if (!item) return null;
  return item.kind === "step" ? stepPin(stepOf(sq, item.key)) : headlinePin(sq, item.optionId);
}

/**
 * The places the map and list show. With an item: only places with a pin for it (P6), and with "priced"
 * only the ones whose pin carries a price. The place-type filter applies either way.
 */
export function filterViews(views: SiteView[], item: MapItem | null, kind: KindFilter, show: ShowFilter): SiteView[] {
  return views.filter((v) => {
    if (kind !== "all" && v.sq.site.kind !== kind) return false;
    if (!item) return true;
    const pin = pinFor(v.sq, item);
    return pin != null && (show === "offered" || pin.kind === "price");
  });
}

export function pricedCount(views: SiteView[], item: MapItem | null): number {
  return item ? views.filter((v) => pinFor(v.sq, item)?.kind === "price").length : 0;
}

/** The dropdown value of the quote on screen: its care path, or the catalog service with its codes. */
export function browseValueOf(quote: QuoteResponse | null, catalog: Catalog | null): BrowseValue | "" {
  if (!quote) return "";
  if (quote.care_path) return `path:${quote.care_path.id}`;
  const codes = [...quote.service_codes].sort().join(",");
  const svc = catalog?.services.find((s) => [...serviceCodes(s)].sort().join(",") === codes);
  return svc ? `svc:${svc.service_id}` : "";
}

const KIND_GROUP: Record<CatalogService["kind"], "visit" | "imaging" | "procedure" | "lab" | "other"> = {
  referral: "visit",
  visit: "visit",
  imaging: "imaging",
  procedure: "procedure",
  lab: "lab",
  anesthesia: "other",
  therapy: "other",
  medication: "other",
  supply: "other",
};
export const SERVICE_GROUPS = ["visit", "imaging", "procedure", "lab", "other"] as const;

export interface ServiceOption {
  value: BrowseValue;
  /** "73030 · Quick picture of the shoulder bones": the code first, so a person who has one finds it */
  label: string;
  group: (typeof SERVICE_GROUPS)[number];
}

/** The services of one body area (catalog `areas`), filtered by a typed code or name, grouped by kind. */
export function serviceOptions(catalog: Catalog | null, area: string, q: string): ServiceOption[] {
  if (!catalog) return [];
  const s = q.trim().toLowerCase();
  return catalog.services
    .filter((x) => area === "all" || (x.areas as string[]).includes(area))
    .filter(
      (x) =>
        !s ||
        x.plain_name.toLowerCase().includes(s) ||
        x.technical_name.toLowerCase().includes(s) ||
        x.codes.some((c) => c.code.toLowerCase().includes(s)),
    )
    .map((x) => ({
      value: `svc:${x.service_id}` as const,
      label: `${serviceCodes(x).join(" / ")} · ${x.plain_name}`,
      group: KIND_GROUP[x.kind],
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Care path area (catalog path `area`, e.g. msk_shoulder) -> the service area it belongs to. */
export function pathServiceArea(pathArea: string): string {
  if (pathArea.startsWith("msk_")) return "ortho";
  if (pathArea.startsWith("gi_")) return "gi";
  return pathArea;
}
