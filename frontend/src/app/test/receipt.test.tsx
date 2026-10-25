import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Receipt } from "../components/Receipt";
import CareApp from "../pages/CareApp";
import { BCBS, CASH } from "./fixtures";

const closed = { known: true, openNow: false, openToday: false, text: "Closed" };

describe("gradient receipt (D8, §4.2)", () => {
  it("shows the total at the top and repeats it at the bottom, from totals.likely", () => {
    const sq = BCBS.sites[0];
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const top = screen.getByTestId("total-top").textContent;
    expect(top).toBe(screen.getByTestId("total-bottom").textContent);
    expect(top).toContain("860.32");
    expect(top).toContain("958.58");
    expect(top?.startsWith("≥")).toBe(!sq.receipt.totals.complete);
  });

  it("every gap row says what to ask; AI lines sit in a dashed box; possible extras are labelled out of total", () => {
    const sq = BCBS.sites[0];
    render(<TooltipProvider><Receipt quote={BCBS} sq={sq} distance={null} open={closed} location={null} /></TooltipProvider>);
    const gaps = within(screen.getByTestId("section-not_in_public_data")).getAllByTestId("receipt-line");
    for (const g of gaps) expect(g.textContent).toMatch(/Ask:/);
    expect(screen.getAllByTestId("ai-suggested").length).toBe(sq.receipt.lines.filter((l) => l.ai_suggested).length);
    expect(screen.getByTestId("section-possible").textContent).toMatch(/not in the total/);
    // one source chip per Money at least
    expect(screen.getAllByTestId("source-chip").length).toBeGreaterThan(10);
    expect(screen.getByTestId("you-pay").textContent).toMatch(/MyBlue/);
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
