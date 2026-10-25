import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Receipt } from "../components/Receipt";
import CareApp from "../pages/CareApp";
import { ScopeNote, SiteCard } from "../components/SiteList";
import { BCBS, CASH, MASSHEALTH, MEDICARE } from "./fixtures";

const closed = { known: true, openNow: false, openToday: false, text: "Closed" };

describe("gradient receipt (D8, §4.2)", () => {
  // Data change (C's engine, 68326f8): sites[0] is now AFC Watertown (a point total, ≥ $292.00 with an
  // estimate); the range-total case moved to Mount Auburn, whose total in quote_bcbs_hmo_shoulder.json
  // is now totals.likely 663.74-723.38 (was 860.32-958.58 on the P1 fixture).
  const MTA = BCBS.sites.find((s) => s.site.site_id === "mount_auburn_hospital")!;

  it("shows the total at the top and repeats it at the bottom, from totals.likely", () => {
    const sq = MTA;
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const top = screen.getByTestId("total-top").textContent;
    expect(top).toBe(screen.getByTestId("total-bottom").textContent);
    // Data change (C3, ee409cf): Mount Auburn's totals.likely is now 669.03-723.38 (was 663.74-723.38)
    expect(top).toContain("669.03");
    expect(top).toContain("723.38");
    expect(top?.startsWith("≥")).toBe(!sq.receipt.totals.complete);
  });

  it("every gap row says what to ask; AI lines sit in a dashed box; possible extras are labelled out of total", () => {
    const sq = MTA;
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const gaps = within(screen.getByTestId("section-not_in_public_data")).getAllByTestId("receipt-line");
    for (const g of gaps) expect(g.textContent).toMatch(/Ask:/);
    expect(screen.getAllByTestId("ai-suggested").length).toBe(sq.receipt.lines.filter((l) => l.ai_suggested).length);
    expect(screen.getByTestId("section-possible").textContent).toMatch(/not in the total/);
    // one source chip per Money at least
    expect(screen.getAllByTestId("source-chip").length).toBeGreaterThan(10);
    expect(screen.getByTestId("you-pay").textContent).toMatch(/MyBlue/);
  });

  it("a range cites both ends: a low chip and a high chip from prov / prov_high (P1 problem 2)", () => {
    // Data change (C2): no Tufts in the 12 nearest Harvard Square; Mount Auburn has 3 ranged lines
    // (visit_doctor, xray_reading, steroid_injection_doctor).
    const sq = MTA;
    const ranged = sq.receipt.lines.filter((l) => l.cell?.kind === "money" && l.cell.prov_high && l.cell.low < l.cell.high);
    expect(ranged.length).toBeGreaterThan(0);
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const high = screen.getAllByTestId("source-chip").filter((c) => c.getAttribute("data-end") === "high");
    expect(high.length).toBeGreaterThanOrEqual(ranged.length);
    expect(high[0].textContent).toMatch(/^High: /);
  });

  it("a referral happens at your primary care office, not this site (ReceiptLine.at, P1 problem 15)", () => {
    const sq = BCBS.sites[0];
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const n = sq.receipt.lines.filter((l) => l.at === "your_primary_care").length;
    expect(n).toBeGreaterThan(0);
    expect(screen.getAllByTestId("at-primary-care").length).toBe(n);
  });

  it("D33 lines sit under a receipt reached from a care path, and not under a manual pick", () => {
    expect(BCBS.copy_keys).toEqual(["copy.not_a_diagnosis", "copy.when_to_see_a_doctor"]);
    const { unmount } = render(<TooltipProvider><Receipt quote={BCBS} sq={BCBS.sites[0]} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getByTestId("d33-copy.not_a_diagnosis").textContent).toMatch(/not a diagnosis/);
    expect(screen.getByTestId("d33-copy.when_to_see_a_doctor")).toBeTruthy();
    unmount();
    expect(MASSHEALTH.copy_keys).toEqual([]);
    render(<TooltipProvider><Receipt quote={MASSHEALTH} sq={MASSHEALTH.sites[0]} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.queryByTestId("d33-lines")).toBeNull();
  });

  it("rung 6 is tagged as an estimate; rung 7 is tagged reference only and left out of the total", () => {
    const afc = BCBS.sites[0];
    const est = afc.receipt.lines.filter((l) => l.cell?.kind === "money" && l.cell.basis === "estimate").length;
    expect(est).toBeGreaterThan(0);
    const { unmount } = render(<TooltipProvider><Receipt quote={BCBS} sq={afc} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getAllByTestId("estimate-tag").length).toBe(est);
    expect(screen.getByTestId("total-top").parentElement?.textContent).toMatch(/Includes an estimate/);
    unmount();
    // Data change (C3, ee409cf): at Cambridge Health Alliance's hospital only visit_doctor ($75.54) is
    // rung 7 now (steroid_injection_doctor became a rung-6 peer estimate), and visit_facility ($30.92)
    // is set aside as unusual (P8), so it left the total too.
    const cha = BCBS.sites.find((s) => s.site.site_id === "cha_cambridge_hospital")!;
    const ref = cha.receipt.lines.filter((l) => l.doctor_fee?.rung === 7);
    expect(ref.length).toBe(1);
    expect(ref.every((l) => !l.in_total)).toBe(true);
    render(<TooltipProvider><Receipt quote={BCBS} sq={cha} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getAllByTestId("reference-tag").length).toBe(1);
    // P2 (D5): a BCBS person never sees the Medicare figure as the price: it is folded away, labelled
    const hidden = screen.getAllByTestId("hidden-price").filter((h) => h.getAttribute("data-hidden") === "medicare_reference");
    expect(hidden.length).toBe(1);
    expect(hidden[0].textContent).toMatch(/^No price for your plan/);
    expect(hidden[0].querySelector("details")?.open).toBe(false);
    // the total is the three in-total lines only: 71.24 + (12.04-17.33) + 294.35, no rung-7 amount
    // (was 408.55-413.84 with the visit facility fee)
    const top = screen.getByTestId("total-top").textContent;
    expect(top).toContain("377.63");
    expect(top).toContain("382.92");
  });

  it("a site whose own price source we do not read says so (price_source_id null, P1 problem 9)", () => {
    const sq = CASH.sites.find((s) => s.site.price_source_id == null)!;
    render(<TooltipProvider><Receipt quote={CASH} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getByTestId("price-source-not-read")).toBeTruthy();
  });

  it("cash at Mount Auburn says no cash discount is listed", () => {
    const sq = CASH.sites.find((s) => s.site.site_id === "mount_auburn_hospital")!;
    render(<TooltipProvider><Receipt quote={CASH} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getAllByTestId("no-cash-discount").length).toBeGreaterThan(0);
  });
});

