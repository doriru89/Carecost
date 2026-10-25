import { t } from "@/contracts/copy";
import { GAP_COPY_KEY, assertNever } from "@/contracts/exhaustive";
import type { Cell, Money, QuoteResponse } from "@/generated/contracts/quote_api";
import { AlertTriangle } from "lucide-react";
import { range } from "../lib/format";
import { SourceChip } from "./SourceChip";

export function MoneyWithChip({
  m,
  sources,
  strong,
}: {
  m: Money;
  sources: QuoteResponse["sources"];
  strong?: boolean;
}) {
  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <span className={strong ? "font-semibold tabular-nums" : "tabular-nums"} data-testid="line-amount">
        {range(m.low, m.high)}
      </span>
      <SourceChip
        sourceId={m.prov.source_id}
        info={sources[m.prov.source_id]}
        rowRef={m.prov.row_ref}
      />
    </span>
  );
}

/**
 * Money | Gap: the only way a price cell is rendered (plan §2.5). The switch fails to compile when a
 * kind is added to the contract.
 */
export function CellView({
  cell,
  sources,
  strong,
}: {
  cell: Cell;
  sources: QuoteResponse["sources"];
  strong?: boolean;
}) {
  switch (cell.kind) {
    case "money":
      return <MoneyWithChip m={cell} sources={sources} strong={strong} />;
    case "conflict":
      return (
        <div className="text-right space-y-1">
          <p className="text-xs text-warn font-medium">{t(GAP_COPY_KEY.conflict)}</p>
          <MoneyWithChip m={cell.a} sources={sources} />
          <MoneyWithChip m={cell.b} sources={sources} />
        </div>
      );
    case "percent_only":
      return (
        <div className="text-right">
          <p className="text-sm font-medium text-warn">
            {cell.pct}% of {cell.of}
          </p>
          <p className="text-[11px] text-muted-foreground">{t(GAP_COPY_KEY.percent_only)}</p>
          <SourceChip sourceId={cell.searched.source_id} info={sources[cell.searched.source_id]} />
        </div>
      );
    case "not_published":
    case "not_loaded":
    case "no_source":
      return (
        <span className="inline-flex items-center gap-1 text-sm font-medium text-warn" data-testid="gap-label">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
          {t(`gap.label.${cell.kind}`)}
        </span>
      );
    default:
      return assertNever(cell);
  }
}

/** The Gap's explanation and what to ask (each Gap row says what to ask, §4.2). */
export function GapDetail({ cell, sources }: { cell: Cell; sources: QuoteResponse["sources"] }) {
  if (cell.kind === "not_published" || cell.kind === "no_source") {
    return (
      <div className="mt-1.5 text-xs space-y-0.5">
        <p className="text-muted-foreground">
          {t(GAP_COPY_KEY[cell.kind])}</p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground/80">Missing:</span> {cell.what}
        </p>
        <p className="text-foreground">
          <span className="font-semibold">{t("receipt.ask")}:</span> “{cell.ask}”
        </p>
        {cell.kind === "not_published" && (
          <p className="text-muted-foreground">
            We searched: <SourceChip sourceId={cell.searched.source_id} info={sources[cell.searched.source_id]} />
          </p>
        )}
      </div>
    );
  }
  if (cell.kind === "not_loaded") {
    return (
      <div className="mt-1.5 text-xs space-y-0.5">
        <p className="text-muted-foreground">
          {t(GAP_COPY_KEY.not_loaded)}</p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground/80">Missing:</span> {cell.what}
          {cell.eta ? ` Expected: ${cell.eta}.` : ""}
        </p>
        <p className="text-foreground">
          <span className="font-semibold">{t("receipt.ask")}:</span> “{t("receipt.ask_not_loaded")}”
        </p>
      </div>
    );
  }
  return null;
}
