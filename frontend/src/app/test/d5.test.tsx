/**
 * Round C4 · D5: the frontend on C3's and Chat2's contracts. Receipts fetched by site_ids (item 9), the
 * fixed chat copy (R18 / P13), and Austin's rules P3-P9 on screen. Numbers come from the committed
 * fixtures (contracts/fixtures/quote_*.json, C3 on the committed extract); synthetic cases say so.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CONTRACT_COPY, reviewKeys, t } from "@/contracts/copy";
import type { Catalog } from "@/generated/contracts/catalog";
import type { ChatResponse } from "@/generated/contracts/chat_api";
import type { QuoteResponse, ReceiptLine, SiteQuote } from "@/generated/contracts/quote_api";
import catalogJson from "../../../../contracts/fixtures/catalog.json";
import clarify from "../../../../contracts/fixtures/chat_clarify.json";
import carePaths from "../../../../contracts/fixtures/chat_care_paths.json";
import { ChatPane, type ChatActions } from "../components/ChatPane";
import { Receipt } from "../components/Receipt";
import { ResultsPane, type QuoteState } from "../components/ResultsPane";
import { SiteCard, SiteList } from "../components/SiteList";
import { availabilityKey, priceHidden } from "../lib/receipt";
import { kindGroups, siteViews, sortWithinKinds } from "../lib/sites";
import { mapStepKeys, stepLabels, stepOf, stepPin } from "../lib/steps";
import { BCBS, CASH, MASSHEALTH, MEDICARE } from "./fixtures";

const CATALOG = catalogJson as unknown as Catalog;
const closed = { known: true, openNow: false, openToday: false, text: "Closed" };
const now = { day: "sat" as const, minutes: 600 };
const site = (q: { sites: SiteQuote[] }, id: string) => q.sites.find((s) => s.site.site_id === id)!;
const AFC_INMAN = "afc_urgent_care_cambridge_inman_square_cambridge";
const AFC_CAMBRIDGE = "afc_urgent_care_cambridge_cambridge";

afterEach(() => vi.restoreAllMocks());

function renderReceipt(quote: QuoteResponse, sq: SiteQuote) {
  return render(
    <TooltipProvider>
      <Receipt quote={quote} sq={sq} distance={null} open={closed} location={null} />
    </TooltipProvider>,
  );
}

/** A copy of a fixture as C3 sends a no-location list: kind_then_distance, receipts on the first n only. */
function noLocation(q: QuoteResponse, n: number): QuoteResponse {
  const KIND = { urgent_care: 0, office: 1, hospital_outpatient: 2, ambulatory_surgery_center: 3 } as const;
  const sites = [...q.sites]
    .sort((a, b) => KIND[a.site.kind] - KIND[b.site.kind] || (a.distance_km ?? 0) - (b.distance_km ?? 0))
    .map((s, i) => (i < n ? s : { ...s, receipt: null, other_payers: [] }));
  return { ...q, ordering: "kind_then_distance", origin: { lat: 42.3603, lon: -71.058 }, sites };
}

function pane(state: QuoteState, view: "receipt" | "map" | "list", loadSite?: (id: string) => Promise<QuoteResponse>, selected: string | null = null) {
  return (
    <TooltipProvider>
      <ResultsPane
        payment={BCBS.payment}
        onPayment={() => {}}
        state={state}
        view={view}
        onView={() => {}}
        catalog={CATALOG}
        paths={[]}
        onBrowse={() => {}}
        location={null}
        onLocation={() => {}}
        pick={{ sort: "price", selected }}
        onPick={() => {}}
        loadSite={loadSite}
      />
    </TooltipProvider>
  );
}

describe("contracts · the fixtures and the copy file", () => {
  it("every committed quote fixture is a near request, so every site carries its receipt", () => {
    for (const q of [BCBS, CASH, MEDICARE, MASSHEALTH]) {
      expect(q.ordering).toBe("rank");
      expect(q.sites.every((s) => s.receipt != null)).toBe(true);
    }
  });

  it("has the C3 and Chat2 copy keys, each marked for Austin's review, wording from data/chat/copy.yaml", () => {
    const keys = [
      "price.group_consistently_higher",
      "price.group_consistently_lower",
      "total.excluded.availability_unknown",
      "total.excluded.unusual",
      "notice.chain_price_spread",
      "ai.paused_provider_chips",
      "chat.fixed_clarify",
      "chat.fixed_paths",
    ] as const;
    const review = reviewKeys();
    for (const k of keys) {
      expect(CONTRACT_COPY[k].en.length).toBeGreaterThan(10);
      expect(review).toContain(k);
    }
    expect(t("chat.fixed_clarify")).toBe("One more question helps narrow this down.");
    expect(t("chat.fixed_paths")).toBe("These care paths match your answers so far.");
    expect(t("ai.paused_provider_chips")).toBe(
      "The assistant can't read typed messages right now. Answer the questions below to find a care path, or browse prices.",
    );
  });

  it("never says best value anywhere a person reads (P7)", () => {
    const all = JSON.stringify(Object.values({ ...CONTRACT_COPY }).map((c) => c.en)) + JSON.stringify(t("list.scope_all", { n: 1 }));
    expect(all).not.toMatch(/best[- ]value/i);
  });
});

