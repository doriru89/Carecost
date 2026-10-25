/**
 * Round C7 · D6: the frontend on C4b's contract. Real responses from the c4b_a7 pack (test/data/d6_*.json,
 * trimmed: other_payers dropped, receipts kept on a few sites) and the committed shoulder fixtures.
 * Synthetic cases say so.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CONTRACT_COPY, reviewKeys, t } from "@/contracts/copy";
import type { QuoteResponse, ReceiptLine, SiteQuote } from "@/generated/contracts/quote_api";
import { ErReferenceView } from "../components/Headline";
import { Overview } from "../components/Overview";
import { Receipt } from "../components/Receipt";
import { SiteList } from "../components/SiteList";
import { headlineMapChoices, headlinePin, includesText, mayAlsoGroups, optionGroups } from "../lib/headline";
import { quoteAnswers } from "../lib/payments";
import { availabilityKey } from "../lib/receipt";
import { optionRuns, siteViews } from "../lib/sites";
import { elsewhereSteps } from "../lib/steps";
import zhouJson from "./data/d6_zhou_cash_stomach.json";
import lingJson from "./data/d6_ling_bcbs_rash.json";
import colonJson from "./data/d6_bcbs_colon.json";
import { BCBS, CASH } from "./fixtures";

const ZHOU = zhouJson as unknown as QuoteResponse; // self-pay, stomach ache, near ZIP 02139
const LING = lingJson as unknown as QuoteResponse; // BCBS HMO + Q14 hmo_referral_required, rash, near 02138
const COLON = colonJson as unknown as QuoteResponse; // BCBS HMO, colon screening, near 02139
const now = { day: "sat" as const, minutes: 600 };
const closed = { known: true, openNow: false, openToday: false, text: "Closed" };
const site = (q: QuoteResponse, id: string) => q.sites.find((s) => s.site.site_id === id)!;
const AFC_INMAN = "afc_urgent_care_cambridge_inman_square_cambridge";
const CHA_SOMERVILLE = "cha_somerville_urgent_care_center_somerville";

function overview(q: QuoteResponse, onOrderBy?: (o: "distance" | "price") => void, onOpen = vi.fn()) {
  return render(
    <Overview quote={q} views={siteViews(q.sites, null, now)} scope={{ kind: "near", label: "ZIP 02139" }} orderBy="distance" onOrderBy={onOrderBy} onOpen={onOpen} onSeeAll={() => {}} />,
  );
}

function receipt(q: QuoteResponse, sq: SiteQuote) {
  return render(
    <TooltipProvider>
      <Receipt quote={q} sq={sq} distance={null} open={closed} location={null} />
    </TooltipProvider>,
  );
}

describe("item 1 · the C4b contract compiles and every new key has copy, marked for review", () => {
  it("the new copy keys exist and are review: true", () => {
    const keys = [
      "headline.doctor_bills_separately",
      "price.flat_visit_rate",
      "price.several_rates_same_doctors",
      "total.excluded.flat_visit_rate",
      "notice.hmo_referral_for_specialist",
      "er.visit_alone_costs_more",
      "receipt.availability.price_file_lists_rate",
      "cheapest.complete",
      "cheapest.includes_estimate",
      "cheapest.partial",
    ] as const;
    for (const k of keys) expect(CONTRACT_COPY[k]).toMatchObject({ review: true });
    expect(reviewKeys()).toEqual(expect.arrayContaining([...keys]));
    expect(t("cheapest.complete")).toBe("Cheapest, from their own published prices");
    expect(t("cheapest.includes_estimate")).toBe("Cheapest; part of this is an estimate");
    expect(t("cheapest.partial")).toBe("Only partial prices found here");
  });

  it("price_file_lists_rate has its own wording; insurer wording only for insurance", () => {
    expect(availabilityKey("price_file_lists_rate", CASH.payment)).toBe("receipt.availability.price_file_lists_rate");
    expect(t("receipt.availability.price_file_lists_rate")).not.toMatch(/insurer/i);
    expect(availabilityKey("insurer_lists_rate", BCBS.payment)).toBe("receipt.availability.insurer_lists_rate");
  });
});

describe("小周 · self-pay, weeknight, stomach ache, near 02139 (real pack)", () => {
  it("option A's cheapest is AFC, includes an estimate, $193–$207; CHA reads 'from $149, the doctor bills separately' and is not the cheapest", () => {
    const [a, b] = ZHOU.options;
    expect(a).toMatchObject({ id: "a", cheapest_site_id: AFC_INMAN, cheapest_basis: "includes_estimate" });
    overview(ZHOU);
    const blocks = screen.getAllByTestId("option-block");
    expect(blocks.map((x) => x.getAttribute("data-option"))).toEqual(["a", "b"]);
    const cheapest = within(blocks[0]).getByTestId("pick-cheapest");
    expect(cheapest.getAttribute("data-site-id")).toBe(AFC_INMAN);
    expect(within(cheapest).getByTestId("cheapest-badge").textContent).toBe("Cheapest place for this");
    expect(within(cheapest).getByTestId("cheapest-basis").textContent).toBe("Cheapest; part of this is an estimate");
    expect(within(cheapest).getByTestId("headline-figure").textContent).toBe("$193–$207");
    expect(within(cheapest).getByTestId("headline-includes").textContent).toBe("Includes the visit, plus: urine test");
    expect(within(cheapest).getByTestId("headline-basis").textContent).toBe("Includes an estimate");
    // 2-3 alternates, never the cheapest again
    const alts = within(blocks[0]).getAllByTestId("pick-alternate");
    expect(alts.length).toBe(3);
    expect(alts.map((x) => x.getAttribute("data-site-id"))).not.toContain(AFC_INMAN);
    // CHA Somerville: from_only, partial; never marked cheapest
    const cha = site(ZHOU, CHA_SOMERVILLE);
    expect(cha.headline_range).toMatchObject({ low: 149, from_only: true, basis: "partial" });
    const chaGroup = optionGroups(ZHOU)[0];
    expect(chaGroup.cheapest?.site.site_id).not.toBe(CHA_SOMERVILLE);
    // option B (GI doctor) is listed, unpriced, with its reason: never hidden
    expect(b.priced).toBe(false);
    const un = within(blocks[1]).getByTestId("option-unpriced");
    expect(un.textContent).toContain("We don't have prices for this yet.");
    expect(un.textContent).toContain(b.missing_reason!);
    expect(within(blocks[1]).queryByTestId("pick-cheapest")).toBeNull();
  });

  it("CHA's card and receipt say 'from $149 — the doctor bills separately', never a full price", () => {
    const cha = site(ZHOU, CHA_SOMERVILLE);
    receipt(ZHOU, cha);
    const head = screen.getByTestId("receipt-headline");
    expect(within(head).getByTestId("headline-figure").textContent).toBe("from $149 — the doctor bills separately");
    expect(within(head).getByTestId("headline-range").getAttribute("data-from-only")).toBe("true");
    // the doctor's line is marked as a separate bill, in plain words (no "professional" on the surface)
    expect(screen.getAllByTestId("doctor-bills-separately").length).toBeGreaterThan(0);
    const surface = screen.getByTestId("receipt").cloneNode(true) as HTMLElement;
    surface.querySelectorAll("details").forEach((d) => d.remove());
    expect(surface.textContent).not.toMatch(/\b(facility|professional)\b/i);
  });

  it("AFC's urine test is done there with no own price: its typical price nearby, never AFC's own", () => {
    const afc = site(ZHOU, AFC_INMAN);
    const ut = afc.steps.find((s) => s.key === "urine_test")!;
    expect(ut).toMatchObject({ figure: "elsewhere_estimate", availability: "offered" });
    expect(elsewhereSteps(afc).map((s) => s.key)).toContain("urine_test");
    receipt(ZHOU, afc);
    const step = screen.getAllByTestId("elsewhere-step").find((s) => s.getAttribute("data-step") === "urine_test")!;
    expect(within(step).getByTestId("elsewhere-about").textContent).toMatch(/^About \$[\d.,]+–\$[\d.,]+ \(typical price nearby\)$/);
    expect(within(step).getByTestId("elsewhere-why").textContent).toBe(t("receipt.elsewhere_estimate_why"));
    // the breakdown shows the three subtotals; with_likely is the headline
    const subs = within(screen.getByTestId("range-build")).getAllByTestId("subtotal-amount").map((e) => e.textContent);
    expect(subs).toEqual(["$179", "$193–$207", "$343–$357"]);
    // the possible imaging (no price) is said, not counted
    expect(within(screen.getByTestId("range-build")).getAllByTestId("subtotal-not-priced").map((e) => e.textContent)).toEqual([
      "No price found, not counted: Sound-wave picture of the belly, Detailed scan of the belly",
    ]);
    expect(screen.getByTestId("call-questions").textContent).toContain(t("call.q_self_pay"));
  });

  it("the belly ultrasound and CT are alternatives: 'one of these'", () => {
    const hr = site(ZHOU, AFC_INMAN).headline_range!;
    const groups = mayAlsoGroups(hr.may_also_order);
    const imaging = groups.find((g) => g.group === "belly_imaging")!;
    expect(imaging.items.map((m) => m.step_key)).toEqual(["belly_ultrasound", "belly_ct"]);
    receipt(ZHOU, site(ZHOU, AFC_INMAN));
    const g = within(screen.getByTestId("receipt-headline")).getByTestId("may-also-group");
    expect(g.textContent).toContain(t("may_also.one_of"));
  });

  it("the ER reference for self-pay: collapsed, the hospital part only, 3 hospitals inside", () => {
    const er = ZHOU.er_reference!;
    expect(er).toMatchObject({ status: "priced", low: 1193, high: 3000, includes_doctor: false });
    render(<ErReferenceView er={er} />);
    const box = screen.getByTestId("er-reference");
    expect(box.tagName).toBe("DETAILS");
    expect((box as HTMLDetailsElement).open).toBe(false);
    expect(within(box).getByTestId("er-range").textContent).toBe("At the ER the visit alone usually costs $1,193–$3,000, before any tests.");
    expect(within(box).getByTestId("er-hospital-only")).toBeTruthy();
    expect(within(box).getAllByTestId("er-hospital").length).toBe(3);
  });
});

describe("阿玲 · BCBS HMO, Saturday, rash, near 02138 (real pack)", () => {
  it("option A urgent care and option B skin doctor, each with its cheapest marked; the referral notice only at B", () => {
    expect(LING.notices).toContain("hmo_referral_for_specialist");
    overview(LING);
    const [a, b] = screen.getAllByTestId("option-block");
    expect(within(a).getByTestId("option-label").textContent).toBe("Option A: Urgent care or primary care");
    expect(within(b).getByTestId("option-label").textContent).toBe("Option B: Skin doctor (dermatologist)");
    expect(within(a).getByTestId("pick-cheapest").getAttribute("data-site-id")).toBe("afc_urgent_care_cambridge_cambridge");
    expect(within(b).getByTestId("pick-cheapest").getAttribute("data-site-id")).toBe("mystic_valley_dermatology_associates_pc_somerville");
    for (const blk of [a, b]) expect(within(blk).getByTestId("cheapest-basis").textContent).toBe("Cheapest, from their own published prices");
    expect(within(a).queryByTestId("hmo-referral-notice")).toBeNull();
    expect(within(b).getByTestId("hmo-referral-notice").textContent).toBe(t("notice.hmo_referral_for_specialist"));
    // each option's own range
    expect(within(a).getByTestId("option-range").textContent).toBe("$136–$413 across 12 places with a price");
    expect(within(b).getByTestId("option-range").textContent).toBe("$131–$413 across 11 places with a price");
  });

  it("a non-derm site has no skin-doctor line any more (C4b item 2); with no includes the headline is the doctor visit", () => {
    const afc = site(LING, "afc_urgent_care_cambridge_cambridge");
    expect(afc.steps.map((s) => s.key)).not.toContain("skin_doctor_visit");
    expect(includesText(afc.headline_range!)).toBe("The doctor visit");
  });

  it("the switch to price re-asks the server; the list groups by option", () => {
    const onOrderBy = vi.fn();
    overview(LING, onOrderBy);
    fireEvent.click(within(screen.getByTestId("order-by")).getByRole("radio", { name: "Cheapest first" }));
    expect(onOrderBy).toHaveBeenCalledWith("price");
    const views = siteViews(LING.sites, null, now);
    expect(optionRuns(views).map((r) => r.optionId)).toEqual(["a", "b"]);
    render(<SiteList views={views} sort="price" onSort={() => {}} selectedId={null} onOpen={() => {}} hasLocation ordering={LING.ordering} options={LING.options} />);
    expect(screen.getAllByTestId("option-group").map((g) => g.querySelector("h3")?.textContent)).toEqual([
      "Option A: Urgent care or primary care · 12",
      "Option B: Skin doctor (dermatologist) · 12",
    ]);
  });

  it("the referral notice sits at the top of a specialist site's receipt, not in its notice list", () => {
    receipt(LING, site(LING, "mystic_valley_dermatology_associates_pc_somerville"));
    expect(screen.getByTestId("hmo-referral-notice")).toBeTruthy();
    expect(screen.getByTestId("receipt").textContent?.split(t("notice.hmo_referral_for_specialist")).length).toBe(2);
  });

  it("an HMO payment sends Q14 hmo_referral_required unless the person answered Q14 themselves", () => {
    expect(quoteAnswers(BCBS.payment, {})).toEqual({ Q14: ["hmo_referral_required"] });
    expect(quoteAnswers(BCBS.payment, { Q14: ["ppo"] })).toEqual({ Q14: ["ppo"] });
    expect(quoteAnswers(CASH.payment, {})).toEqual({});
    expect(quoteAnswers({ kind: "insurance", payer_id: "BCBS_MA", product: "PPO", network: null }, {})).toEqual({});
  });

  it("the ER reference for BCBS HMO is shown; not_loaded is not shown at all", () => {
    const { unmount } = render(<ErReferenceView er={LING.er_reference} />);
    expect(screen.getByTestId("er-range").textContent).toMatch(/^At the ER the visit alone usually costs \$\d/);
    unmount();
    const { container } = render(<ErReferenceView er={{ ...LING.er_reference!, status: "not_loaded", low: null, high: null, hospitals: [] }} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("map · one item at a time (P3, D-UI-3)", () => {
  it("the headline items are one per priced option; a pin is only on that option's sites", () => {
    const choices = headlineMapChoices(LING);
    expect(choices.map((c) => c.label)).toEqual(["Option A: whole visit", "Option B: whole visit"]);
    const afc = site(LING, "afc_urgent_care_cambridge_cambridge");
    expect(headlinePin(afc, "b")).toBeNull();
    expect(headlinePin(afc, "a")).toEqual({ kind: "price", text: "$136", estimated: false, partial: false });
    // stomach: option B is unpriced, so no map item for it; CHA's pin reads "from $149"
    expect(headlineMapChoices(ZHOU).map((c) => c.id)).toEqual(["option:a"]);
    expect(headlinePin(site(ZHOU, CHA_SOMERVILLE), "a")).toEqual({ kind: "price", text: "from $149", estimated: false, partial: true });
    // a quote without options: one "whole visit" item over every site
    expect(headlineMapChoices(COLON).map((c) => c.id)).toEqual(["option:*"]);
  });
});

describe("BCBS HMO colon screening (real pack)", () => {
  it("the polyp removal and pathology are listed on their own; the likely anesthesia with no price is said, not hidden", () => {
    const dfci = site(COLON, "dana_farber_cancer_institute");
    const hr = dfci.headline_range!;
    expect(hr.may_also_order.map((m) => m.step_key)).toEqual(["polyp_removal", "polyp_pathology"]);
    receipt(COLON, dfci);
    const head = screen.getByTestId("receipt-headline");
    expect(within(head).getAllByTestId("may-also-step").map((e) => e.getAttribute("data-step"))).toEqual(["polyp_removal", "polyp_pathology"]);
    // C4b data today: anesthesia (likely) has no figure under BCBS HMO at any of the 12 sites, so it is in
    // with_likely.not_priced, and the headline says so
    expect(hr.with_likely.not_priced).toEqual(["Medicine so you sleep through it"]);
    expect(within(head).getByTestId("headline-not-priced").textContent).toBe("Not in this figure, no price found: medicine so you sleep through it");
  });
});

describe("flat visit rate (C4b item 5), synthetic on a fixture line", () => {
  it("the line keeps its amount, says its note, and adds $0", () => {
    const sq = BCBS.sites.find((s) => s.site.site_id === AFC_INMAN)!;
    const xray = sq.receipt.lines.find((l) => l.line_id === "xray")!;
    const flat: ReceiptLine = { ...xray, in_total: false, price_notes: ["price.flat_visit_rate"] };
    const lines = sq.receipt.lines.map((l) => (l.line_id === "xray" ? flat : l));
    const totals = { ...sq.receipt.totals, excluded: [...sq.receipt.totals.excluded, { line_id: "xray", reason: "flat_visit_rate" as const }] };
    receipt(BCBS, { ...sq, receipt: { lines, totals } });
    expect(screen.getByTestId("flat-adds-zero").textContent).toBe("Adds $0: paid as part of the visit");
    expect(screen.getAllByTestId("price-note").map((n) => n.getAttribute("data-note"))).toContain("price.flat_visit_rate");
    expect(screen.getByText(`· ${t("total.excluded.flat_visit_rate")}`)).toBeTruthy();
  });
});
