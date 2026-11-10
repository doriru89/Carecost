import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bot, ListOrdered, MapPin, Receipt as ReceiptIcon, Send, SlidersHorizontal } from "lucide-react";
import CareCostLogo from "@/components/CareCostLogo";
import { t } from "@/contracts/copy";
import { CHAT_REPLY_FULL_PAGE } from "@/contracts/exhaustive";
import type { Catalog, CatalogPath, CatalogService } from "@/generated/contracts/catalog";
import { browseValueOf, DEFAULT_BROWSE_SERVICE, type BrowseValue, type KindFilter, type ShowFilter } from "../lib/browse";
import type { CandidatePath, ChatRequest, RedFlagReply, ServiceRef } from "@/generated/contracts/chat_api";
import type { Payment, QuoteRequest, QuoteResponse } from "@/generated/contracts/quote_api";
import { ApiError, getApi, nearFor, NoMockData } from "../api/client";
import { ChatPane, type ChatTurn } from "../components/ChatPane";
import { PaymentSelect } from "../components/PaymentSelect";
import { ResultsPane, type QuoteState, type ResultsView, type SitePick } from "../components/ResultsPane";
import type { SiteScope } from "../lib/sites";
import { LocationInput } from "../components/ResultsPane";
import { BrowseBar } from "../components/BrowseBar";
import { Workspace, type Section } from "../components/Workspace";
import { priceChoices } from "../lib/priceChoices";
import type { UserLocation } from "../lib/geo";
import { serviceCodes } from "../lib/mapPrice";
import { paymentId } from "../lib/payments";
import type { OrderBy } from "../components/Overview";
import { RedFlagPage } from "./StopPages";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/**
 * R15: a quote that has not answered after this long is given up on and the person is told so. The server
 * scales to zero (Cloud Run), and a cold start loads the price data first (about 30 s), so this covers one;
 * past 3 s the pane says the server is starting (ResultsPane WAKING_AFTER_MS). Cloud Run's own limit is 60 s.
 */
export const QUOTE_TIMEOUT_MS = 55_000;
const MAX_HISTORY = 6;

type Query = Pick<QuoteRequest, "care_path_id" | "service_codes" | "picked_by">;

function requestKey(payment: Payment, q: Query, where = "", orderBy: OrderBy = "distance"): string {
  return `${paymentId(payment)}|${q.care_path_id ?? q.service_codes.join(",")}|${q.picked_by}|${where}|${orderBy}`;
}

/** The part of the request key that depends on location: the `near` point quoteBody() will send. */
function whereKey(mode: "mock" | "api", location: UserLocation | null): string {
  if (mode === "mock") return "";
  const n = nearFor(location);
  return n ? `${n.lat},${n.lon}` : "all";
}

function siteScope(mode: "mock" | "api", location: UserLocation | null): SiteScope {
  if (mode === "mock") return { kind: "fixture" };
  if (!location || !nearFor(location)) return { kind: "all" };
  return { kind: "near", label: location.kind === "device" ? "you" : location.label };
}

declare global {
  interface Window {
    /** Measured insurance switches: select change -> next frame after the new receipt commits (ms). Read by scripts/screenshots.mjs. */
    __carecostSwitch?: { ms: number; key: string }[];
  }
}