describe("Chat2 · fixed_text_key replaces the model's lead-in / text", () => {
  const actions = (): ChatActions => ({ send: vi.fn(), answer: vi.fn(), pickPath: vi.fn(), pickService: vi.fn(), browse: vi.fn() });
  it("clarify with fixed_text_key and no lead_in shows the fixed copy and keeps the chips", () => {
    const res = { ...(clarify as unknown as ChatResponse) };
    res.reply = { ...(res.reply as object), lead_in: null, fixed_text_key: "ai.paused_provider_chips" } as ChatResponse["reply"];
    render(<ChatPane turns={[{ role: "assistant", res }]} busy={false} error={null} answers={{}} actions={actions()} activePathId={null} />);
    expect(screen.getByTestId("fixed-text").textContent).toBe(t("ai.paused_provider_chips"));
    expect(screen.getAllByTestId("chip").length).toBeGreaterThan(0);
  });

  it("care_paths with text null and fixed_text_key shows the fixed copy, never a blank or 'null'", () => {
    const res = { ...(carePaths as unknown as ChatResponse) };
    res.reply = { ...(res.reply as object), text: null, fixed_text_key: "chat.fixed_paths" } as ChatResponse["reply"];
    const { container, unmount } = render(<ChatPane turns={[{ role: "assistant", res }]} busy={false} error={null} answers={{}} actions={actions()} activePathId={null} />);
    expect(screen.getByTestId("fixed-text").textContent).toBe("These care paths match your answers so far.");
    expect(container.textContent).not.toMatch(/\bnull\b/);
    unmount();
    // text null and no fixed key: nothing is printed for it
    const bare = { ...res, reply: { ...(res.reply as object), text: null, fixed_text_key: null } } as ChatResponse;
    const r2 = render(<ChatPane turns={[{ role: "assistant", res: bare }]} busy={false} error={null} answers={{}} actions={actions()} activePathId={null} />);
    expect(screen.queryByTestId("fixed-text")).toBeNull();
    expect(r2.container.textContent).not.toMatch(/\bnull\b/);
  });
});