describe("C2 fields on the receipt and the site card", () => {
  it("price_notes: Medicare at Brigham says the facility fee is the national rate, not adjusted for Boston", () => {
    const sq = MEDICARE.sites.find((s) => s.site.site_id === "brigham_and_womens_hospital")!;
    const noted = sq.receipt.lines.filter((l) => l.price_notes.includes("price.national_unadjusted"));
    // visit_facility (G0463), xray_facility, tendon_scan_mri_facility, mr_arthrogram_facility
    expect(noted.map((l) => l.line_id)).toEqual(["visit_facility", "xray_facility", "tendon_scan_mri_facility", "mr_arthrogram_facility"]);
    expect(noted[0].codes).toContain("G0463");
    render(<TooltipProvider><Receipt quote={MEDICARE} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const notes = screen.getAllByTestId("price-note");
    expect(notes.length).toBe(4);
    for (const n of notes) expect(n.textContent).toBe("Medicare's national rate, not adjusted for Boston");
  });

  it("availability unknown has its own label; offered lines carry none", () => {
    // Data change (C3, ee409cf): the Medicare fixture has no availability-unknown line any more; AFC
    // Cambridge under BCBS HMO has 9, all insurer_lists_rate (was MEDICARE.sites[0] with 5).
    expect(MEDICARE.sites.flatMap((s) => s.receipt.lines).filter((l) => l.availability === "unknown").length).toBe(0);
    const sq = BCBS.sites.find((s) => s.site.site_id === "afc_urgent_care_cambridge_cambridge")!;
    const unknown = sq.receipt.lines.filter((l) => l.availability === "unknown").length;
    expect(unknown).toBe(9);
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const labels = screen.getAllByTestId("availability-unknown");
    expect(labels.length).toBe(unknown);
    expect(labels[0].textContent).toBe("Not known whether this place offers it");
    // every line that shows the label is an unknown one
    for (const el of labels) {
      const row = el.closest("[data-testid=receipt-line]")!;
      expect(within(row as HTMLElement).queryByTestId("availability-unknown")).toBe(el);
    }
  });

  it("children_only shows a badge; data_notices show on the card and the receipt", () => {
    // No site in the committed fixtures is children-only or carries a notice (BIDMC's notice is not
    // among the 12 nearest Harvard Square), so this takes a fixture site and sets the two fields.
    const base = BCBS.sites[0];
    const notice = {
      id: "bidmc_content_changed_date_unchanged",
      kind: "content_changed_date_unchanged",
      source_id: "bidmc_mrf",
      observed: "2026-10-24",
      detail: "BIDMC's price file changed content between our 2026-05 copy and the 2026-10-24 download.",
      effect: null,
    };
    const sq = { ...base, site: { ...base.site, children_only: true, data_notices: [notice] } };
    const { unmount } = render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getByTestId("children-only").textContent).toBe("Children only");
    expect(screen.getByTestId("data-notice").textContent).toMatch(/changed, but the date on it did not/);
    expect(screen.getByTestId("data-notice").textContent).toContain("2026-10-24 download");
    unmount();
    const view = { sq, rank: 0, distance: null, open: closed };
    const { unmount: u2 } = render(<SiteCard v={view} onOpen={() => {}} />);
    expect(screen.getByTestId("children-only")).toBeTruthy();
    expect(screen.getByTestId("data-notice").textContent).toMatch(/changed, but the date on it did not/);
    u2();
    render(<SiteCard v={{ ...view, sq: base }} onOpen={() => {}} />);
    expect(screen.queryByTestId("children-only")).toBeNull();
    expect(screen.queryByTestId("data-notice")).toBeNull();
  });
});

