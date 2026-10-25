import PriceRangeBar from "@/components/PriceRangeBar";
import type { OtherPayerRange, Payment, QuoteResponse } from "@/generated/contracts/quote_api";
import { t } from "@/contracts/copy";
import { range } from "../lib/format";
import { InfoTip } from "./InfoTip";
import { MoneyWithChip } from "./CellView";

/**
 * Range bar for the same item at the same site across every payer the engine found, plus self-pay, and a
 * popup listing each point with its chip (§4.2, v2; reuses PriceRangeBar.tsx).
 * Which lines of business belong on it (P1 problem 18) is the engine's call: we show every point it
 * sends and mark the person's own payer.
 */
export function OtherPayers({
  range: r,
  payment,
  sources,
}: {
  range: OtherPayerRange;
  payment: Payment;
  sources: QuoteResponse["sources"];
}) {
  const values = r.points.flatMap((p) => [p.money.low, p.money.high]);
  if (r.cash?.kind === "money") values.push(r.cash.low, r.cash.high);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const mine =
    payment.kind === "insurance"
      ? r.points.find((p) => p.payer_id === payment.payer_id && (!p.product || p.product === payment.product))
      : undefined;
  return (
    <div className="mt-2 rounded-lg border border-dashed border-border p-2" data-testid="other-payers">
      <InfoTip
        className="w-full block"
        label="Compare other ways of paying"
        trigger={
          <div className="w-full">
            <PriceRangeBar
              label={`${t("receipt.other_payers")} (${r.points.length} plans${r.cash ? ` + ${t("payment.self_pay")}` : ""})`}
              min={min}
              max={max}
              scaleMin={min}
              scaleMax={max}
              highlight={mine ? { value: mine.money.low, label: "Your plan" } : undefined}
            />
          </div>
        }
      >
        <p className="font-semibold text-foreground mb-1">Code {r.code} at this site</p>
        <ul className="space-y-1 max-h-64 overflow-auto">
          {r.points.map((p, i) => (
            <li key={i} className="flex items-start justify-between gap-2">
              <span className={p === mine ? "font-semibold" : ""}>
                {p.label}
                {p.product ? ` · ${p.product}` : ""}
                {p === mine ? " (yours)" : ""}
              </span>
              <MoneyWithChip m={p.money} sources={sources} />
            </li>
          ))}
          {r.cash && (
            <li className="flex items-start justify-between gap-2 border-t pt-1">
              <span>{t("payment.self_pay")}</span>
              {r.cash.kind === "money" ? <MoneyWithChip m={r.cash} sources={sources} /> : <span>{r.cash.kind}</span>}
            </li>
          )}
        </ul>
        <p className="mt-1 text-muted-foreground">Range {range(min, max)}</p>
      </InfoTip>
    </div>
  );
}