describe("C3 item 9 · a list row needs no receipt; an opened site's receipt is fetched by site_ids", () => {
  it("the card reads the headline: total, estimate flag, steps done elsewhere (P4), never the receipt", () => {
    // D6: a response without a C4b headline range (headline_range null) keeps the C3 card
    const sq = { ...site(BCBS, AFC_INMAN), receipt: null, other_payers: [], headline_range: null };
    const labels = stepLabels(BCBS);
    render(<SiteCard v={{ sq, rank: 0, distance: null, open: closed }} onOpen={() => {}} labels={labels} />);
    // headline.likely 178.76-204.50 (whole dollars on cards), a floor: the referral has no dollar amount
    expect(sq.headline.complete).toBe(false);
    expect(screen.getByTestId("card-total").textContent).toBe("≥ $179–$205");
    expect(screen.getByTestId("card-estimate")).toBeTruthy();
    // physical therapy is likely and done elsewhere: p25-p75 196.43-257.00 over 14 groups
    const away = screen.getAllByTestId("card-elsewhere").map((e) => e.textContent);
    expect(away).toEqual(["+ Guided exercise program for the shoulder: about $196–$257 (typical price nearby)"]);
  });

  it("C4b: the card reads headline_range (certain + likely, with the step done elsewhere at its nearby range)", () => {
    const sq = { ...site(BCBS, AFC_INMAN), receipt: null, other_payers: [] };
    // visit 135.61 (estimate) + X-ray 43.15 (estimate) + PT elsewhere 196.43-257.00 = 375.19-461.50.
    // Data change (C4c, d863c59): basis partial -> includes_estimate
    expect(sq.headline_range).toMatchObject({ low: 375.19, high: 461.5, basis: "includes_estimate", from_only: false });
    render(<SiteCard v={{ sq, rank: 0, distance: null, open: closed }} onOpen={() => {}} labels={stepLabels(BCBS)} />);
    expect(screen.getByTestId("headline-figure").textContent).toBe("$375–$462");
    expect(screen.getByTestId("headline-includes").textContent).toBe(
      "Includes the visit with a bone & joint doctor, plus: quick picture of the shoulder bones and guided exercise program for the shoulder",
    );
    expect(screen.getByTestId("headline-basis").textContent).toBe("Includes an estimate");
    // the old "≥ total" and the separate "elsewhere" lines are not repeated next to the range
    expect(screen.queryByTestId("card-total")).toBeNull();
    expect(screen.queryByTestId("card-elsewhere")).toBeNull();
  });

  it("opening a summary-only site asks for it by site_ids once, then shows its receipt with its own sources", async () => {
    const list = noLocation(BCBS, 2);
    const target = list.sites[5];
    expect(target.receipt).toBeNull();
    const full = BCBS.sites.find((s) => s.site.site_id === target.site.site_id)!;
    const extraSource = "only_in_site_response";
    const fetched: QuoteResponse = {
      ...BCBS,
      sources: { ...BCBS.sources, [extraSource]: Object.values(BCBS.sources)[0] },
      sites: [full],
    };
    const loadSite = vi.fn(async () => fetched);
    const st: QuoteState = { status: "ok", key: "k1", quote: list, scope: { kind: "all" } };
    render(pane(st, "receipt", loadSite, target.site.site_id));
    expect(screen.getByTestId("receipt-pending").textContent).toContain(t("receipt.loading"));
    await waitFor(() => expect(screen.getByTestId("receipt")).toBeTruthy());
    expect(loadSite).toHaveBeenCalledTimes(1);
    expect(loadSite).toHaveBeenCalledWith(target.site.site_id);
    // the fetched site's own headline is shown (D6b: no separate bottom total)
    expect(within(screen.getByTestId("receipt-headline")).getByTestId("headline-figure").textContent).toBe(
      `$${Math.round(full.headline_range!.low)}–$${Math.round(full.headline_range!.high)}`,
    );
  });

  it("a failed fetch says so; it never shows another site's receipt", async () => {
    const list = noLocation(BCBS, 1);
    const target = list.sites[3];
    const st: QuoteState = { status: "ok", key: "k2", quote: list, scope: { kind: "all" } };
    render(pane(st, "receipt", async () => Promise.reject(new Error("500")), target.site.site_id));
    await waitFor(() => expect(screen.getByTestId("receipt-load-failed")).toBeTruthy());
    expect(screen.queryByTestId("receipt")).toBeNull();
  });
});

describe("P3 · the map prices one selected step, from SiteQuote.steps", () => {
  it("a pin only where the site says it offers the step; unknown availability gets no pin", () => {
    // physical therapy under BCBS HMO: AFC Cambridge is unknown (insurer_lists_rate), Mount Auburn offers it at $246.33
    const pt = (id: string) => stepPin(stepOf(site(BCBS, id), "physical_therapy"));
    expect(stepOf(site(BCBS, AFC_CAMBRIDGE), "physical_therapy")?.availability).toBe("unknown");
    expect(pt(AFC_CAMBRIDGE)).toBeNull();
    expect(pt("mount_auburn_hospital")).toEqual({ kind: "price", text: "$246", estimated: false });
    // an estimated step is marked as one (AFC Inman's visit: estimate 135.61-161.35)
    expect(stepPin(stepOf(site(BCBS, AFC_INMAN), "visit"))).toEqual({ kind: "price", text: "$136–$161", estimated: true });
    // Data change (C4c, d863c59): CHA's visit is now a from step (hospital bill 78.46-178.98 estimate, doctor's
    // bill not published): the pin reads "from $78", never a full price
    expect(stepPin(stepOf(site(BCBS, "cha_cambridge_hospital"), "visit"))).toEqual({ kind: "price", text: "from $78", estimated: true });
    // synthetic: the same step with a line set aside as unusual says so (never a cheap-looking pin)
    const st = { ...stepOf(site(BCBS, "cha_cambridge_hospital"), "visit")!, figure: "none" as const, low: null, high: null, from_only: false, unusual: true };
    expect(stepPin(st)).toEqual({ kind: "no_price", unusual: true });
  });

  it("the step chips leave out steps nobody prices; no step selected = places only", () => {
    const keys = mapStepKeys(BCBS);
    expect(keys).not.toContain("referral"); // happens at your own primary care office: no site prices it
    expect(keys).toEqual(expect.arrayContaining(["visit", "xray", "physical_therapy"]));
    render(pane({ status: "ok", key: "m", quote: BCBS, scope: { kind: "fixture" } }, "map"));
    expect(screen.getByTestId("map-price-note").textContent).toBe(t("map.places_only"));
    const chips = within(screen.getByTestId("map-steps")).getAllByRole("radio");
    expect(chips[0].textContent).toBe(t("map.no_step"));
    expect(chips[0].getAttribute("aria-checked")).toBe("true");
    const pt = "Guided exercise program for the shoulder"; // physical_therapy, named from the receipts' lines
    fireEvent.click(chips.find((c) => c.textContent === pt)!);
    expect(screen.getByTestId("map-price-note").textContent).toBe(t("map.step_price_for", { step: pt }));
  });
});

