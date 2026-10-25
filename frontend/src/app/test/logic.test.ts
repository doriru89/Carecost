import { describe, expect, it } from "vitest";
import type { Hours, ReceiptLine, SourceInfo } from "@/generated/contracts/quote_api";
import { miles, zipToLocation } from "../lib/geo";
import { bostonNow, openStatus } from "../lib/hours";
import {
  freshnessDetail,
  freshnessState,
  highEndProv,
  moneySourceIds,
  noCashDiscount,
  sections,
  siteSourceIds,
  sourceHover,
} from "../lib/receipt";
import { siteViews, sortSites } from "../lib/sites";
import { ALL_QUOTES, BCBS, CASH } from "./fixtures";

describe("receipt sections (D8)", () => {
  it("orders tiers strongest first, keeps every line once, drops empty tiers", () => {
    const lines = BCBS.sites[0].receipt.lines;
    const s = sections(lines);
    expect(s.map((x) => x.tier)).toEqual(["certain", "likely", "possible", "not_in_public_data"]);
    expect(s.flatMap((x) => x.lines).length).toBe(lines.length);
    expect(sections(lines.filter((l) => l.tier === "possible")).map((x) => x.tier)).toEqual(["possible"]);
  });

  it("possible lines are never in the total in the fixtures we render", () => {
    for (const sq of BCBS.sites) for (const l of sq.receipt.lines) if (l.tier === "possible") expect(l.in_total).toBe(false);
  });
});

describe("cash discount check (P1 problem 16)", () => {
  it("flags Mount Auburn's cash price that equals its gross charge, not Tufts' discounted one", () => {
    const ma = CASH.sites.find((s) => s.site.site_id === "mount_auburn_hospital")!;
    const tufts = CASH.sites.find((s) => s.site.site_id === "tufts_medical_center")!;
    const xray = (sq: typeof ma) => sq.receipt.lines.find((l) => l.line_id === "xray_facility")!;
    expect(noCashDiscount(xray(ma), CASH.payment)).toBe(true);
    expect(noCashDiscount(xray(tufts), CASH.payment)).toBe(false);
    expect(noCashDiscount(xray(ma), BCBS.payment)).toBe(false);
  });
});

