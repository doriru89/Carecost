import { t } from "@/contracts/copy";
import { NOTICE_KEY, YOU_PAY_KEY } from "@/contracts/exhaustive";
import type { QuoteResponse, ReceiptLine, SiteQuote, StepSummary, Totals } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { ExternalLink } from "lucide-react";
import { isoDate, range } from "../lib/format";
import { milesText, type UserLocation } from "../lib/geo";
import type { OpenStatus } from "../lib/hours";
import { dataNoticeKey, freshnessDetail, freshnessLabel, freshnessState, sections, siteSourceIds, sourceHover } from "../lib/receipt";
import { Booking } from "./Booking";
import { GLOSSARY_CREDIT } from "../lib/glossary";
import { ReceiptLineView } from "./ReceiptLineView";
import { elsewhereSteps, stepLabels } from "../lib/steps";
import { ChildrenOnlyBadge } from "./SiteList";

function Total({ totals, where, labels }: { totals: Totals; where: "top" | "bottom"; labels: Record<string, string> }) {
  const l = totals.likely;
  const might = totals.might_add;
  return (
    <div className={cn("py-3", where === "bottom" && "pt-3 pb-0 border-t-2 border-foreground/80")}>
      <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
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
      {might && where === "top" && (
        // P9: possible steps (the doctor may decide against them) are never in the headline
        <p className="mt-1 text-xs text-muted-foreground" data-testid="might-add">
          <span className="font-semibold text-foreground">{t("receipt.might_add", { range: range(might.low, might.high) })}</span>{" "}
          {t("receipt.might_add_detail", { steps: might.step_keys.map((k) => labels[k] ?? k).join(", ") })}
        </p>
      )}
    </div>
  );
}

const LIKELIHOOD_LABEL: Record<StepSummary["likelihood"], string> = {
  certain: "Happens at this visit",
  likely: "Likely",
  possible: "Possible",
  rare: "Rare",
};

/**
 * P4: a step this place does not do (or does not say it does) is its own line, priced at the places that
 * do it ("Elsewhere, about $X–$Y", p25–p75 of the same payer). Never in this place's total. The step's
 * own lines (what the files say here) are folded away under it.
 */
function ElsewhereStep({
  step,
  label,
  lines,
  render,
}: {
  step: StepSummary;
  label: string;
  lines: ReceiptLine[];
  render: (l: ReceiptLine) => React.ReactNode;
}) {
  const e = step.elsewhere;
  return (
    <div className="rounded-md border border-dashed border-border px-3 py-2.5" data-testid="elsewhere-step" data-step={step.key}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-[11rem] flex-1">
          <p className="text-sm font-medium leading-snug">{label}</p>
          <p className="text-[11px] text-muted-foreground">{LIKELIHOOD_LABEL[step.likelihood]}</p>
        </div>
        <p className="ml-auto text-right text-sm font-medium tabular-nums text-foreground/80" data-testid="elsewhere-about">
          {e ? t("receipt.elsewhere_about", { range: range(e.low, e.high) }) : "—"}
        </p>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {e ? t("receipt.elsewhere_basis", { n: e.n_groups }) : t("receipt.elsewhere_none")}
      </p>
      {lines.length > 0 && (
        <details className="mt-1.5 text-xs">
          <summary className="cursor-pointer text-[11px] text-muted-foreground">What the files say about this place</summary>
          <div className="mt-1.5 space-y-2">{lines.map(render)}</div>
        </details>
      )}
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
  const labels = stepLabels({ ...quote, sites: [sq, ...quote.sites] });
  if (!receipt) {
    // C3 item 9: past the first full_receipts sites the receipt is fetched by site_ids (ResultsPane)
    return (
      <article className="rounded-2xl border border-border bg-card shadow-card p-4 sm:p-5" data-testid="receipt-pending">
        <h2 className="text-lg font-bold leading-tight">{site.name}</h2>
        <p className="mt-2 text-sm text-muted-foreground animate-pulse">{t("receipt.loading")}</p>
      </article>
    );
  }
  const excluded = new Map(receipt.totals.excluded.map((e) => [e.line_id, e]));
  const op = new Map(sq.other_payers.map((r) => [r.line_id, r]));
  const yp = receipt.totals.you_pay;
  const usedSources = siteSourceIds(sq).flatMap((id) => (quote.sources[id] ? [[id, quote.sources[id]] as const] : []));
  // P4: the steps this place does not do get their own lines; their receipt lines fold under them
  const away = elsewhereSteps(sq);
  const awayIds = new Set(away.flatMap((st) => st.line_ids));
  const byId = new Map(receipt.lines.map((l) => [l.line_id, l]));
  const ownLines = receipt.lines.filter((l) => !awayIds.has(l.line_id));
  const render = (line: ReceiptLine) => (
    <ReceiptLineView
      key={line.line_id}
      line={line}
      sources={quote.sources}
      payment={quote.payment}
      excluded={excluded.get(line.line_id)}
      otherPayers={op.get(line.line_id)}
      location={location}
      site={site}
    />
  );
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
        {site.children_only && (
          <p>
            <ChildrenOnlyBadge />
          </p>
        )}
        {site.data_notices.length > 0 && (
          <ul className="space-y-1 pt-1">
            {site.data_notices.map((n) => (
              <li key={n.id} className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px]" data-testid="data-notice">
                <p className="font-medium text-amber-900">{t(dataNoticeKey(n.kind))}</p>
                <details className="text-muted-foreground">
                  <summary className="cursor-pointer">{t("data_notice.details", { date: isoDate(n.observed) })}</summary>
                  <p className="mt-1">{n.detail}</p>
                  {n.effect && <p className="mt-1">{n.effect}</p>}
                </details>
              </li>
            ))}
          </ul>
        )}
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

      <Total totals={receipt.totals} where="top" labels={labels} />

      <div className="space-y-4">
        {sections(ownLines).map((s) => (
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
            <div className="space-y-2">{s.lines.map(render)}</div>
          </section>
        ))}
        {away.length > 0 && (
          <section data-testid="section-elsewhere">
            <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{t("receipt.elsewhere_section")}</h3>
            <div className="space-y-2">
              {away.map((st) => (
                <ElsewhereStep
                  key={st.key}
                  step={st}
                  label={labels[st.key] ?? st.key}
                  lines={st.line_ids.flatMap((id) => (byId.has(id) ? [byId.get(id)!] : []))}
                  render={render}
                />
              ))}
            </div>
          </section>
        )}
      </div>

      <div className="mt-5">
        <Total totals={receipt.totals} where="bottom" labels={labels} />
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
