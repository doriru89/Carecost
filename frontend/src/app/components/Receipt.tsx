import { t } from "@/contracts/copy";
import { NOTICE_KEY, YOU_PAY_KEY } from "@/contracts/exhaustive";
import type { QuoteResponse, SiteQuote } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { ExternalLink } from "lucide-react";
import { range } from "../lib/format";
import { milesText, type UserLocation } from "../lib/geo";
import type { OpenStatus } from "../lib/hours";
import { freshnessDetail, freshnessLabel, freshnessState, sections, siteSourceIds, sourceHover } from "../lib/receipt";
import { Booking } from "./Booking";
import { GLOSSARY_CREDIT } from "../lib/glossary";
import { ReceiptLineView } from "./ReceiptLineView";

function Total({ sq, where }: { sq: SiteQuote; where: "top" | "bottom" }) {
  const { totals } = sq.receipt;
  const l = totals.likely;
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-x-3 gap-y-1", where === "top" ? "py-3" : "pt-3 border-t-2 border-foreground/80")}>
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("receipt.total")}</p>
        {!totals.complete && <p className="text-[11px] text-warn">{t("receipt.total_floor")}</p>}
        <div className="flex flex-wrap gap-1 mt-0.5">
          {l?.includes_estimate && <Flag>{t("receipt.includes_estimate")}</Flag>}
          {l?.includes_late_source && <Flag>{t("receipt.includes_late")}</Flag>}
          {l?.includes_stale_source && <Flag>{t("receipt.includes_stale")}</Flag>}
        </div>
      </div>
      <p className={cn("ml-auto whitespace-nowrap tabular-nums font-bold text-ink", where === "top" ? "text-2xl sm:text-3xl" : "text-xl")} data-testid={`total-${where}`}>
        {l ? `${totals.complete ? "" : "≥ "}${range(l.low, l.high)}` : "—"}
      </p>
    </div>
  );
}

function Flag({ children }: { children: React.ReactNode }) {
  return <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-900">{children}</span>;
}

export function Receipt({
  quote,
  sq,
  distance,
  open,
  location,
}: {
  quote: QuoteResponse;
  sq: SiteQuote;
  distance: number | null;
  open: OpenStatus;
  location: UserLocation | null;
}) {
  const { site, receipt } = sq;
  const excluded = new Map(receipt.totals.excluded.map((e) => [e.line_id, e]));
  const op = new Map(sq.other_payers.map((r) => [r.line_id, r]));
  const yp = receipt.totals.you_pay;
  const usedSources = siteSourceIds(sq).flatMap((id) => (quote.sources[id] ? [[id, quote.sources[id]] as const] : []));
  return (
    <article className="rounded-2xl border border-border bg-card shadow-card p-4 sm:p-5" data-testid="receipt">
      <header className="space-y-0.5">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">Receipt estimate</p>
        <h2 className="text-lg font-bold leading-tight">{site.name}</h2>
        <p className="text-xs text-muted-foreground">
          {site.address_line}
          {distance != null && <> · {milesText(distance)}</>} · {open.text}
        </p>
        <p className="text-xs">{t(`billing.${site.billing_type}`)}</p>
        {site.price_source_id == null && (
          <p className="text-[11px] text-warn" data-testid="price-source-not-read">
            {t("receipt.price_source_not_read")}
          </p>
        )}
      </header>

      {quote.notices.length > 0 && (
        <ul className="mt-2 space-y-1">
          {quote.notices.map((n) => (
            <li key={n} className="rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">
              {t(NOTICE_KEY[n])}
            </li>
          ))}
        </ul>
      )}

      <Total sq={sq} where="top" />

      <div className="space-y-4">
        {sections(receipt.lines).map((s) => (
          <section key={s.tier} data-testid={`section-${s.tier}`}>
            <h3
              className={cn(
                "mb-1.5 text-[11px] font-semibold uppercase tracking-wider",
                s.tier === "certain" && "text-ink",
                s.tier === "likely" && "text-ink/70",
                s.tier === "possible" && "text-muted-foreground",
                s.tier === "not_in_public_data" && "text-warn",
              )}
            >
              {t(`tier.${s.tier}`)}
            </h3>
            <div className="space-y-2">
              {s.lines.map((line) => (
                <ReceiptLineView
                  key={line.line_id}
                  line={line}
                  sources={quote.sources}
                  payment={quote.payment}
                  excluded={excluded.get(line.line_id)}
                  otherPayers={op.get(line.line_id)}
                  location={location}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="mt-5">
        <Total sq={sq} where="bottom" />
      </div>

      <div className="mt-3 rounded-lg bg-muted/60 p-3 text-xs space-y-1.5" data-testid="you-pay">
        <p>
          <span className="font-semibold">You pay: </span>
          {t(YOU_PAY_KEY[yp.kind])}
        </p>
        {yp.portal_url && (
          <a href={yp.portal_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium underline">
            {yp.portal_label ?? "Check my plan"} <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      {quote.copy_keys.length > 0 && (
        // D33: a quote reached from a care path carries both fixed lines; a manual pick carries none
        <div className="mt-3 rounded-lg border border-border p-3 text-xs space-y-1.5" data-testid="d33-lines">
          <p className="font-semibold">{t("receipt.d33_heading")}</p>
          {quote.copy_keys.map((k) => (
            <p key={k} data-testid={`d33-${k}`}>
              {t(k)}
            </p>
          ))}
        </div>
      )}

      <div className="mt-3">
        <Booking site={site} />
      </div>

      <details className="mt-4 text-xs" data-testid="sources-dates">
        <summary className="cursor-pointer font-semibold">{t("receipt.sources")}</summary>
        <ul className="mt-2 space-y-2">
          {usedSources.map(([id, info]) => {
            const st = freshnessState(info);
            return (
              <li key={id}>
                <p>
                  <span className={cn("mr-1 rounded px-1 py-0.5 text-[10px] font-semibold",
                    st === "current" && "bg-emerald-50 text-emerald-800",
                    st === "late" && "bg-amber-100 text-amber-900",
                    st === "stale" && "bg-sky-100 text-sky-900")}>{freshnessLabel(st)}</span>
                  {sourceHover(info, id)}
                </p>
                <p className="text-muted-foreground">{freshnessDetail(info)}</p>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-muted-foreground">
          Data build {quote.data_version.build_id} · prices as of {quote.as_of}
          {quote.data_version.tic_release ? ` · insurer files ${quote.data_version.tic_release}` : ""}
        </p>
        <p className="mt-1 text-muted-foreground">{GLOSSARY_CREDIT}</p>
      </details>
    </article>
  );
}