describe("P4 / P5 / P6 · own steps make the total; the rest are 'elsewhere' lines", () => {
  it("AFC Cambridge: physical therapy is its own line, Elsewhere about $196.43–$257.00, not in the total", () => {
    const sq = site(BCBS, AFC_CAMBRIDGE);
    renderReceipt(BCBS, sq);
    const steps = screen.getAllByTestId("elsewhere-step");
    const pt = steps.find((s) => s.getAttribute("data-step") === "physical_therapy")!;
    expect(within(pt).getByTestId("elsewhere-about").textContent).toBe("About $196.43–$257.00 (typical price nearby)");
    expect(pt.textContent).toContain("14 places that do it");
    // this place's own bills are the own steps only (totals.likely: visit 135.61 + X-ray 43.15-70.72); D6b: that
    // sum is not shown as a second total, the subtotals show the steps instead
    expect(sq.receipt!.totals.likely).toMatchObject({ low: 178.76, high: 206.33 });
    expect(screen.queryByTestId("total-bottom")).toBeNull();
    const pt2 = within(screen.getByTestId("range-build")).getAllByTestId("subtotal-step").find((e) => e.getAttribute("data-step") === "physical_therapy")!;
    expect(pt2.textContent).toContain("$196–$257 · Typical price nearby, not this place's own price");
    // the headline counts PT at its nearby range (C4b P4): 375.19-463.33
    expect(within(screen.getByTestId("receipt-headline")).getByTestId("headline-figure").textContent).toBe("$375–$463");
  });

  it("P6: the insurer-listed wording, and no Medicare figure shown as a BCBS person's price (rung 7 folded away)", () => {
    const sq = site(BCBS, AFC_CAMBRIDGE);
    renderReceipt(BCBS, sq);
    const why = screen.getAllByTestId("availability-why");
    expect(why[0].textContent).toBe("Your insurer lists a rate for this group, but this place doesn't say it offers this. Call to check.");
    // C4b 3d (1a7d986): no rung-7 Medicare figure is sent for a BCBS person at all; the fold-away guard for
    // one is tested on a synthetic line below and in receipt.test.tsx
    const rung7 = sq.receipt!.lines.filter((l) => l.doctor_fee?.explanation_key === "fee.rung_7_medicare_reference");
    expect(rung7).toEqual([]);
    expect(screen.queryAllByTestId("hidden-price").filter((h) => h.getAttribute("data-hidden") === "medicare_reference")).toEqual([]);
  });

  it("P6: 'your insurer lists a rate' is said only to a person paying with insurance", () => {
    expect(availabilityKey("insurer_lists_rate", BCBS.payment)).toBe("receipt.availability.insurer_lists_rate");
    for (const p of [MEDICARE.payment, CASH.payment, MASSHEALTH.payment])
      expect(availabilityKey("insurer_lists_rate", p)).toBe("receipt.availability.no_evidence");
    expect(availabilityKey(null, BCBS.payment)).toBeNull();
  });

  it("a card with no total says there is no price for this way of paying (never a bare dash)", () => {
    const base = site(CASH, AFC_CAMBRIDGE);
    const sq = { ...base, receipt: null, headline_range: null, headline: { ...base.headline, likely_low: null, likely_high: null } };
    render(<SiteCard v={{ sq, rank: 0, distance: null, open: closed }} onOpen={() => {}} />);
    expect(screen.getByTestId("card-total").textContent).toBe("—");
    expect(screen.getByTestId("card-no-total").textContent).toBe(t("list.no_total"));
  });

  it("priceHidden: rung 7 is hidden for every payment but Medicare, across every fixture line", () => {
    const all: [QuoteResponse, ReceiptLine][] = [BCBS, CASH, MEDICARE, MASSHEALTH].flatMap((q) =>
      q.sites.flatMap((s) => s.receipt.lines.map((l) => [q, l] as [QuoteResponse, ReceiptLine])),
    );
    // C4b 3d: the fixtures carry no rung-7 line any more, so every money line is made one (synthetic)
    const r7 = all
      .filter(([, l]) => l.cell?.kind === "money")
      .map(([q, l]) => [q, { ...l, doctor_fee: { rung: 7, explanation_key: "fee.rung_7_medicare_reference", group_name: null, group_tin: null, npi_count: null, chia_badge: null, by_npi: null } }] as [QuoteResponse, ReceiptLine]);
    expect(r7.length).toBeGreaterThan(50);
    expect(new Set(r7.map(([q]) => q.payment.kind))).toEqual(new Set(["insurance", "cash", "medicare", "masshealth"]));
    for (const [q, l] of r7)
      expect(priceHidden(l, q.payment)).toBe(
        q.payment.kind === "medicare"
          ? l.availability === "unknown" && l.at === "this_site"
            ? "listed_price"
            : l.unusual?.whole_line
              ? "unusual"
              : null
          : "medicare_reference",
      );
  });

  it("P5: an estimated line says it is one and what it rests on; the total says it includes an estimate", () => {
    const sq = site(BCBS, AFC_INMAN);
    const est = sq.receipt!.lines.filter((l) => l.estimate != null);
    expect(est.length).toBe(2); // visit and X-ray
    renderReceipt(BCBS, sq);
    expect(screen.getAllByTestId("estimate-tag").length).toBe(2);
    const basis = screen.getAllByTestId("estimate-basis").map((b) => b.textContent);
    expect(basis.length).toBe(2);
    expect(basis[0]).toMatch(new RegExp(`^Estimate: the middle half of prices at ${est[0].estimate!.n_groups} `));
    expect(screen.getByTestId("headline-basis").textContent).toBe("Includes an estimate");
    // each estimated line's plain footnote says so
    expect(screen.getAllByTestId("line-footnote").filter((f) => f.getAttribute("data-kind") === "estimate").length).toBe(2);
  });
});

