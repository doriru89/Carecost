/**
 * D-UI-1 / D-UI-3 (Austin 2026-10-25): the first screen. Per entry option (A: urgent care / walk-in,
 * B: a specialist such as a skin doctor): its label and range, a clearly marked "cheapest place for this"
 * (the engine's cheapest_site_id, with honest cheapest_basis words) and 2–3 alternates. Sorted by distance
 * by default; the switch to price re-asks the server with `order_by: "price"`. The ER reference sits under
 * it, collapsed and never ranked. Tap a place to see every bill (the breakdown).
 */
import { t } from "@/contracts/copy";
import { KIND_LABEL_KEY, NOTICE_KEY } from "@/contracts/exhaustive";
import type { QuoteOption, QuoteResponse, SiteQuote } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { milesText } from "../lib/geo";
import { cheapestText, optionGroups, optionLetter, optionRangeCount, optionRangeText, partialMoreText, type OptionGroup } from "../lib/headline";
import { hoursSourceKey } from "../lib/hours";
import { totalText } from "../lib/receipt";
import type { SiteScope, SiteView } from "../lib/sites";
import { ErReferenceView, HeadlineFigure, MayAlsoOrderList } from "./Headline";
import { ScopeNote } from "./SiteList";

export type OrderBy = "distance" | "price";

function where(v: SiteView | undefined): string {
  if (!v) return "";
  if (v.distance != null) return milesText(v.distance);
  if (v.cityHallMiles != null) return t("list.from_city_hall", { distance: milesText(v.cityHallMiles) });
  return "";
}

function PickCard({
  sq,
  v,
  cheapest,
  option,
  onOpen,
  payment,
}: {
  payment: QuoteResponse["payment"];
  sq: SiteQuote;
  v: SiteView | undefined;
  cheapest?: boolean;
  option: QuoteOption | null;
  onOpen: () => void;
}) {
  const hr = sq.headline_range;
  const loc = where(v);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "w-full rounded-xl border bg-card p-3 text-left shadow-sm transition-colors hover:border-ink/60",
        cheapest ? "border-2 border-emerald-600" : "border-border",
      )}
      data-testid={cheapest ? "pick-cheapest" : "pick-alternate"}
      data-site-id={sq.site.site_id}
    >
      {cheapest && (
        <p className="mb-1 flex flex-wrap items-center gap-x-2 text-[11px]">
          <span className="rounded-full bg-emerald-600 px-2 py-0.5 font-semibold text-white" data-testid="cheapest-badge">
            {t("option.cheapest")}
          </span>
          <span className="font-medium text-emerald-800" data-testid="cheapest-basis">
            {cheapestText(option?.cheapest_basis ?? null)}
          </span>
        </p>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-[10rem] flex-1">
          <p className="font-semibold leading-tight">{sq.site.name}</p>
          <p className="text-[11px] text-muted-foreground">
            {t(KIND_LABEL_KEY[sq.site.kind])}
            {loc ? ` · ${loc}` : ""}
          </p>
          {v && (
            <p className="text-[11px]" data-testid="pick-hours" data-hours-field={sq.site.hours_label}>
              <span className={v.open.openNow ? "font-medium text-emerald-700" : "text-muted-foreground"}>
                {v.open.known ? v.open.text : t("hours.unknown")}
              </span>
              {v.open.known && <span className="text-muted-foreground"> · {t(hoursSourceKey(sq.site.hours_label))}</span>}
            </p>
          )}
        </div>
        <div className="ml-auto max-w-[16rem] text-right">
          {hr ? (
            <HeadlineFigure hr={hr} steps={sq.steps} />
          ) : totalText(sq) ? (
            // a quote without a headline range (a manual pick): this place's own bills, added up
            <p className="text-lg font-bold tabular-nums text-ink" data-testid="pick-total">
              {sq.headline.complete ? "" : "≥ "}
              {totalText(sq)}
            </p>
          ) : (
            <p className="text-[11px] text-muted-foreground" data-testid="pick-no-price">
              {t("list.no_total")}
            </p>
          )}
        </div>
      </div>
      {cheapest && hr && <MayAlsoOrderList hr={hr} payment={payment} compact />}
    </button>
  );
}

