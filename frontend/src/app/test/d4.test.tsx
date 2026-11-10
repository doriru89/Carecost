/**
 * Round C3 · D4: frontend fixes on today's contract. Self-pay label (P2), no stale receipt on a payment
 * switch (R15), no hand-kept "not loaded" (R16), chips survive a paused AI (R18), map price only for one
 * selected service (P3), phone tabs keep the prices pane mounted.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { APP_COPY, CONTRACT_COPY, reviewKeys, t } from "@/contracts/copy";
import type { Catalog } from "@/generated/contracts/catalog";
import type { ChatResponse } from "@/generated/contracts/chat_api";
import type { QuoteResponse } from "@/generated/contracts/quote_api";
import catalogJson from "../../../../contracts/fixtures/catalog.json";
import clarify from "../../../../contracts/fixtures/chat_clarify.json";
import paused from "../../../../contracts/fixtures/chat_ai_paused.json";
import { getApi } from "../api/client";
import { ChatPane, type ChatActions } from "../components/ChatPane";
import { PaymentSelect } from "../components/PaymentSelect";
import { Receipt } from "../components/Receipt";
import { ResultsPane, type QuoteState } from "../components/ResultsPane";
import { Workspace } from "../components/Workspace";
import { priceChoices } from "../lib/priceChoices";
import { mapService, serviceCodes } from "../lib/mapPrice";
import { PAYMENT_CHOICES } from "../lib/payments";
import CareApp, { QUOTE_TIMEOUT_MS } from "../pages/CareApp";
import { BCBS, CASH, MASSHEALTH } from "./fixtures";

// jsdom has no WebGL: MapLibre cannot draw here; the map pins are tested through lib/steps and lib/browse
vi.mock("../components/SiteMap", () => ({ SiteMap: () => <div data-testid="site-map" /> }));

const CATALOG = catalogJson as unknown as Catalog;
const closed = { known: true, openNow: false, openToday: false, text: "Closed" };
const CASH_WORD = /\bcash\b/i;

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("P2 · self-pay, never 'cash', wherever a person reads it", () => {
  it("the payment choice reads Self-pay (no insurance) / 自费（无保险）, marked for review; the enum stays cash", () => {
    const c = PAYMENT_CHOICES.find((x) => x.id === "cash")!;
    expect(c.payment).toEqual({ kind: "cash" });
    expect(c.label).toBe("Self-pay (no insurance)");
    expect(APP_COPY["payment.self_pay"].zh).toBe("自费（无保险）");
    expect(reviewKeys()).toEqual(expect.arrayContaining(["payment.self_pay", "youpay.cash_full_amount", "receipt.no_cash_discount", "fee.self_pay_no_source"]));
  });

  it("no copy line and no payment label says cash", () => {
    const all = { ...CONTRACT_COPY, ...APP_COPY } as Record<string, { en: string }>;
    expect(Object.entries(all).filter(([, c]) => CASH_WORD.test(c.en)).map(([k]) => k)).toEqual([]);
    expect(PAYMENT_CHOICES.filter((c) => CASH_WORD.test(c.label)).map((c) => c.id)).toEqual([]);
  });

  it("a self-pay receipt never shows the word cash, at any site of the fixture", () => {
    for (const sq of CASH.sites) {
      const { container, unmount } = render(
        <TooltipProvider>
          <Receipt quote={CASH} sq={sq} distance={null} open={closed} location={null} />
        </TooltipProvider>,
      );
      expect(container.textContent).not.toMatch(CASH_WORD);
      unmount();
    }
  });
});

describe("R16 · no hand-kept 'not loaded' label on an insurer", () => {
  it("the payment menu never says an insurer's files are not loaded (the quote's own notice says so)", () => {
    render(<PaymentSelect value={null} onChange={() => {}} />);
    const options = screen.getAllByRole("option").map((o) => o.textContent ?? "");
    expect(options.some((o) => o.startsWith("Harvard Pilgrim"))).toBe(true);
    expect(options.some((o) => o.startsWith("Tufts Health Plan"))).toBe(true);
    expect(options.filter((o) => /not loaded/i.test(o))).toEqual([]);
  });
});

function pane(state: QuoteState, view: "receipt" | "map" = "receipt", payment = CASH.payment) {
  return (
    <TooltipProvider>
      <ResultsPane
        payment={payment}
        onPayment={() => {}}
        state={state}
        view={view}
        onView={() => {}}
        catalog={CATALOG}
        paths={[]}
        onBrowse={() => {}}
        location={null}
        onLocation={() => {}}
        pick={{ sort: "price", selected: null }}
        onPick={() => {}}
      />
    </TooltipProvider>
  );
}

describe("R15 · the previous payment's receipt is never shown as current", () => {
  const ok = { status: "ok" as const, key: "BCBS_MA:HMO|x", quote: BCBS, scope: { kind: "fixture" as const } };

  it("while the new quote loads, the old receipt is dimmed and says it is updating for the new choice", () => {
    render(pane({ status: "loading", key: "cash|x", prev: ok }));
    const body = screen.getByTestId("quote-body");
    expect(body.dataset.updating).toBe("true");
    expect(body.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByTestId("quote-updating").textContent).toBe(t("quote.updating", { payment: "Self-pay (no insurance)" }));
    // the old receipt is not the current one: the pane's quote key is empty until the new one lands
    expect(screen.getByTestId("results-pane").dataset.quoteKey).toBe("");
  });

  it("a current quote has no updating banner; a first load with nothing before says Pricing…", () => {
    const { unmount } = render(pane(ok, "receipt", BCBS.payment));
    expect(screen.queryByTestId("quote-updating")).toBeNull();
    expect(screen.getByTestId("results-pane").dataset.quoteKey).toBe(ok.key);
    unmount();
    render(pane({ status: "loading", key: "cash|x" }));
    expect(screen.getByText("Pricing…")).toBeTruthy();
    expect(screen.queryByTestId("receipt")).toBeNull();
  });

  it("in the app: switching to self-pay dims the BCBS receipt, then a hung server times out into 'Could not load prices'", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = getApi();
    const real = api.quote.bind(api);
    const spy = vi.spyOn(api, "quote");
    // first quote (BCBS) answers; the self-pay one hangs until it is aborted
    spy.mockImplementationOnce(real);
    spy.mockImplementationOnce(
      (_req, opts) =>
        new Promise<QuoteResponse>((_res, rej) => opts?.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")))),
    );
    render(
      <MemoryRouter>
        <CareApp />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByTestId("payment-select"), { target: { value: "BCBS_MA:HMO" } });
    fireEvent.change(screen.getByTestId("email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByTestId("start-chat"), { target: { value: "my shoulder clicks" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    // An AI-ranked path is only offered (the quote contract refuses an assistant-picked care path):
    // the person taps "See prices" on the card.
    fireEvent.click((await screen.findAllByRole("button", { name: "See prices" }))[0]);
    // D6 (D-UI-1): a care path's quote opens on the first screen (options, cheapest, alternates)
    await waitFor(() => expect(screen.getByTestId("overview")).toBeTruthy());
    expect(screen.queryByTestId("quote-updating")).toBeNull();

    // the Where to go section (the sidebar holds several result panes; the payment switch is shared above them)
    const pickSection = () => within(document.querySelector('[data-section="pick"]') as HTMLElement);
    const results = pickSection().getByTestId("results-pane");
    fireEvent.change(screen.getByTestId("payment-select"), { target: { value: "cash" } });
    await waitFor(() => expect(pickSection().getByTestId("quote-updating").textContent).toContain("Self-pay (no insurance)"));
    expect(pickSection().getByTestId("quote-body").dataset.updating).toBe("true");
    expect(results.dataset.quoteKey).toBe("");

    await act(async () => {
      vi.advanceTimersByTime(QUOTE_TIMEOUT_MS + 10);
    });
    await waitFor(() => expect(pickSection().getByTestId("quote-unavailable").textContent).toContain(t("quote.timeout")));
    expect(screen.queryByTestId("overview")).toBeNull();
    expect(screen.queryByTestId("receipt")).toBeNull();
    expect(spy.mock.calls[1][1]?.signal?.aborted).toBe(true);
  });
});

describe("R18 · chips are code-only: a paused AI does not switch them off", () => {
  const actions = (): ChatActions => ({ send: vi.fn(), answer: vi.fn(), pickPath: vi.fn(), pickService: vi.fn(), browse: vi.fn() });
  const chips = clarify as unknown as ChatResponse;
  const noKey = {
    ...(paused as unknown as ChatResponse),
    llm_called: false,
    reply: { kind: "ai_paused", reason: "provider_unavailable", message_key: "ai.paused_provider", resumes_at: null, browse_prices_available: true },
  } as ChatResponse;

  it("a server clarify with no lead-in (no model called) renders its chips, answerable", () => {
    const res = { ...chips, llm_called: false, reply: { ...(chips.reply as object), lead_in: null } } as ChatResponse;
    const a = actions();
    render(<ChatPane turns={[{ role: "user", text: "shoulder" }, { role: "assistant", res }]} busy={false} error={null} answers={{}} actions={a} activePathId={null} />);
    const chip = screen.getAllByTestId("chip")[0] as HTMLButtonElement;
    expect(chip.disabled).toBe(false);
  });

  it("the chips stay answerable after a later ai_paused turn", () => {
    const a = actions();
    render(
      <ChatPane
        turns={[
          { role: "user", text: "shoulder" },
          { role: "assistant", res: chips },
          { role: "user", text: "more" },
          { role: "assistant", res: noKey },
        ]}
        busy={false}
        error={null}
        answers={{}}
        actions={a}
        activePathId={null}
      />,
    );
    const chip = screen.getAllByTestId("chip").find((b) => !(b as HTMLButtonElement).disabled);
    expect(chip).toBeTruthy();
    fireEvent.click(chip!);
    expect(a.answer).toHaveBeenCalledOnce();
  });
});

describe("P3 · the map shows a price only for one selected service", () => {
  it("a care path quote has no map service; a manual pick of one catalog service does", () => {
    expect(mapService(BCBS, CATALOG)).toBeNull();
    const svc = CATALOG.services.find((s) => serviceCodes(s).length === 1)!;
    const one = { ...MASSHEALTH, care_path: null, service_codes: serviceCodes(svc) } as QuoteResponse;
    expect(mapService(one, CATALOG)?.service_id).toBe(svc.service_id);
    // two services in one manual pick (the MassHealth fixture: X-ray + MRI) is not one service
    expect(MASSHEALTH.service_codes.length).toBe(2);
    expect(mapService(MASSHEALTH, CATALOG)).toBeNull();
    expect(mapService(one, null)).toBeNull();
  });

  it("Austin 2026-11-09: a care path's map prices its first item (the whole visit) with nothing picked, never places only", () => {
    render(pane({ status: "ok", key: "k", quote: BCBS, scope: { kind: "fixture" } }, "map", BCBS.payment));
    const first = priceChoices(BCBS)[0];
    expect(first.item.kind).toBe("headline");
    expect(screen.getByTestId("map-price-note").textContent).toBe(t("map.headline_for", { option: first.label }));
  });
});

describe("Workspace · the map is the main canvas, the views are sidebar sections", () => {
  const Icon = () => null;
  const sections = [
    { id: "ai", title: "AI helper", icon: Icon as never, content: <p data-testid="ai-content">chat</p> },
    { id: "receipt", title: "Breakdown", icon: Icon as never, summary: "MGH", content: <p>receipt</p> },
  ];
  it("several sections open at once; a closed one stays mounted and shows its summary", () => {
    const toggles: [string, boolean][] = [];
    const ws = (open: Record<string, boolean>) => (
      <Workspace head={<p>head</p>} sections={sections} open={open} onToggle={(id, o) => toggles.push([id, o])} map={<p data-testid="the-map">map</p>} collapsed={false} onCollapsed={() => {}} />
    );
    const { rerender } = render(ws({ ai: true, receipt: true }));
    expect(screen.getByTestId("the-map")).toBeTruthy();
    const ai = screen.getByTestId("ai-content");
    expect((ai.parentElement as HTMLElement).hidden).toBe(false);
    rerender(ws({ ai: false, receipt: true }));
    expect(screen.getByTestId("ai-content")).toBe(ai); // same node: not unmounted
    expect((ai.parentElement as HTMLElement).hidden).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /AI helper/ }));
    expect(toggles).toEqual([["ai", true]]);
  });
  it("folded, the sidebar is a rail of section buttons; one opens the sidebar and that section", () => {
    const calls: string[] = [];
    render(
      <Workspace head={<p>head</p>} sections={sections} open={{}} onToggle={(id, o) => calls.push(`${id}:${o}`)} map={<p>map</p>} collapsed onCollapsed={(c) => calls.push(`collapsed:${c}`)} />,
    );
    expect(screen.queryByTestId("sidebar-sections")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Breakdown" }));
    expect(calls).toEqual(["collapsed:false", "receipt:true"]);
  });
});