describe("P7 · no location: every place, grouped by kind, by distance from Boston City Hall", () => {
  it("groups in the server's order under kind headers, distance from City Hall on each card", () => {
    const list = noLocation(BCBS, 12);
    const views = siteViews(list.sites, null, now);
    const groups = kindGroups(views).map((g) => g.kind);
    expect(groups).toEqual(["urgent_care", "office", "hospital_outpatient"]);
    render(<SiteList views={views} sort="price" onSort={() => {}} selectedId={null} onOpen={() => {}} hasLocation={false} scope={{ kind: "all" }} ordering="kind_then_distance" />);
    const heads = screen.getAllByTestId("kind-group").map((g) => g.querySelector("h3")?.textContent);
    expect(heads).toEqual(["Urgent care · 4", "Doctors' offices · 1", "Hospital outpatient clinics · 7"]);
    expect(screen.getAllByTestId("site-card")[0].textContent).toMatch(/mi from Boston City Hall/);
    expect(screen.getByTestId("site-list").textContent).not.toMatch(/best/i);
    expect(screen.getByRole("radio", { name: "By distance" })).toBeTruthy();
  });

  it("a sort inside the list keeps every kind together", () => {
    const views = siteViews(noLocation(BCBS, 12).sites, null, now);
    const sorted = sortWithinKinds(views, "open_today");
    expect(kindGroups(sorted).map((g) => g.kind)).toEqual(["urgent_care", "office", "hospital_outpatient"]);
  });
});

