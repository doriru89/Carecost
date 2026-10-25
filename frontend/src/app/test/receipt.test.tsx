import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Receipt } from "../components/Receipt";
import CareApp from "../pages/CareApp";
import { BCBS, CASH, MASSHEALTH } from "./fixtures";

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
    expect(top).toContain("663.74");
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
    const sq = BCBS.sites.find((s) => s.site.site_id === "tufts_medical_center")!;
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
    const tufts = MASSHEALTH.sites.find((s) => s.site.site_id === "tufts_medical_center")!;
    const ref = tufts.receipt.lines.filter((l) => l.doctor_fee?.rung === 7);
    expect(ref.length).toBe(2);
    expect(ref.every((l) => !l.in_total)).toBe(true);
    render(<TooltipProvider><Receipt quote={MASSHEALTH} sq={tufts} distance={null} open={closed} location={null} /></TooltipProvider>);
    expect(screen.getAllByTestId("reference-tag").length).toBe(2);
    // the total is the two facility lines only: 333 + 1631
    expect(screen.getByTestId("total-top").textContent).toContain("1,964.00");
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
