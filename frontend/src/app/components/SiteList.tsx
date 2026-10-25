import { t } from "@/contracts/copy";
import { KIND_LABEL_KEY, ORDERING_BY_OPTION } from "@/contracts/exhaustive";
import type { QuoteOption, QuoteResponse } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { range } from "../lib/format";
import { milesText } from "../lib/geo";
import { dataNoticeKey, totalText } from "../lib/receipt";
import { kindGroups, optionRuns, type SiteScope, type SiteView, type SortMode } from "../lib/sites";
import { HeadlineFigure } from "./Headline";
import { elsewhereSteps, isExpected } from "../lib/steps";
import { Booking } from "./Booking";

const BILLING_TAG: Record<string, string> = {
  office_visit: "Office visit billing",
  hospital_outpatient: "Hospital billing: a hospital bill + the doctor's",
  asc: "Surgery center",
  unknown: "Billing not confirmed",
};

/** Says which sites the response holds: nearest to the person's point, or every place by kind (P7). */
export function ScopeNote({ scope, count }: { scope: SiteScope; count: number }) {
  const text =
    scope.kind === "near"
      ? t("list.scope_near", { n: count, label: scope.label })
      : scope.kind === "all"
        ? t("list.scope_all", { n: count })
        : t("list.scope_fixture", { n: count });
  return (
    <p className="text-[11px] text-muted-foreground" data-testid="site-scope" data-scope={scope.kind}>
      {text}
    </p>
  );
}

/** D27: a pediatric-only site. The server quotes one only when the request names it. */
export function ChildrenOnlyBadge() {
  return (
    <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-900" data-testid="children-only">
      {t("site.children_only")}
    </span>
  );
}

export function SiteCard({
  v,
  selected,
  onOpen,
  labels = {},
}: {
  v: SiteView;
  selected?: boolean;
  onOpen: () => void;
  /** step key -> readable name (lib/steps.ts stepLabels) */
  labels?: Record<string, string>;
}) {
  const { site, headline } = v.sq;
  const hr = v.sq.headline_range;
  const total = totalText(v.sq);
  // P4: expected steps this place does not do, each with the range at places that do (never summed here)
  const away = elsewhereSteps(v.sq).filter((st) => isExpected(st) && st.elsewhere);
  const where =
    v.distance != null ? `${milesText(v.distance)} · ` : v.cityHallMiles != null ? `${t("list.from_city_hall", { distance: milesText(v.cityHallMiles) })} · ` : "";
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-3 shadow-sm transition-colors",
        selected ? "border-ink ring-1 ring-ink/30" : "border-border",
      )}
      data-testid="site-card"
      data-site-id={site.site_id}
    >
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-semibold leading-tight">{site.name}</p>
            <p className="text-xs text-muted-foreground">
              {where}
              <span className={v.open.openNow ? "text-emerald-700 font-medium" : ""}>{v.open.text}</span>
            </p>
          </div>
          {hr ? (
            // C4b: the same headline as the first screen (certain + likely; possible steps are in the breakdown)
            <div className="ml-auto max-w-[16rem] shrink-0 text-right">
              <HeadlineFigure hr={hr} steps={v.sq.steps} />
            </div>
          ) : (
          <div className="text-right shrink-0">
            <p className="text-lg font-bold tabular-nums text-ink" data-testid="card-total">
              {total ? `${headline.complete ? "" : "≥ "}${total}` : "—"}
            </p>
            {!total && (
              <p className="max-w-[10rem] text-[11px] text-muted-foreground" data-testid="card-no-total">
                {t("list.no_total")}
              </p>
            )}
            {headline.includes_estimate && (
              <p className="text-[11px] font-medium text-amber-900" data-testid="card-estimate">
                {t("receipt.includes_estimate")}
              </p>
            )}
            {headline.missing > 0 && (
              <p className="text-[11px] text-warn">{headline.missing} likely {headline.missing === 1 ? "step" : "steps"} without a price</p>
            )}
          </div>
          )}
        </div>
        {!hr && (away.length > 0 || headline.might_add) && (
          <div className="mt-1 space-y-0.5 text-[11px] text-muted-foreground">
            {away.map((st) => (
              <p key={st.key} data-testid="card-elsewhere">
                + {t("list.done_elsewhere", { step: labels[st.key] ?? st.key, range: range(st.elsewhere!.low, st.elsewhere!.high, false) })}
              </p>
            ))}
            {headline.might_add && (
              <p data-testid="card-might-add">{t("receipt.might_add", { range: range(headline.might_add.low, headline.might_add.high, false) })}</p>
            )}
          </div>
        )}
        <div className="mt-1.5 flex flex-wrap gap-1 text-[11px]">
          <span className="rounded-full bg-muted px-2 py-0.5">{BILLING_TAG[site.billing_type]}</span>
          {site.booking.some((b) => b.kind === "walk_in") && (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-800">Walk-in today</span>
          )}
          {site.hours_label === "may_close_early" && <span className="rounded-full bg-amber-50 px-2 py-0.5">May close early</span>}
          {site.children_only && <ChildrenOnlyBadge />}
        </div>
        {site.data_notices.map((n) => (
          <p key={n.id} className="mt-1 text-[11px] text-warn" data-testid="data-notice">
            {t(dataNoticeKey(n.kind))}
          </p>
        ))}
      </button>
      <div className="mt-2">
        <Booking site={site} compact />
      </div>
    </div>
  );
}

