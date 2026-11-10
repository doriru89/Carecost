import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { LocateFixed } from "lucide-react";
import type { Catalog, CatalogPath } from "@/generated/contracts/catalog";
import type { Payment, QuoteResponse, SiteQuote } from "@/generated/contracts/quote_api";
import { t } from "@/contracts/copy";
import { cn } from "@/lib/utils";
import { mapService } from "../lib/mapPrice";
import { paymentLabel } from "../lib/payments";
import { zipToLocation, type UserLocation } from "../lib/geo";
import { bostonNow } from "../lib/hours";
import { siteViews, sortSites, sortWithinKinds, sortWithinOptions, type SiteScope, type SortMode } from "../lib/sites";
import { stepLabels } from "../lib/steps";
import { byOption } from "../lib/headline";
import { onlyStepOf, priceChoices } from "../lib/priceChoices";
import { StepChips } from "./StepChips";
import { Overview, type OrderBy } from "./Overview";
import { BrowseBar } from "./BrowseBar";
import { browseValueOf, filterViews, pricedCount, type BrowseValue, type KindFilter, type ShowFilter } from "../lib/browse";
import { PaymentSelect } from "./PaymentSelect";
import { Receipt } from "./Receipt";
import { ScopeNote, SiteList } from "./SiteList";
// MapLibre is ~1 MB: loaded only when the Map tab opens
const SiteMap = lazy(() => import("./SiteMap").then((m) => ({ default: m.SiteMap })));

export interface QuoteOk {
  status: "ok";
  key: string;
  quote: QuoteResponse;
  scope: SiteScope;
}

export type QuoteState =
  | { status: "idle" }
  /** `prev`: the last receipt, kept on screen dimmed and labelled "updating" (R15), never as current */
  | { status: "loading"; key: string; prev?: QuoteOk }
  | QuoteOk
  | { status: "nomock" | "error"; key: string; message: string };

/** The person's sort and chosen site; owned by CareApp so it survives a remount of this pane. */
export interface SitePick {
  sort: SortMode;
  selected: string | null;
}

/** pick: the first screen (D-UI-1); receipt: the breakdown of one place (D-UI-2) */
export type ResultsView = "pick" | "receipt" | "list" | "map" | "browse";