describe("source chip and freshness (§2.2, D18)", () => {
  const base: SourceInfo = BCBS.sources.mtauburn_mrf;
  it("builds the §2.2 hover sentence from the response's source", () => {
    expect(sourceHover(base, "mtauburn_mrf")).toBe(
      "Hospital's own price file, required by federal law · Mount Auburn Hospital · updated Apr 1, 2026",
    );
  });
  it("never merges the two sides: stale wins over late", () => {
    expect(freshnessState(base)).toBe("current");
    expect(freshnessState({ ...base, freshness: { ...base.freshness, late_to_refresh: true } })).toBe("late");
    expect(freshnessState({ ...base, freshness: { ...base.freshness, stale_on_our_side: true } })).toBe("stale");
  });
  it("D18: both flags true -> stale on our side, never the publisher's lateness (state and detail text)", () => {
    const both: SourceInfo = {
      ...base,
      freshness: { ...base.freshness, late_to_refresh: true, stale_on_our_side: true, our_refresh_due: "2026-11-24" },
    };
    expect(freshnessState(both)).toBe("stale");
    const detail = freshnessDetail(both);
    expect(detail).toMatch(/^We last downloaded it/);
    expect(detail).not.toMatch(/publisher's file/);
  });
  it("lists exactly sources the response carries for each site, both ends of every range included", () => {
    for (const q of ALL_QUOTES) for (const sq of q.sites) for (const id of siteSourceIds(sq)) expect(q.sources[id]).toBeDefined();
    const withHigh = BCBS.sites.flatMap((sq) => sq.receipt.lines).flatMap((l) => (l.cell?.kind === "money" && l.cell.prov_high ? [l.cell] : []));
    expect(withHigh.length).toBeGreaterThan(0);
    for (const m of withHigh) expect(moneySourceIds(m)).toContain(m.prov_high!.source_id);
  });
  it("a null price_source_id adds no source", () => {
    const sq = CASH.sites.find((s) => s.site.price_source_id == null)!;
    expect(siteSourceIds(sq)).not.toContain(null);
  });
  it("a point needs one chip; a range whose ends come from different rows needs two", () => {
    const m = BCBS.sites.flatMap((sq) => sq.receipt.lines).flatMap((l) => (l.cell?.kind === "money" ? [l.cell] : []));
    const point = m.find((x) => x.low === x.high)!;
    expect(highEndProv(point)).toBeNull();
    const ranged = m.find((x) => x.low < x.high && x.prov_high)!;
    expect(highEndProv(ranged)).toEqual(ranged.prov_high);
  });
});

describe("hours in Boston time", () => {
  const hours: Hours = {
    source: "manual",
    source_url: null,
    checked_at: "2026-10-24",
    weekly: [{ days: ["mon", "tue", "wed", "thu", "fri"], opens: "08:00", closes: "20:00" }],
    may_close_early: false,
  };
  it("open now / opens later / closed with next day", () => {
    expect(openStatus(hours, { day: "mon", minutes: 9 * 60 }).text).toBe("Open now until 8 PM");
    expect(openStatus(hours, { day: "mon", minutes: 7 * 60 }).text).toBe("Opens today at 8 AM");
    const sat = openStatus(hours, { day: "sat", minutes: 600 });
    expect(sat.openToday).toBe(false);
    expect(sat.text).toBe("Closed today · opens Mon 8 AM");
    expect(openStatus(hours, { day: "mon", minutes: 21 * 60 }).text).toBe("Closed now · opens tomorrow 8 AM");
    expect(openStatus(null, { day: "mon", minutes: 0 }).known).toBe(false);
  });
  it("reads the wall clock in America/New_York, not the machine zone", () => {
    // 2026-10-24 16:30 UTC = 12:30 EDT, a Saturday
    expect(bostonNow(new Date("2026-10-24T16:30:00Z"))).toEqual({ day: "sat", minutes: 12 * 60 + 30 });
  });
});

describe("distance in the browser (§4.3)", () => {
  it("looks up a typed MA ZIP and computes miles", () => {
    const allston = zipToLocation("02135")!;
    expect(allston.kind).toBe("zip");
    const afc = BCBS.sites.find((s) => s.site.site_id === "afc_watertown")!.site.coords;
    const d = miles(allston, afc);
    expect(d).toBeGreaterThan(0.3);
    expect(d).toBeLessThan(3);
    expect(zipToLocation("10001")).toBeNull(); // not MA
    expect(zipToLocation("abc")).toBeNull();
  });
});

describe("site sorting (I7 respected)", () => {
  const now = { day: "sat" as const, minutes: 600 };
  it("price keeps the engine's I7 order; nearest uses distance; open-today puts open sites first", () => {
    const loc = zipToLocation("02472")!; // Watertown
    const views = siteViews(BCBS.sites, loc, now);
    expect(sortSites(views, "price").map((v) => v.sq.site.site_id)).toEqual(BCBS.sites.map((s) => s.site.site_id));
    expect(sortSites(views, "nearest")[0].sq.site.site_id).toBe("afc_watertown");
    const open = sortSites(views, "open_today");
    expect(open[0].open.openToday).toBe(true);
  });
  it("nearest without a location falls back to I7 order", () => {
    const views = siteViews(BCBS.sites, null, now);
    // data change: the fixture now has 6 sites (was 3)
    expect(BCBS.sites.length).toBe(6);
    expect(sortSites(views, "nearest").map((v) => v.rank)).toEqual([0, 1, 2, 3, 4, 5]);
  });
});

export type { ReceiptLine };