export function SiteList({
  views,
  sort,
  onSort,
  selectedId,
  onOpen,
  hasLocation,
  scope,
  ordering = "rank",
  labels,
  options = [],
}: {
  views: SiteView[];
  sort: SortMode;
  onSort: (s: SortMode) => void;
  selectedId: string | null;
  onOpen: (siteId: string) => void;
  hasLocation: boolean;
  scope?: SiteScope | null;
  /** P7: kind_then_distance = grouped by kind under headers; C4b option_then_* = grouped by entry option */
  ordering?: QuoteResponse["ordering"];
  labels?: Record<string, string>;
  options?: QuoteOption[];
}) {
  const byKind = ordering === "kind_then_distance";
  const byOption = ORDERING_BY_OPTION[ordering];
  const opts: { id: SortMode; label: string }[] = [
    // with no location the server's order is kind then distance from City Hall, never a price ranking
    { id: "price", label: byKind || ordering === "option_then_distance" ? "By distance" : ordering === "option_then_price" ? "Cheapest first" : "Price" },
    { id: "nearest", label: "Nearest" },
    { id: "open_today", label: "Open today" },
  ];
  const card = (v: SiteView) => (
    <SiteCard key={v.sq.site.site_id} v={v} labels={labels} selected={v.sq.site.site_id === selectedId} onOpen={() => onOpen(v.sq.site.site_id)} />
  );
  return (
    <div className="space-y-2" data-testid="site-list">
      {scope && <ScopeNote scope={scope} count={views.length} />}
      <div className="flex items-center gap-1 text-xs" role="radiogroup" aria-label="Sort by">
        <span className="text-muted-foreground mr-1">Sort:</span>
        {opts.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={sort === o.id}
            onClick={() => onSort(o.id)}
            className={cn(
              "rounded-full border px-2.5 py-1",
              sort === o.id ? "border-ink bg-ink text-white" : "border-border bg-card",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
      {sort === "nearest" && !hasLocation && (
        <p className="text-[11px] text-muted-foreground">Add a ZIP or use your location to sort by distance.</p>
      )}
      {byOption
        ? optionRuns(views).map((g, i) => {
            const o = options.find((x) => x.id === g.optionId);
            const letter = o ? String.fromCharCode(65 + options.indexOf(o)) : null;
            return (
              <section key={`${g.optionId}-${i}`} className="space-y-2" data-testid="option-group" data-option={g.optionId ?? ""}>
                <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-ink">
                  {o ? t("option.label", { letter: letter ?? "", label: o.label.en }) : ""}{" "}
                  <span className="font-normal text-muted-foreground">· {g.views.length}</span>
                </h3>
                {g.views.map(card)}
              </section>
            );
          })
        : byKind
        ? kindGroups(views).map((g) => (
            <section key={g.kind} className="space-y-2" data-testid="kind-group" data-kind={g.kind}>
              <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-ink">
                {t(KIND_LABEL_KEY[g.kind])} <span className="font-normal text-muted-foreground">· {g.views.length}</span>
              </h3>
              {g.views.map(card)}
            </section>
          ))
        : views.map(card)}
      <p className="text-[11px] text-muted-foreground">{t("start.privacy")}</p>
    </div>
  );
}