export function ResultsPane({
  payment,
  onPayment,
  state,
  view,
  onView,
  catalog,
  paths,
  onBrowse,
  location,
  onLocation,
  pick,
  onPick,
  loadSite,
  orderBy = "distance",
  onOrderBy,
  step: stepProp,
  onStep: onStepProp,
  chipsHere = true,
  chrome = true,
  kind: kindProp,
  show: showProp,
  mapClassName,
}: {
  payment: Payment;
  onPayment: (p: Payment) => void;
  state: QuoteState;
  view: ResultsView;
  onView: (v: ResultsView) => void;
  catalog: Catalog | null;
  paths: CatalogPath[] | null;
  /** Browse: the person picked a service or a care path from the dropdown (the view stays Browse) */
  onBrowse: (v: BrowseValue) => void;
  location: UserLocation | null;
  onLocation: (l: UserLocation | null) => void;
  /** Kept by the parent: the Workspace shows several panes (sections + map) that share one pick. */
  pick: SitePick;
  onPick: (p: SitePick) => void;
  /**
   * C3 item 9: a no-location list carries full receipts for its first `full_receipts` sites only; any
   * other site's receipt is asked for by `site_ids` when the person opens it (same payment and query).
   */
  loadSite?: (siteId: string) => Promise<QuoteResponse>;
  /** C4b (D-UI-1): distance (default) or price; a change re-asks the server with `order_by` */
  orderBy?: OrderBy;
  onOrderBy?: (o: OrderBy) => void;
  /** The chosen price item (P3): owned by CareApp, so the chips can sit in the chat. */
  step?: string | null;
  onStep?: (id: string | null) => void;
  /** false: the chips are in the chat (next to the care path card), not above the map and list */
  chipsHere?: boolean;
  /**
   * false: inside a sidebar section or the main map (Workspace): no payment row, no tab bar, and the
   * loading state is one quiet line except on the map.
   */
  chrome?: boolean;
  /** The Browse filters, shared by the map and the List (owned by CareApp); standalone, "all" / "offered" */
  kind?: KindFilter;
  show?: ShowFilter;
  /** the map's height (the Workspace map fills the window) */
  mapClassName?: string;
}) {
  const { sort, selected } = pick;
  const setSort = (s: SortMode) => onPick({ ...pick, sort: s });
  const setSelected = (id: string | null) => onPick({ ...pick, selected: id });
  // R15: while a new quote loads, the last one may stay on screen, dimmed and labelled, never as current
  const shown = state.status === "ok" ? state : state.status === "loading" ? (state.prev ?? null) : null;
  const updating = state.status === "loading" && shown != null;
  const quote = shown?.quote ?? null;
  const scope = shown?.scope ?? null;
  const priced = useMemo(() => (quote ? mapService(quote, catalog) : null), [quote, catalog]);
  const now = useMemo(() => bostonNow(), [quote]); // eslint-disable-line react-hooks/exhaustive-deps
  const views = useMemo(() => (quote ? siteViews(quote.sites, location, now) : []), [quote, location, now]);
  const byKind = quote?.ordering === "kind_then_distance";
  const byOpt = quote ? byOption(quote) : false;
  const sorted = useMemo(
    () => (byOpt ? sortWithinOptions(views, sort) : byKind ? sortWithinKinds(views, sort) : sortSites(views, sort)),
    [views, sort, byKind, byOpt],
  );
  const current = views.find((v) => v.sq.site.site_id === selected) ?? sorted[0];
  const labels = useMemo(() => (quote ? stepLabels(quote) : {}), [quote]);

  // P3 / D-UI-3: the map prices one item at a time: an option's headline per site, or one step. A manual
  // pick of one service has one step: it is selected.
  const choices = useMemo(() => (quote ? priceChoices(quote) : []), [quote]);
  const shownKey = shown?.key ?? "";
  // controlled by CareApp (chips may sit in the chat); standalone, the pane keeps its own pick
  const [ownStep, setOwnStep] = useState<string | null>(null);
  useEffect(() => setOwnStep(null), [shownKey]);
  const controlled = onStepProp !== undefined;
  const pickedStep = controlled ? (stepProp ?? null) : ownStep;
  const onStep = controlled ? onStepProp : setOwnStep;
  const onlyStep = quote ? onlyStepOf(quote) : null;
  // Austin 2026-11-09: the map always prices something: with nothing picked, the first item (a care path's
  // whole visit, or the one service picked)
  const chosen = choices.find((c) => c.id === pickedStep) ?? (onlyStep ? choices.find((c) => c.id === onlyStep) : undefined) ?? choices[0] ?? null;
  const step = chosen?.id ?? null;
  const showChips = chipsHere && choices.length > (onlyStep ? 1 : 0);

  // Browse: the map prices something from the first screen (a care path: its whole-visit figure), never places only
  const [ownKind, setKindFilter] = useState<KindFilter>("all");
  const [ownShow, setShowFilter] = useState<ShowFilter>("offered");
  const kindFilter = kindProp ?? ownKind;
  const showFilter = showProp ?? ownShow;
  const [browseMode, setBrowseMode] = useState<"map" | "list">("map");
  const browseChosen = chosen;
  const browseItem = browseChosen?.item ?? null;
  const browseViews = useMemo(() => filterViews(sorted, browseItem, kindFilter, showFilter), [sorted, browseItem, kindFilter, showFilter]);
  const shownViews = browseViews;
  const browsePriced = useMemo(() => pricedCount(filterViews(sorted, browseItem, kindFilter, "offered"), browseItem), [sorted, browseItem, kindFilter]);

  // C3 item 9: fetch the opened site's receipt when the list carries only its summary
  const [fetched, setFetched] = useState<Record<string, { status: "loading" } | { status: "error" } | { status: "ok"; quote: QuoteResponse }>>({});
  useEffect(() => setFetched({}), [shownKey]);
  const needId = view === "receipt" && current && current.sq.receipt == null ? current.sq.site.site_id : null;
  const need = needId ? fetched[needId] : undefined;
  useEffect(() => {
    if (!needId || need || !loadSite) return;
    setFetched((f) => ({ ...f, [needId]: { status: "loading" } }));
    loadSite(needId).then(
      (q) => setFetched((f) => ({ ...f, [needId]: { status: "ok", quote: q } })),
      () => setFetched((f) => ({ ...f, [needId]: { status: "error" } })),
    );
  }, [needId, need, loadSite]);
  const receiptFor = (sq: SiteQuote): { quote: QuoteResponse; sq: SiteQuote } | "loading" | "error" | null => {
    if (!quote) return null;
    if (sq.receipt) return { quote, sq };
    const f = fetched[sq.site.site_id];
    if (!f || f.status === "loading") return "loading";
    if (f.status === "error") return "error";
    const got = f.quote.sites.find((x) => x.site.site_id === sq.site.site_id);
    if (!got?.receipt) return "error";
    // the site's own sources join the list's; the list's distance (from the person or City Hall) stays
    return { quote: { ...quote, sources: { ...quote.sources, ...f.quote.sources } }, sq: { ...got, distance_km: sq.distance_km } };
  };

  const open = (id: string) => {
    setSelected(id);
    onView("receipt");
  };

  return (
    <div className="space-y-3" data-testid="results-pane" data-quote-key={state.status === "ok" ? state.key : ""}>
      {chrome && (
      <>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="payment-switch" className="text-xs font-medium text-muted-foreground">
          Paying with
        </label>
        <PaymentSelect
          id="payment-switch"
          value={payment}
          onChange={onPayment}
          className="min-w-0 flex-1 rounded-lg border border-border bg-card px-2 py-1.5 text-sm font-medium"
        />
        <LocationInput location={location} onLocation={onLocation} />
      </div>

      <div className="flex gap-1 rounded-xl bg-muted p-1 text-sm" role="tablist">
        {(["pick", "receipt", "list", "map", "browse"] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => onView(v)}
            className={cn("flex-1 rounded-lg px-1.5 py-1.5 font-medium leading-tight", view === v ? "bg-card shadow-sm text-ink" : "text-muted-foreground")}
          >
            {t(`tab.${v}`)}
          </button>
        ))}
      </div>
      </>
      )}

      {view === "browse" ? (
        <div className="space-y-2" data-testid="browse">
          <BrowseBar
            catalog={catalog}
            paths={paths}
            value={browseValueOf(quote, catalog)}
            onPick={onBrowse}
            kind={kindFilter}
            onKind={setKindFilter}
            show={showFilter}
            onShow={setShowFilter}
            mode={browseMode}
            onMode={setBrowseMode}
          />
          {state.status === "loading" && !quote ? (
            <Pricing />
          ) : state.status === "nomock" || state.status === "error" ? (
            <QuoteUnavailable state={state} />
          ) : quote ? (
            <div className="relative space-y-2" data-testid="browse-body" aria-busy={updating || undefined}>
              {updating && <Pricing compact />}
              <div className={cn("space-y-2", updating && "pointer-events-none select-none opacity-40")}>
                {choices.length > 1 && (
                  <StepChips choices={choices} step={browseChosen?.id ?? null} onStep={(id) => onStep(id)} label={t("map.pick_step")} testId="browse-steps" />
                )}
                <p className="text-xs text-muted-foreground" data-testid="browse-count">
                  {t("browse.count", { shown: browseViews.length, total: sorted.length, priced: browsePriced })}
                  {scope?.kind === "near" ? ` · ${t("list.scope_near", { n: sorted.length, label: scope.label })}` : ""}
                </p>
                {browseViews.length === 0 ? (
                  <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{t("browse.none")}</p>
                ) : browseMode === "map" ? (
                  <Suspense fallback={<p className="p-6 text-center text-sm text-muted-foreground">Loading map…</p>}>
                    <SiteMap views={browseViews} selectedId={selected} onOpen={open} location={location} item={browseItem} />
                  </Suspense>
                ) : (
                  <SiteList
                    views={browseViews}
                    sort={sort}
                    onSort={setSort}
                    selectedId={selected}
                    onOpen={open}
                    hasLocation={!!location}
                    ordering={quote.ordering}
                    labels={labels}
                    options={quote.options}
                    item={browseItem?.kind === "step" ? browseItem : null}
                  />
                )}
              </div>
            </div>
          ) : null}
        </div>
      ) : state.status === "idle" ? (
        <p className={cn("rounded-xl border border-dashed border-border text-center text-sm text-muted-foreground", chrome || view === "map" ? "p-6" : "p-3")}>
          Describe what's going on in the chat, or pick a service under Browse, and prices show here.
        </p>
      ) : state.status === "loading" && !quote ? (
        chrome || view === "map" ? <Pricing /> : <p className="animate-pulse text-sm text-muted-foreground">Pricing…</p>
      ) : state.status === "nomock" || state.status === "error" ? (
        <QuoteUnavailable state={state} />
      ) : quote && current ? (
        <div className="relative space-y-2" data-testid="quote-body" data-updating={updating || undefined} aria-busy={updating || undefined}>
        {updating && (
          <p role="status" className="rounded-lg border border-ink/20 bg-card px-3 py-2 text-xs font-medium shadow-sm animate-pulse" data-testid="quote-updating">
            {t("quote.updating", { payment: paymentLabel(payment) })}
          </p>
        )}
        <div className={cn(updating && "pointer-events-none select-none opacity-40")}>
        {view === "pick" ? (
          <Overview
            quote={quote}
            views={views}
            scope={scope}
            orderBy={orderBy}
            onOrderBy={onOrderBy}
            onOpen={open}
            onSeeAll={() => onView("list")}
          />
        ) : view === "receipt" ? (
          <div className="space-y-2">
            {scope && <ScopeNote scope={scope} count={sorted.length} />}
            {sorted.length > 1 && (
              <div className="flex gap-1 overflow-x-auto pb-1 text-xs" aria-label="Pick a place">
                {sorted.map((v) => (
                  <button
                    key={v.sq.site.site_id}
                    type="button"
                    onClick={() => setSelected(v.sq.site.site_id)}
                    className={cn(
                      "shrink-0 rounded-full border px-2.5 py-1",
                      v === current ? "border-ink bg-ink text-white" : "border-border bg-card",
                    )}
                  >
                    {v.sq.site.name}
                  </button>
                ))}
              </div>
            )}
            {(() => {
              const r = receiptFor(current.sq);
              if (r === "error")
                return (
                  <p className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm" data-testid="receipt-load-failed">
                    {t("receipt.load_failed")}
                  </p>
                );
              if (r === "loading" || r == null)
                return <Receipt quote={quote} sq={current.sq} distance={current.distance} open={current.open} location={location} />;
              return <Receipt quote={r.quote} sq={r.sq} distance={current.distance} open={current.open} location={location} />;
            })()}
          </div>
        ) : view === "list" ? (
          <div className="space-y-2">
          {showChips && <StepChips choices={choices} step={step} onStep={onStep} testId="list-steps" />}
          <SiteList
            views={shownViews}
            sort={sort}
            onSort={setSort}
            selectedId={current.sq.site.site_id}
            onOpen={open}
            hasLocation={!!location}
            scope={scope}
            ordering={quote.ordering}
            labels={labels}
            options={quote.options}
            item={chosen?.item.kind === "step" ? chosen.item : null}
          />
          </div>
        ) : (
          <div className="space-y-2">
            {showChips && <StepChips choices={choices} step={step} onStep={onStep} label={t("map.pick_step")} />}
            <p className="text-xs text-muted-foreground" data-testid="map-price-note">
              {chosen
                ? chosen.item.kind === "headline"
                  ? t("map.headline_for", { option: chosen.label })
                  : t("map.step_price_for", { step: (onlyStep && priced ? priced.plain_name : labels[chosen.item.key]) ?? chosen.item.key })
                : chipsHere
                  ? t("map.places_only")
                  : t("map.places_only_chat")}
            </p>
            {shownViews.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{t("browse.none")}</p>
            ) : (
              <Suspense fallback={<p className="p-6 text-center text-sm text-muted-foreground">Loading map…</p>}>
                <SiteMap views={shownViews} selectedId={current.sq.site.site_id} onOpen={open} location={location} item={chosen?.item ?? null} className={mapClassName} />
              </Suspense>
            )}
          </div>
        )}
        </div>
        </div>
      ) : (
        <p className="p-6 text-center text-sm text-muted-foreground">No place in our data offers this yet.</p>
      )}
    </div>
  );
}