function OptionBlock({
  quote,
  g,
  views,
  onOpen,
  onSeeAll,
}: {
  quote: QuoteResponse;
  g: OptionGroup;
  views: Map<string, SiteView>;
  onOpen: (siteId: string) => void;
  onSeeAll: () => void;
}) {
  const o = g.option;
  const letter = o ? optionLetter(quote, o.id) : null;
  const referral = o?.specialist && quote.notices.includes("hmo_referral_for_specialist");
  const rangeText = o ? optionRangeText(o) : null;
  // C4c: a path without entry options has one implicit option: no "Option A" label, just its range and cheapest
  const labelled = !!o && !o.implicit;
  const more = o ? partialMoreText(o) : null;
  return (
    <section className="space-y-2 rounded-2xl border border-border bg-background p-3" data-testid="option-block" data-option={o?.id ?? "all"}>
      <header>
        {labelled ? (
          <h3 className="text-sm font-bold" data-testid="option-label">
            {t("option.label", { letter: letter ?? "", label: o!.label.en })}
          </h3>
        ) : (
          <h3 className="text-sm font-bold">{t("overview.no_options")}</h3>
        )}
        {o && o.priced && (
          <p className="text-xs text-muted-foreground" data-testid="option-range">
            {rangeText ? t("option.range", { range: rangeText, n: optionRangeCount(o) }) : t("option.no_range")}
          </p>
        )}
        {more && (
          <p className="text-[11px] text-muted-foreground" data-testid="option-partial-more">
            {more}
          </p>
        )}
      </header>
      {referral && (
        <p className="rounded-md border border-sky-300 bg-sky-50 px-2 py-1.5 text-xs font-medium text-sky-950" data-testid="hmo-referral-notice">
          {t(NOTICE_KEY.hmo_referral_for_specialist)}
        </p>
      )}
      {o && !o.priced ? (
        <div className="rounded-xl border border-dashed border-border p-3 text-sm" data-testid="option-unpriced">
          <p className="font-medium">{t("option.unpriced")}</p>
          {o.missing_reason && <p className="mt-0.5 text-xs text-muted-foreground">{o.missing_reason}</p>}
        </div>
      ) : (
        <>
          {o && !g.cheapest && o.cheapest_site_id && (
            <p className="text-[11px] text-muted-foreground">{t("option.cheapest_not_here")}</p>
          )}
          {g.cheapest && (
            <PickCard sq={g.cheapest} v={views.get(g.cheapest.site.site_id)} cheapest option={o} payment={quote.payment} onOpen={() => onOpen(g.cheapest!.site.site_id)} />
          )}
          {g.alternates.length > 0 && (
            <div className="space-y-1.5">
              {g.cheapest && <p className="pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{t("option.alternates")}</p>}
              {g.alternates.map((sq) => (
                <PickCard key={sq.site.site_id} sq={sq} v={views.get(sq.site.site_id)} option={o} payment={quote.payment} onOpen={() => onOpen(sq.site.site_id)} />
              ))}
            </div>
          )}
          {g.sites.length > g.alternates.length + (g.cheapest ? 1 : 0) && (
            <button type="button" onClick={onSeeAll} className="text-xs font-medium underline" data-testid="see-all">
              {t("option.see_all", { n: g.sites.length })}
            </button>
          )}
        </>
      )}
    </section>
  );
}

export function Overview({
  quote,
  views,
  scope,
  orderBy,
  onOrderBy,
  onOpen,
  onSeeAll,
}: {
  quote: QuoteResponse;
  views: SiteView[];
  scope: SiteScope | null;
  orderBy: OrderBy;
  /** absent in mock mode or for a quote without options: no switch */
  onOrderBy?: (o: OrderBy) => void;
  onOpen: (siteId: string) => void;
  onSeeAll: () => void;
}) {
  const byId = new Map(views.map((v) => [v.sq.site.site_id, v]));
  const groups = optionGroups(quote);
  return (
    <div className="space-y-3" data-testid="overview" data-ordering={quote.ordering}>
      <div>
        <h2 className="text-base font-bold">{t("overview.title")}</h2>
        <p className="text-xs text-muted-foreground">{t("overview.lead")}</p>
        {scope && <ScopeNote scope={scope} count={quote.sites.length} />}
      </div>
      {quote.options.some((o) => !o.implicit) && onOrderBy && (
        <div className="flex flex-wrap items-center gap-1 text-xs" role="radiogroup" aria-label={t("order.label")} data-testid="order-by">
          <span className="mr-1 text-muted-foreground">{t("order.label")}</span>
          {(["distance", "price"] as const).map((o) => (
            <button
              key={o}
              type="button"
              role="radio"
              aria-checked={orderBy === o}
              onClick={() => onOrderBy(o)}
              className={cn("rounded-full border px-2.5 py-1", orderBy === o ? "border-ink bg-ink text-white" : "border-border bg-card")}
            >
              {t(o === "distance" ? "order.distance" : "order.price")}
            </button>
          ))}
          {orderBy === "price" && <span className="basis-full text-[11px] text-muted-foreground">{t("order.price_note")}</span>}
        </div>
      )}
      {groups.map((g) => (
        <OptionBlock key={g.option?.id ?? "all"} quote={quote} g={g} views={byId} onOpen={onOpen} onSeeAll={onSeeAll} />
      ))}
      <ErReferenceView er={quote.er_reference} />
    </div>
  );
}