describe("P8 / P8a / P9 / anesthesia / chains on the receipt", () => {
  it("P8: a whole-line unusual price says 'being checked' and is not in the total (CHA visit facility fee)", () => {
    // Data change (C4b fixtures, 1a7d986): CHA's visit facility line is now a summed peer estimate (78.46) and no
    // fixture line is whole-line unusual. Synthetic: that line with every row set aside, as the engine sends it.
    const base = site(BCBS, "cha_cambridge_hospital");
    const orig = base.receipt!.lines.find((l) => l.line_id === "visit_facility")!;
    expect(orig.unusual).toBeNull();
    const line = { ...orig, in_total: false, unusual: { peer_median: 235.0, n_groups: 7, whole_line: true, set_aside: [] } } as ReceiptLine;
    const sq = { ...base, receipt: { ...base.receipt!, lines: base.receipt!.lines.map((l) => (l.line_id === "visit_facility" ? line : l)) } };
    expect(priceHidden(line, BCBS.payment)).toBe("unusual");
    renderReceipt(BCBS, sq);
    expect(screen.getAllByTestId("unusual")[0].textContent).toBe("Price looks unusual, being checked");
  });

  it("P9: possible steps are 'might add $X–$Y', never in the headline (Mount Auburn)", () => {
    // without a C4b headline range (older response): the C3 'might add' line under the receipt total
    const sq = { ...site(BCBS, "mount_auburn_hospital"), headline_range: null };
    renderReceipt(BCBS, sq);
    const m = screen.getByTestId("might-add").textContent ?? "";
    expect(m).toMatch(/^Might add \$281\.49–\$4,224\.80 if the doctor decides you need: /);
    expect(screen.getByTestId("total-top").textContent).toBe("≥ $669.03–$723.38");
  });

  it("C4b: possible steps are listed on their own (plain name, why, own price), never in the headline (Mount Auburn)", () => {
    const sq = site(BCBS, "mount_auburn_hospital");
    renderReceipt(BCBS, sq);
    expect(screen.queryByTestId("might-add")).toBeNull();
    const rows = screen.getAllByTestId("may-also-step").map((r) => [r.getAttribute("data-step"), r.querySelector("span.ml-auto")?.textContent]);
    expect(rows).toEqual([
      ["steroid_injection", "$536–$558"],
      ["tendon_scan_ultrasound", "$281"],
      ["tendon_scan_mri", "$780"],
      ["mr_arthrogram", "$2,581–$2,605"],
    ]);
    expect(screen.getByTestId("headline-figure").textContent).toBe("$669–$723");
  });

  it("P9: unknown billing says it is priced as a hospital clinic; a facility line with no price says the fee may apply", () => {
    // synthetic: MGPO Cambridge (billing unknown) with its visit facility line turned into the engine's P9 Gap
    const sq = site(BCBS, "massachusetts_general_physicians_organization_inc_cambri");
    expect(sq.site.billing_type).toBe("unknown");
    const lines = sq.receipt!.lines.map((l) =>
      l.line_id === "visit_facility"
        ? ({ ...l, cell: { kind: "not_published", what: "a hospital facility fee this place may also charge (we could not confirm how it bills)", ask: "Ask the center what your plan pays for its facility fee.", searched: { source_id: "x", source_sha256: "y" } } } as ReceiptLine)
        : l,
    );
    renderReceipt(BCBS, { ...sq, receipt: { ...sq.receipt!, lines } });
    expect(screen.getByText(t("billing.unknown"))).toBeTruthy();
    // the synthetic visit_facility Gap plus the fixture's own physical_therapy_sessions_facility Gap
    expect(screen.getAllByTestId("facility-fee-possible").length).toBe(2);
  });

  it("P8a, anesthesia and the chain line (synthetic fields on a fixture line)", () => {
    const sq = site(BCBS, AFC_CAMBRIDGE);
    const lines = sq.receipt!.lines.map((l) =>
      l.line_id === "visit"
        ? ({
            ...l,
            price_notes: ["price.group_consistently_higher"],
            chain_price_from: "afc_watertown",
            anesthesia_time: { minutes: 30, base_units: 4, low: 210, high: 260, source: "CMS" },
          } as ReceiptLine)
        : l,
    );
    renderReceipt(BCBS, { ...sq, site: { ...sq.site, chain_id: "afc_urgent_care" }, receipt: { ...sq.receipt!, lines } });
    expect(screen.getAllByTestId("price-note").map((n) => n.textContent)).toContain("This group's prices are consistently higher than similar places here.");
    // C4b: the chain's display name comes from the contract (SiteSummary.chain_name)
    expect(sq.site.chain_name).toBe("AFC Urgent Care");
    expect(screen.getByTestId("chain-price").textContent).toBe("AFC Urgent Care's posted self-pay price for all its locations");
    expect(screen.getByTestId("anesthesia-time").textContent).toBe("With a typical time (30 min), about $210.00–$260.00. Not in the total.");
  });
});