function QuoteUnavailable({ state }: { state: { status: "nomock" | "error"; message: string } }) {
  return (
    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm" data-testid="quote-unavailable">
      <p className="font-semibold">{state.status === "nomock" ? "No test data for this choice yet" : "Could not load prices"}</p>
      <p className="mt-1 text-muted-foreground">{state.message}</p>
    </div>
  );
}

/** "Pricing…"; past a few seconds it says the server is starting (Cloud Run scales to zero), so a cold start reads as one. */
function Pricing({ compact = false }: { compact?: boolean }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setSlow(true), WAKING_AFTER_MS);
    return () => clearTimeout(id);
  }, []);
  return (
    <div role="status" className={cn("text-center text-sm text-muted-foreground", compact ? "rounded-lg border border-ink/20 bg-card px-3 py-2 text-xs shadow-sm" : "p-6")} data-testid="pricing">
      <p className="animate-pulse">Pricing…</p>
      {slow && (
        <p className="mt-1 text-xs" data-testid="quote-waking">
          {t("quote.waking")}
        </p>
      )}
    </div>
  );
}

/** A warm server answers in under half a second; past this the wait is a cold start. */
export const WAKING_AFTER_MS = 3_000;

export function LocationInput({ location, onLocation }: { location: UserLocation | null; onLocation: (l: UserLocation | null) => void }) {
  // starts from the location the parent holds, so a remounted pane still shows the typed ZIP
  const [zip, setZip] = useState(location?.kind === "zip" ? location.label.replace(/^ZIP /, "") : "");
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex items-center gap-1">
      <input
        value={zip}
        onChange={(e) => {
          const v = e.target.value.replace(/\D/g, "").slice(0, 5);
          setZip(v);
          setErr(null);
          if (v.length === 5) {
            const loc = zipToLocation(v);
            if (loc) onLocation(loc);
            else setErr("ZIP not found in MA");
          }
        }}
        inputMode="numeric"
        placeholder={location?.kind === "device" ? "My location" : "ZIP"}
        aria-label="ZIP code for distance"
        className="w-20 rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
        data-testid="zip-input"
      />
      <button
        type="button"
        title="Use my location (sent rounded, to find places near you)"
        aria-label="Use my location"
        className="rounded-lg border border-border bg-card p-1.5"
        onClick={() =>
          navigator.geolocation?.getCurrentPosition(
            (p) => onLocation({ lat: p.coords.latitude, lon: p.coords.longitude, label: "My location", kind: "device" }),
            () => setErr("Location unavailable"),
            { maximumAge: 600_000, timeout: 10_000 },
          )
        }
      >
        <LocateFixed className="h-4 w-4" />
      </button>
      {err && <span className="text-[11px] text-warn">{err}</span>}
    </div>
  );
}
