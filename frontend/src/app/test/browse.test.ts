/**
 * Browse without the AI (Austin 2026-11-09): dropdown options, the place filters and the dropdown value of
 * the quote on screen. Real fixtures (contracts/fixtures: catalog.json, quote_*_shoulder.json, C3).
 */
import { describe, expect, it } from "vitest";
import type { Catalog } from "@/generated/contracts/catalog";
import type { QuoteResponse } from "@/generated/contracts/quote_api";
import catalogJson from "../../../../contracts/fixtures/catalog.json";
import { browseValueOf, filterViews, pinFor, pricedCount, serviceOptions } from "../lib/browse";
import { priceChoices } from "../lib/priceChoices";
import { siteViews } from "../lib/sites";
import { bostonNow } from "../lib/hours";
import { BCBS, MASSHEALTH } from "./fixtures";

const catalog = catalogJson as unknown as Catalog;
const NOON = bostonNow(new Date("2026-11-10T17:00:00Z"));

describe("Browse dropdown", () => {
  it("a typed CPT code narrows the services to the ones carrying it, the code shown first", () => {
    const opts = serviceOptions(catalog, "all", "73030");
    expect(opts.length).toBeGreaterThan(0);
    for (const o of opts) expect(o.label.startsWith("73030")).toBe(true);
  });
  it("a body area keeps only that area's services", () => {
    const skin = serviceOptions(catalog, "skin", "");
    const ids = new Set(catalog.services.filter((s) => (s.areas as string[]).includes("skin")).map((s) => `svc:${s.service_id}`));
    expect(skin.map((o) => o.value).sort()).toEqual([...ids].sort());
  });
  it("a care path quote reads as its path; a manual one as the catalog service with its codes", () => {
    const path = BCBS as unknown as QuoteResponse;
    expect(browseValueOf(path, catalog)).toBe(`path:${path.care_path!.id}`);
    const manual = MASSHEALTH as unknown as QuoteResponse;
    const v = browseValueOf(manual, catalog);
    expect(v === "" || v.startsWith("svc:")).toBe(true);
  });
});

describe("Browse filters", () => {
  const quote = BCBS as unknown as QuoteResponse;
  const views = siteViews(quote.sites, null, NOON);
  const item = priceChoices(quote)[0].item;

  it("P6: with an item, only places with a pin for it; 'priced' keeps only pins with a dollar figure", () => {
    const offered = filterViews(views, item, "all", "offered");
    const priced = filterViews(views, item, "all", "priced");
    for (const v of offered) expect(pinFor(v.sq, item)).not.toBeNull();
    for (const v of priced) expect(pinFor(v.sq, item)?.kind).toBe("price");
    expect(priced.length).toBe(pricedCount(views, item));
    expect(priced.length).toBeLessThanOrEqual(offered.length);
  });
  it("the place type filter keeps one kind of place", () => {
    const kind = views[0].sq.site.kind;
    const kept = filterViews(views, null, kind, "offered");
    expect(kept.length).toBeGreaterThan(0);
    for (const v of kept) expect(v.sq.site.kind).toBe(kind);
  });
});
