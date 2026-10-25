import { t } from "@/contracts/copy";
import { cn } from "@/lib/utils";
import { milesText } from "../lib/geo";
import { dataNoticeKey, totalText } from "../lib/receipt";
import type { SiteScope, SiteView, SortMode } from "../lib/sites";
import { Booking } from "./Booking";

const BILLING_TAG: Record<string, string> = {
  office_visit: "Office visit billing",
  hospital_outpatient: "Hospital billing + facility fee",
  asc: "Surgery center",
  unknown: "Billing not confirmed",
};

/** Says which sites the response holds: nearest to the person's point, or the best value overall (C2). */
export function ScopeNote({ scope, count }: { scope: SiteScope; count: number }) {
  const text =
    scope.kind === "near"
      ? t("list.scope_near", { n: count, label: scope.label })
      : scope.kind === "overall"
        ? t("list.scope_overall", { n: count })
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

export function SiteCard({ v, selected, onOpen }: { v: SiteView; selected?: boolean; onOpen: () => void }) {
  const { site, receipt } = v.sq;
  const total = totalText(v.sq);
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-3 shadow-sm transition-colors",
        selected ? "border-ink ring-1 ring-ink/30" : "border-border",
      )}
      data-testid="site-card"
    >
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-semibold leading-tight">{site.name}</p>
            <p className="text-xs text-muted-foreground">
              {v.distance != null ? `${milesText(v.distance)} · ` : ""}
              <span className={v.open.openNow ? "text-emerald-700 font-medium" : ""}>{v.open.text}</span>
            </p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-lg font-bold tabular-nums text-ink">
              {total ? `${receipt.totals.complete ? "" : "≥ "}${total}` : "—"}
            </p>
            {receipt.totals.missing > 0 && (
              <p className="text-[11px] text-warn">{receipt.totals.missing} likely {receipt.totals.missing === 1 ? "item" : "items"} without a price</p>
            )}
          </div>
        </div>
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
}: {
  views: SiteView[];
  sort: SortMode;
  onSort: (s: SortMode) => void;
  selectedId: string | null;
  onOpen: (siteId: string) => void;
  hasLocation: boolean;
  scope?: SiteScope | null;
}) {
  const opts: { id: SortMode; label: string }[] = [
    { id: "price", label: "Price" },
    { id: "nearest", label: "Nearest" },
    { id: "open_today", label: "Open today" },
  ];
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
      {views.map((v) => (
        <SiteCard key={v.sq.site.site_id} v={v} selected={v.sq.site.site_id === selectedId} onOpen={() => onOpen(v.sq.site.site_id)} />
      ))}
      <p className="text-[11px] text-muted-foreground">{t("start.privacy")}</p>
    </div>
  );
}
