/**
 * C4b / D6 building blocks a person reads first: the headline range, what it covers, the possible extras,
 * the ER for comparison, and the three questions to ask when calling. Every number is a contract number.
 */
import { ChevronDown } from "lucide-react";
import { t } from "@/contracts/copy";
import { ER_SHOWN } from "@/contracts/exhaustive";
import type { ErReference, HeadlineRange, Payment, QuoteResponse, StepSummary, Subtotal } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { range } from "../lib/format";
import { basisText, fromNoteFor, fromText, headlineText, includesText, mayAlsoFigure, mayAlsoGroups, plainList, stepFootnote } from "../lib/headline";
import { paymentLabel } from "../lib/payments";

/**
 * The headline: `low–high` of the certain + likely steps, one plain line saying what it covers, its basis
 * ("includes an estimate" / "only partial prices found here"), and the likely steps with no price at all.
 */
export function HeadlineFigure({ hr, steps, size = "card" }: { hr: HeadlineRange; steps?: StepSummary[]; size?: "card" | "big" }) {
  const basis = basisText(hr);
  const notPriced = hr.with_likely.not_priced;
  return (
    <div data-testid="headline-range" data-basis={hr.basis} data-from-only={hr.from_only || undefined}>
      <p
        className={cn("font-bold tabular-nums text-ink leading-tight", size === "big" ? "text-2xl sm:text-3xl" : "text-lg")}
        data-testid="headline-figure"
      >
        {headlineText(hr)}
      </p>
      <p className="text-xs text-foreground/80" data-testid="headline-includes">
        {includesText(hr, steps)}
      </p>
      {basis && (
        <p className={cn("text-[11px] font-medium", hr.basis === "partial" ? "text-warn" : "text-amber-900")} data-testid="headline-basis">
          {basis}
        </p>
      )}
      {notPriced.length > 0 && (
        <p className="text-[11px] text-warn" data-testid="headline-not-priced">
          {t("headline.not_priced", { items: plainList(notPriced) })}
        </p>
      )}
    </div>
  );
}

