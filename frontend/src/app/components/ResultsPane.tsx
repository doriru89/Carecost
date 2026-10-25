import { lazy, Suspense, useMemo, useState } from "react";
import { LocateFixed } from "lucide-react";
import type { Catalog, CatalogService } from "@/generated/contracts/catalog";
import type { Payment, QuoteResponse } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { zipToLocation, type UserLocation } from "../lib/geo";
import { bostonNow } from "../lib/hours";
import { siteViews, sortSites, type SortMode } from "../lib/sites";
import { BrowsePicker } from "./BrowsePicker";
import { PaymentSelect } from "./PaymentSelect";
import { Receipt } from "./Receipt";
import { SiteList } from "./SiteList";
// MapLibre is ~1 MB: loaded only when the Map tab opens
const SiteMap = lazy(() => import("./SiteMap").then((m) => ({ default: m.SiteMap })));

export type QuoteState =
  | { status: "idle" }
  | { status: "loading"; key: string }
  | { status: "ok"; key: string; quote: QuoteResponse }
  | { status: "nomock" | "error"; key: string; message: string };

export type ResultsView = "receipt" | "list" | "map" | "browse";

export function ResultsPane({
  payment,
  onPayment,
  state,
  view,
  onView,
  catalog,
  onPickPath,
  onPickService,
  location,
  onLocation,
}: {
  payment: Payment;
  onPayment: (p: Payment) => void;
  state: QuoteState;
  view: ResultsView;
  onView: (v: ResultsView) => void;
  catalog: Catalog | null;
  onPickPath: (id: string) => void;
  onPickService: (s: CatalogService) => void;
  location: UserLocation | null;
  onLocation: (l: UserLocation | null) => void;
}) {
  const [sort, setSort] = useState<SortMode>("price");
  const [selected, setSelected] = useState<string | null>(null);
  const quote = state.status === "ok" ? state.quote : null;
  const now = useMemo(() => bostonNow(), [quote]); // eslint-disable-line react-hooks/exhaustive-deps
  const views = useMemo(() => (quote ? siteViews(quote.sites, location, now) : []), [quote, location, now]);
  const sorted = useMemo(() => sortSites(views, sort), [views, sort]);
  const current = views.find((v) => v.sq.site.site_id === selected) ?? sorted[0];

  const open = (id: string) => {
    setSelected(id);
    onView("receipt");
  };

  return (
    <div className="space-y-3" data-testid="results-pane" data-quote-key={state.status === "ok" ? state.key : ""}>
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
        {(["receipt", "list", "map", "browse"] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => onView(v)}
            className={cn("flex-1 rounded-lg px-2 py-1.5 font-medium", view === v ? "bg-card shadow-sm text-ink" : "text-muted-foreground")}
          >
            {v === "receipt" ? "Receipt" : v === "list" ? "List" : v === "map" ? "Map" : "Browse"}
          </button>
        ))}
      </div>

      {view === "browse" ? (
        <BrowsePicker catalog={catalog} onPickPath={onPickPath} onPickService={onPickService} />
      ) : state.status === "idle" ? (
        <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Describe what's going on in the chat, or pick a problem under Browse, and prices show here.
        </p>
      ) : state.status === "loading" && !quote ? (
        <p className="p-6 text-center text-sm text-muted-foreground animate-pulse">Pricing…</p>
      ) : state.status === "nomock" || state.status === "error" ? (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm" data-testid="quote-unavailable">
          <p className="font-semibold">{state.status === "nomock" ? "No test data for this choice yet" : "Could not load prices"}</p>
          <p className="mt-1 text-muted-foreground">{state.message}</p>
        </div>
      ) : quote && current ? (
        view === "receipt" ? (
          <div className="space-y-2">
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
            <Receipt quote={quote} sq={current.sq} distance={current.distance} open={current.open} location={location} />
          </div>
        ) : view === "list" ? (
          <SiteList views={sorted} sort={sort} onSort={setSort} selectedId={current.sq.site.site_id} onOpen={open} hasLocation={!!location} />
        ) : (
          <Suspense fallback={<p className="p-6 text-center text-sm text-muted-foreground">Loading map…</p>}>
            <SiteMap views={sorted} selectedId={current.sq.site.site_id} onOpen={open} location={location} />
          </Suspense>
        )
      ) : (
        <p className="p-6 text-center text-sm text-muted-foreground">No place in our data offers this yet.</p>
      )}
    </div>
  );
}

function LocationInput({ location, onLocation }: { location: UserLocation | null; onLocation: (l: UserLocation | null) => void }) {
  const [zip, setZip] = useState("");
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
        title="Use my location (stays in this browser)"
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