export default function CareApp() {
  const api = getApi();
  const navigate = useNavigate();
  const [payment, setPayment] = useState<Payment | null>(null);
  const [email, setEmail] = useState("");
  const [phase, setPhase] = useState<"start" | "work">("start");
  const [draft, setDraft] = useState("");

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [redFlag, setRedFlag] = useState<RedFlagReply | null>(null);

  const [query, setQuery] = useState<Query | null>(null);
  const [quoteState, setQuoteState] = useState<QuoteState>({ status: "idle" });
  const cache = useRef(new Map<string, QuoteState>());
  const switchStart = useRef<{ t: number; key: string } | null>(null);

  // Austin 2026-11-09: the map is the main canvas; the other views are sidebar sections, several open at once
  const [open, setOpen] = useState<Record<string, boolean>>({ ai: true, browse: false, pick: true, list: false, receipt: false });
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  /** open a section and scroll to it (a pin or card opens Breakdown; "See all" opens List) */
  const show = useCallback((v: ResultsView) => {
    if (v === "map") return;
    setOpen((o) => ({ ...o, [v]: true }));
    setFocus((f) => ({ id: v, n: (f?.n ?? 0) + 1 }));
  }, []);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [showFilter, setShowFilter] = useState<ShowFilter>("offered");
  const [orderBy, setOrderBy] = useState<OrderBy>("distance");
  const [location, setLocation] = useState<UserLocation | null>(null);
  const [pick, setPick] = useState<SitePick>({ sort: "price", selected: null });
  const [collapsed, setCollapsed] = useState(readCollapsed);
  useEffect(() => writeCollapsed(collapsed), [collapsed]);
  // P3: the price item the map pins and the list's step line show; reset when a different quote arrives
  const [priceStep, setPriceStep] = useState<string | null>(null);
  const shownQuote = quoteState.status === "ok" ? quoteState : quoteState.status === "loading" ? (quoteState.prev ?? null) : null;
  const shownQuoteKey = shownQuote?.key ?? "";
  useEffect(() => setPriceStep(null), [shownQuoteKey]);
  const choices = useMemo(() => (shownQuote ? priceChoices(shownQuote.quote) : []), [shownQuote]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [paths, setPaths] = useState<CatalogPath[] | null>(null);

  useEffect(() => {
    api.catalog().then(setCatalog, () => setCatalog(null));
    api.catalogPaths().then(setPaths, () => setPaths([]));
  }, [api]);

  // Browse: a dropdown pick sets the query and stays on Browse (the map is where the person is looking)
  const browsePick = useCallback(
    (v: BrowseValue) => {
      if (v.startsWith("path:")) {
        setQuery({ care_path_id: v.slice(5), service_codes: [], picked_by: "person" });
        return;
      }
      const svc = catalog?.services.find((x) => x.service_id === v.slice(4));
      if (svc) setQuery({ care_path_id: null, service_codes: serviceCodes(svc), picked_by: "person" });
    },
    [catalog],
  );
  // Browse never opens on an empty map: with nothing chosen yet, a new-patient visit. Not while the person is
  // asking the AI (office-visit prices next to a shoulder question would read as the answer).
  const browseOpen = !!open.browse;
  useEffect(() => {
    if (phase === "work" && payment && browseOpen && !query && catalog) browsePick(`svc:${DEFAULT_BROWSE_SERVICE}`);
  }, [phase, payment, browseOpen, query, catalog, browsePick]);

  // ---- quotes: one request per (payment, query); cached so switching back is instant
  useEffect(() => {
    if (!payment || !query) return;
    const key = requestKey(payment, query, whereKey(api.mode, location), orderBy);
    const hit = cache.current.get(key);
    if (hit) {
      setQuoteState(hit);
      return;
    }
    let live = true;
    let timedOut = false;
    const ctl = new AbortController();
    const timer = setTimeout(() => {
      timedOut = true;
      ctl.abort();
    }, QUOTE_TIMEOUT_MS);
    // R15: the last receipt may stay on screen while this one loads, but only as `prev` of a loading
    // state: ResultsPane dims it and says it is updating. A quote is never shown as current unless its
    // key is this request's key.
    setQuoteState((s) => ({ status: "loading", key, prev: s.status === "ok" ? s : s.status === "loading" ? s.prev : undefined }));
    api
      .quote(
        { payment, ...query, answers, site_ids: null, ...(orderBy === "price" ? { order_by: "price" as const } : {}) },
        { location, signal: ctl.signal },
      )
      .then((quote) => {
        const st: QuoteState = { status: "ok", key, quote, scope: siteScope(api.mode, location) };
        cache.current.set(key, st);
        if (live) setQuoteState(st);
      })
      .catch((e: unknown) => {
        if (!live) return;
        const st: QuoteState =
          e instanceof NoMockData
            ? { status: "nomock", key, message: e.message }
            : { status: "error", key, message: timedOut ? t("quote.timeout") : e instanceof Error ? e.message : String(e) };
        setQuoteState(st);
      })
      .finally(() => clearTimeout(timer));
    return () => {
      live = false;
      clearTimeout(timer);
      ctl.abort();
    };
  }, [api, payment, query, location, orderBy]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- the <300 ms check: time from the payment change to the new receipt being committed
  useEffect(() => {
    const s = switchStart.current;
    if (!s || quoteState.status === "loading" || quoteState.status === "idle") return;
    if (quoteState.key !== s.key) return;
    switchStart.current = null;
    // next animation frame ≈ the new receipt has been painted
    requestAnimationFrame(() => {
      (window.__carecostSwitch ??= []).push({ ms: performance.now() - s.t, key: s.key });
    });
  }, [quoteState]);

  // C3 item 9: one site's full receipt, for a no-location list that carries only its summary.
  // Same payment, query and answers as the list; `site_ids` names the site (no `near`, so the ordering
  // and the distances stay the list's). Cached per request key + site.
  const siteCache = useRef(new Map<string, Promise<QuoteResponse>>());
  const loadSite = useCallback(
    (siteId: string) => {
      if (!payment || !query) return Promise.reject(new Error("no quote"));
      const key = `${requestKey(payment, query)}|${siteId}`;
      let p = siteCache.current.get(key);
      if (!p) {
        p = api.quote({ payment, ...query, answers, site_ids: [siteId] });
        p.catch(() => siteCache.current.delete(key));
        siteCache.current.set(key, p);
      }
      return p;
    },
    [api, payment, query, answers],
  );

  const changePayment = (p: Payment) => {
    if (query) switchStart.current = { t: performance.now(), key: requestKey(p, query, whereKey(api.mode, location), orderBy) };
    setPayment(p);
  };

  // ---- chat
  const sendChat = useCallback(
    async (text: string, nextAnswers: Record<string, string[]> = answers) => {
      if (!payment) return;
      if (!EMAIL_RE.test(email)) {
        setChatError("Add your email above to use the AI helper (we don't verify it). Or skip AI and browse prices.");
        return;
      }
      setTurns((ts) => [...ts, { role: "user", text }]);
      setChatBusy(true);
      setChatError(null);
      const req: ChatRequest = {
        conversation_id: conversationId,
        text,
        payment,
        email,
        answers: nextAnswers,
        history: history.slice(-MAX_HISTORY),
        focus: null,
        locale: "en",
      };
      try {
        const res = await api.chat(req);
        setConversationId(res.conversation_id);
        setHistory((h) => [...h, text].slice(-MAX_HISTORY));
        if (CHAT_REPLY_FULL_PAGE[res.reply.kind] && res.reply.kind === "red_flag") {
          setRedFlag(res.reply);
          setQuery(null);
          return;
        }
        setTurns((ts) => [...ts, { role: "assistant", res }]);
        const r = res.reply;
        if ((r.kind === "clarify" || r.kind === "care_paths") && r.candidates.length > 0) {
          // Prices from turn one; later questions only refine (§4.1). An entry-matched path follows from the
          // person's own answers (deterministic), so it is quoted at once. An AI-ranked one is only offered:
          // the quote contract refuses a care-path quote picked by the assistant (422), so the person taps
          // "See prices" on the card (pickPath, picked_by: person).
          const top = r.candidates[0];
          if (top.match === "entry_matched") {
            setQuery({ care_path_id: top.path_id, service_codes: [], picked_by: "person" });
            show("pick");
          }
        }
      } catch (e) {
        // The server could not answer at all (no reply to render): say so plainly, keep browsing open.
        setChatError(e instanceof ApiError ? t("chat.unreachable", { status: e.status }) : t("chat.unreachable_network"));
      } finally {
        setChatBusy(false);
      }
    },
    [api, answers, conversationId, email, history, payment, show],
  );

  const actions = {
    send: (text: string) => void sendChat(text),
    answer: (qid: string, values: string[], labels: string[]) => {
      const next = { ...answers, [qid]: values };
      setAnswers(next);
      void sendChat(labels.join(", "), next);
    },
    pickPath: (c: CandidatePath) => {
      setQuery({ care_path_id: c.path_id, service_codes: [], picked_by: "person" });
      show("pick");
    },
    pickService: (s: ServiceRef) => {
      const svc = catalog?.services.find((x) => x.service_id === s.service_id);
      if (svc) pickService(svc, "assistant");
    },
    browse: () => show("browse"),
  };

  const pickService = (s: CatalogService, by: "person" | "assistant" = "person") => {
    setQuery({ care_path_id: null, service_codes: serviceCodes(s), picked_by: by });
    show("pick");
  };

  const resetAll = () => {
    setRedFlag(null);
    setTurns([]);
    setHistory([]);
    setAnswers({});
    setConversationId(null);
    setQuery(null);
    setQuoteState({ status: "idle" });
    setPick({ sort: "price", selected: null });
    setPhase("start");
    navigate("/");
  };

  if (redFlag) return <RedFlagPage reply={redFlag} onBack={resetAll} />;

  if (phase === "start" || !payment) {
    const canChat = !!payment && draft.trim().length > 0;
    return (
      <main className="min-h-screen bg-background" data-testid="start-page">
        <header className="container mx-auto flex items-center justify-between px-4 py-3">
          <Link to="/">
            <CareCostLogo compact />
          </Link>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
            {api.mode === "mock" ? "Test data" : "Live data"}
          </span>
        </header>
        <div className="mx-auto max-w-xl px-4 pb-16 pt-6 sm:pt-12 space-y-6">
          <h1 className="text-2xl sm:text-4xl font-bold leading-tight">{t("start.title")}</h1>
          <div className="space-y-2">
            <label htmlFor="payment" className="block text-sm font-semibold">
              {t("start.payment")}
            </label>
            <PaymentSelect value={payment} onChange={setPayment} />
          </div>
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!canChat) return;
              setPhase("work");
              void sendChat(draft.trim());
              setDraft("");
            }}
          >
            <div className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-card">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={3}
                maxLength={1000}
                placeholder={t("start.chat_placeholder")}
                aria-label="Describe what's going on"
                className="flex-1 resize-none bg-transparent px-2 py-1 text-base outline-none"
                data-testid="start-chat"
              />
              <button type="submit" disabled={!canChat || !EMAIL_RE.test(email)} className="rounded-full bg-ink p-2.5 text-white disabled:opacity-40" aria-label="Send">
                <Send className="h-4 w-4" />
              </button>
            </div>
            <label className="block text-xs text-muted-foreground">
              {t("start.email")}
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="mt-1 w-full rounded-xl border border-border bg-card px-3 py-2 text-sm text-foreground"
                data-testid="email"
              />
            </label>
            {!payment && <p className="text-xs text-muted-foreground">Choose how you're paying first.</p>}
          </form>
          <button
            type="button"
            disabled={!payment}
            onClick={() => {
              setPhase("work");
              setOpen({ ai: false, browse: true, pick: true, list: false, receipt: false });
            }}
            className="w-full rounded-xl border-2 border-ink px-4 py-3 text-sm font-semibold text-ink disabled:opacity-40"
            data-testid="skip-ai"
          >
            {t("start.skip_ai")}
          </button>
          <p className="text-xs text-muted-foreground">{t("start.privacy")}</p>
        </div>
      </main>
    );
  }

  // Chips go in the chat when the AI helper is open and holds the card being priced; otherwise they sit above the map.
  const pathInChat =
    query?.care_path_id != null &&
    turns.some(
      (tn) =>
        tn.role === "assistant" &&
        (tn.res.reply.kind === "clarify" || tn.res.reply.kind === "care_paths") &&
        tn.res.reply.candidates.some((c) => c.path_id === query.care_path_id),
    );
  const chipsInChat = !!open.ai && !collapsed && pathInChat && choices.length > 0;
  // the map prices one item; with nothing picked, the first (ResultsPane does the same)
  const effStep = choices.find((c) => c.id === priceStep)?.id ?? choices[0]?.id ?? null;

  const pane = (v: ResultsView, extra: Partial<Parameters<typeof ResultsPane>[0]> = {}) => (
    <ResultsPane
      payment={payment}
      onPayment={changePayment}
      state={quoteState}
      view={v}
      onView={show}
      catalog={catalog}
      paths={paths}
      onBrowse={browsePick}
      location={location}
      onLocation={setLocation}
      pick={pick}
      onPick={setPick}
      loadSite={loadSite}
      orderBy={orderBy}
      onOrderBy={api.mode === "api" ? setOrderBy : undefined}
      step={priceStep}
      onStep={setPriceStep}
      chipsHere={!chipsInChat}
      chrome={false}
      kind={kindFilter}
      show={showFilter}
      {...extra}
    />
  );
  const quoteNow = shownQuote?.quote ?? null;
  const browseLabel = (() => {
    const v = browseValueOf(quoteNow, catalog);
    if (v.startsWith("path:")) return quoteNow?.care_path?.title ?? null;
    const svc = catalog?.services.find((x) => `svc:${x.service_id}` === v);
    return svc ? `${serviceCodes(svc).join(" / ")} · ${svc.plain_name}` : null;
  })();
  const selectedName = quoteNow?.sites.find((x) => x.site.site_id === pick.selected)?.site.name ?? null;

  const sections: Section[] = [
    {
      id: "ai",
      title: t("chat.helper"),
      icon: Bot,
      summary: turns.length ? `${turns.filter((x) => x.role === "user").length} question(s)` : null,
      content: (
        <div className="flex h-[26rem] flex-col gap-2">
          {!EMAIL_RE.test(email) && (
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("start.email")}
              aria-label={t("start.email")}
              className="w-full rounded-xl border border-border bg-card px-3 py-2 text-xs"
            />
          )}
          <ChatPane
            turns={turns}
            busy={chatBusy}
            error={chatError}
            answers={answers}
            actions={actions}
            activePathId={query?.care_path_id ?? null}
            stepChips={chipsInChat ? { choices, step: effStep, onStep: setPriceStep } : null}
          />
        </div>
      ),
    },
    {
      id: "browse",
      title: t("tab.browse"),
      icon: SlidersHorizontal,
      summary: browseLabel,
      content: (
        <BrowseBar
          catalog={catalog}
          paths={paths}
          value={browseValueOf(quoteNow, catalog)}
          onPick={browsePick}
          kind={kindFilter}
          onKind={setKindFilter}
          show={showFilter}
          onShow={setShowFilter}
        />
      ),
    },
    { id: "pick", title: t("tab.pick"), icon: MapPin, content: pane("pick") },
    { id: "list", title: t("tab.list"), icon: ListOrdered, content: pane("list") },
    { id: "receipt", title: t("tab.receipt"), icon: ReceiptIcon, summary: selectedName, content: pane("receipt") },
  ];

  return (
    <main className="min-h-screen bg-background" data-testid="workspace">
      <header className="sticky top-0 z-30 border-b border-border bg-card/90 backdrop-blur">
        <div className="flex h-11 items-center justify-between px-4">
          <Link to="/">
            <CareCostLogo compact />
          </Link>
          <div className="flex items-center gap-2 text-xs">
            <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">{api.mode === "mock" ? "Test data" : "Live data"}</span>
            <button type="button" onClick={resetAll} className="underline text-muted-foreground">
              Start over
            </button>
          </div>
        </div>
      </header>
      <Workspace
        head={
          <div className="flex flex-wrap items-center gap-2">
            <PaymentSelect
              id="payment-switch"
              value={payment}
              onChange={changePayment}
              className="min-w-0 flex-1 rounded-lg border border-border bg-card px-2 py-1.5 text-sm font-medium"
            />
            <LocationInput location={location} onLocation={setLocation} />
          </div>
        }
        sections={sections}
        open={open}
        onToggle={(id, o) => setOpen((x) => ({ ...x, [id]: o }))}
        collapsed={collapsed}
        onCollapsed={setCollapsed}
        focus={focus}
        map={pane("map", { mapClassName: "h-[55vh] md:h-[calc(100vh-8.5rem)]" })}
      />
    </main>
  );
}

const COLLAPSED_KEY = "carecost.chatCollapsed";
/** A per-viewer convenience: storage may be missing or throw (private window), so it never matters. */
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}
function writeCollapsed(v: boolean) {
  try {
    localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0");
  } catch {
    /* ignore */
  }
}