/** Possible steps, listed on their own with their purpose and figure. Never in the headline. */
export function MayAlsoOrderList({ hr, payment, compact = false }: { hr: HeadlineRange; payment: Payment; compact?: boolean }) {
  const groups = mayAlsoGroups(hr.may_also_order);
  if (groups.length === 0) return null;
  return (
    <div className={cn("text-xs", compact ? "mt-1.5" : "mt-3 rounded-lg border border-border p-3")} data-testid="may-also-order">
      <p className={cn("font-semibold", compact ? "text-[11px] text-muted-foreground" : "")}>{t("may_also.heading")}</p>
      <ul className="mt-1 space-y-1">
        {groups.map((g) => (
          <li key={g.group ?? g.items[0].step_key} data-testid={g.group ? "may-also-group" : "may-also-item"} data-group={g.group ?? undefined}>
            {g.group && <p className="text-[11px] text-muted-foreground">{t("may_also.one_of")}</p>}
            <ul className={cn(g.group && "border-l-2 border-dashed border-border pl-2 space-y-0.5")}>
              {g.items.map((m) => (
                <li key={m.step_key} className="flex flex-wrap justify-between gap-x-2" data-testid="may-also-step" data-step={m.step_key} data-figure={m.figure}>
                  <span className="min-w-0">
                    <span className="font-medium text-foreground/90">{m.plain_name}</span>
                    {!compact && m.why && <span className="block text-[11px] text-muted-foreground">{m.why}</span>}
                  </span>
                  <span className="ml-auto tabular-nums text-foreground/80">{mayAlsoFigure(m, payment)}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SubtotalRow({
  label,
  sub,
  steps,
  strong,
  payment,
}: {
  label: string;
  sub: Subtotal;
  steps: Map<string, StepSummary>;
  strong?: boolean;
  payment: Payment;
}) {
  return (
    <li className={cn("rounded-md px-2 py-1.5", strong ? "bg-muted" : "")} data-testid="subtotal">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className={cn("text-xs", strong ? "font-semibold" : "text-foreground/85")}>{label}</span>
        <span className={cn("ml-auto tabular-nums", strong ? "font-bold text-ink" : "font-medium")} data-testid="subtotal-amount">
          {range(sub.low, sub.high, false)}
        </span>
      </div>
      {sub.step_keys.length > 0 && (
        <ul className="mt-0.5 space-y-0.5 text-[11px] text-muted-foreground">
          {sub.step_keys.map((k, i) => {
            const st = steps.get(k);
            return (
              <li key={k} className="flex flex-wrap justify-between gap-x-2" data-testid="subtotal-step" data-step={k}>
                <span>+ {sub.includes[i] ?? st?.plain_name ?? k}</span>
                <span className="ml-auto">
                  {st && st.low != null && st.high != null
                    ? st.from_only
                      ? fromText(st.low, fromNoteFor(payment))
                      : `${range(st.low, st.high, false)} · ${stepFootnote(st).text}`
                    : st
                      ? stepFootnote(st).text
                      : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {sub.not_priced.length > 0 && (
        <p className="mt-0.5 text-[11px] text-warn" data-testid="subtotal-not-priced">
          {t("breakdown.not_priced", { items: sub.not_priced.join(", ") })}
        </p>
      )}
      {sub.alternatives.length > 0 && (
        <p className="mt-0.5 text-[11px] text-muted-foreground" data-testid="subtotal-alternatives">
          {t("breakdown.alternatives", { items: sub.alternatives.join(", ") })}
        </p>
      )}
    </li>
  );
}

/** D-UI-2: the three subtotals, so a person sees how the range was built. with_likely = the headline. */
export function RangeBuild({ hr, steps, payment, flags }: { hr: HeadlineRange; steps: StepSummary[]; payment: Payment; flags?: React.ReactNode }) {
  const byKey = new Map(steps.map((s) => [s.key, s]));
  return (
    <section className="mt-3 rounded-lg border border-border p-3" data-testid="range-build">
      <h3 className="text-xs font-semibold">{t("breakdown.heading")}</h3>
      <ul className="mt-1.5 space-y-1">
        <SubtotalRow label={t("breakdown.visit_only")} sub={hr.visit_only} steps={byKey} payment={payment} />
        <SubtotalRow label={t("breakdown.with_likely")} sub={hr.with_likely} steps={byKey} strong payment={payment} />
        <SubtotalRow label={t("breakdown.with_possible")} sub={hr.with_possible} steps={byKey} payment={payment} />
      </ul>
      {flags}
    </section>
  );
}

/** Cheap win: three fixed questions to ask when calling (same for every place). */
export function CallQuestions({ payment }: { payment: Payment }) {
  return (
    <div className="mt-3 rounded-lg border border-border bg-card p-3 text-xs" data-testid="call-questions">
      <p className="font-semibold">{t("call.heading")}</p>
      <ol className="mt-1 list-decimal space-y-0.5 pl-4">
        <li>{t("call.q_self_pay")}</li>
        <li>{t("call.q_doctor")}</li>
        <li>{payment.kind === "cash" ? t("call.q_plan_none") : t("call.q_plan", { plan: paymentLabel(payment) })}</li>
      </ol>
    </div>
  );
}

const ER_LEVEL = (code: string) => (code.startsWith("9928") ? code.slice(-1) : code);

/**
 * C4b item 7: the ER for comparison. Small, collapsed, never ranked, never in the list or on the map.
 * `not_loaded` = not shown at all.
 */
export function ErReferenceView({ er }: { er: QuoteResponse["er_reference"] }) {
  if (!er || !ER_SHOWN[er.status]) return null;
  return (
    <details className="rounded-lg border border-border bg-muted/40 p-3 text-xs" data-testid="er-reference" data-status={er.status}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 font-semibold">
        <span>{t("er.summary")}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </summary>
      <div className="mt-2 space-y-1.5">
        {er.status === "priced" && er.low != null && er.high != null ? (
          <p data-testid="er-range">{t("er.range", { range: range(er.low, er.high, false) })}</p>
        ) : (
          <p data-testid="er-range">{t("er.not_published")}</p>
        )}
        <p className="text-muted-foreground">{t(er.note_key)}</p>
        {er.status === "priced" && !er.includes_doctor && <p className="text-warn" data-testid="er-hospital-only">{t("er.hospital_part_only")}</p>}
        <ErHospitals er={er} />
        <p className="text-[11px] text-muted-foreground">{t("er.never_ranked")}</p>
      </div>
    </details>
  );
}

function cellAmount(c: ErReference["hospitals"][number]["levels"][number]["facility"]): string {
  return c.kind === "money" ? range(c.low, c.high) : "—";
}

function ErHospitals({ er }: { er: ErReference }) {
  if (er.hospitals.length === 0) return null;
  return (
    <ul className="space-y-1.5" data-testid="er-hospitals">
      {er.hospitals.map((h) => (
        <li key={h.site_id} data-testid="er-hospital">
          <p className="font-medium">
            {h.name} <span className="font-normal text-muted-foreground">· {(h.distance_km / 1.609344).toFixed(1)} mi</span>
          </p>
          <ul className="text-[11px] text-muted-foreground">
            {h.levels.map((l) => (
              <li key={l.code} className="flex flex-wrap justify-between gap-x-2 tabular-nums">
                <span>{t("er.level", { n: ER_LEVEL(l.code) })}</span>
                <span>
                  {t("er.hospital_part")} {cellAmount(l.facility)} · {t("er.doctor_part")} {cellAmount(l.doctor)}
                </span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
