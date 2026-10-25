import { t } from "@/contracts/copy";
import { SOURCE_CHIP_KEY } from "@/contracts/exhaustive";
import type { SourceInfo } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { freshnessDetail, freshnessLabel, freshnessState, sourceHover } from "../lib/receipt";
import { InfoTip } from "./InfoTip";

/**
 * A number's chip IS its provenance: derived from prov.source_id -> response.sources (P2).
 * Shows the §2.2 sentence on hover, plus the two freshness sides, never merged (D18).
 */
export function SourceChip({
  sourceId,
  info,
  rowRef,
  file,
}: {
  sourceId: string;
  info: SourceInfo | undefined;
  rowRef?: string;
  file?: string;
}) {
  const state = freshnessState(info);
  return (
    <InfoTip
      label={`Source: ${sourceId}`}
      trigger={
        <span
          data-testid="source-chip"
          className={cn(
            "whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
            state === "current" && "border-border bg-muted text-muted-foreground",
            state === "late" && "border-amber-300 bg-amber-50 text-amber-800",
            state === "stale" && "border-sky-300 bg-sky-50 text-sky-800",
          )}
        >
          {info ? t(SOURCE_CHIP_KEY[info.source_kind]) : sourceId}
          {state !== "current" && <> · {freshnessLabel(state)}</>}
        </span>
      }
    >
      <p className="font-medium text-foreground">{sourceHover(info, sourceId)}</p>
      {info && <p className="mt-1 text-muted-foreground">{freshnessDetail(info)}</p>}
      {(rowRef || file) && (
        <p className="mt-1 font-mono text-[10px] text-muted-foreground break-all">
          {rowRef ?? file}
        </p>
      )}
    </InfoTip>
  );
}