describe("which sites the list holds (C2 near / max_sites)", () => {
  // Rule change (P7, Austin 2026-10-25; C3 ordering kind_then_distance): with no location the list is
  // every admitted place grouped by kind, by distance from Boston City Hall. "Best value overall" is
  // never said anywhere (was: "The 12 best-value places overall").
  it("says nearest only when a location was sent, all places by kind otherwise, never best value", () => {
    const { unmount } = render(<ScopeNote scope={{ kind: "all" }} count={133} />);
    expect(screen.getByTestId("site-scope").textContent).toMatch(/^All 133 places that do this, grouped by kind of place, nearest to Boston City Hall first/);
    expect(screen.getByTestId("site-scope").textContent).not.toMatch(/best/i);
    expect(screen.getByTestId("site-scope").textContent).not.toMatch(/^The 133 places nearest/);
    unmount();
    render(<ScopeNote scope={{ kind: "near", label: "ZIP 02138" }} count={12} />);
    expect(screen.getByTestId("site-scope").textContent).toBe("The 12 places nearest ZIP 02138");
  });
});

describe("red flag stops everything (§4.1)", () => {
  it("a crisis message shows the 988 page and no prices", async () => {
    render(
      <MemoryRouter>
        <CareApp />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByTestId("payment-select"), { target: { value: "cash" } });
    fireEvent.change(screen.getByTestId("email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByTestId("start-chat"), { target: { value: "I want to kill myself" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByTestId("crisis-page")).toBeTruthy());
    expect(screen.queryByTestId("receipt")).toBeNull();
    expect(screen.queryByText(/\$\d/)).toBeNull();
    expect(screen.getByRole("link", { name: /Call 988/ }).getAttribute("href")).toBe("tel:988");
  });
});
