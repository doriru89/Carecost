import { t } from "@/contracts/copy";
import { COMPONENT_LABEL_KEY, EXCLUDED_REASON_KEY, TIER_BASIS_KEY } from "@/contracts/exhaustive";
import type { ExcludedLine, OtherPayerRange, Payment, QuoteResponse, ReceiptLine } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { range } from "../lib/format";
import { miles, milesText, type UserLocation } from "../lib/geo";
import { noCashDiscount } from "../lib/receipt";
import { CellView, GapDetail } from "./CellView";
import { DoctorFeeNote } from "./DoctorFeeNote";
import { GlossaryChips } from "./Glossary";
import { OtherPayers } from "./OtherPayers";
import { SourceChip } from "./SourceChip";

const TIER_CLASS: Record<ReceiptLine["tier"], string> = {
  certain: "tier-certain",
  likely: "tier-likely",
  possible: "tier-possible",
  not_in_public_data: "tier-gap",
};

/** Visual weight per tier (D8): name and amount get lighter as the line gets less certain. */
const NAME_CLASS: Record<ReceiptLine["tier"], string> = {
  certain: "text-foreground font-semibold",
  likely: "text-foreground/85 font-medium",
  possible: "text-muted-foreground font-medium",
  not_in_public_data: "text-foreground font-medium",
};

export function ReceiptLineView({
  line,
  sources,
  payment,
  excluded,
  otherPayers,
  location,
}: {
  line: ReceiptLine;
  sources: QuoteResponse["sources"];
  payment: Payment;
  excluded?: ExcludedLine;
  otherPayers?: OtherPayerRange;
  location: UserLocation | null;
}) {
  const body = (
    <div className={cn("pl-3 pr-2 py-2.5 rounded-r-md", TIER_CLASS[line.tier])} data-testid="receipt-line" data-tier={line.tier}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-[11rem] flex-1">
          <p className={cn("text-sm leading-snug", NAME_CLASS[line.tier])}>{line.plain_name}</p>
          <p className="text-[11px] text-muted-foreground">
            {line.technical_name}
            {line.codes.length > 0 && <> · {line.codes.join(", ")}{line.modifier ? `-${line.modifier}` : ""}</>}
            {!line.component_confirmed && <> · {t(COMPONENT_LABEL_KEY.unknown)}</>}
          </p>
        </div>
        <div className="ml-auto shrink-0 text-right">
          {line.cell ? (
            <CellView cell={line.cell} sources={sources} strong={line.tier === "certain"} />
          ) : (
            <span className="text-sm text-muted-foreground">{t("receipt.not_offered")}</span>
          )}
          {line.unit !== "once" && (
            <p className="text-[11px] text-muted-foreground">
              {t(line.unit === "per_15_minutes" ? "receipt.per_15_minutes" : "receipt.per_visit")}
            </p>
          )}
        </div>
      </div>

      {line.why && <p className="mt-1 text-xs text-muted-foreground"><span className="font-medium text-foreground/80">Why:</span> {line.why}</p>}

      {line.cell && <GapDetail cell={line.cell} sources={sources} />}

      {line.availability === "not_offered" && line.elsewhere.length > 0 && (
        <Elsewhere line={line} sources={sources} location={location} />
      )}

      {line.doctor_fee && <DoctorFeeNote fee={line.doctor_fee} sources={sources} />}

      {line.list_price && (
        <p className="mt-1 text-[11px] text-muted-foreground flex flex-wrap items-center gap-1">
          {t("receipt.list_price")}: <span className="tabular-nums">{range(line.list_price.low, line.list_price.high)}</span>
          <SourceChip sourceId={line.list_price.prov.source_id} info={sources[line.list_price.prov.source_id]} rowRef={line.list_price.prov.row_ref} />
        </p>
      )}
      {noCashDiscount(line, payment) && (
        <p className="mt-0.5 text-[11px] font-medium text-warn" data-testid="no-cash-discount">{t("receipt.no_cash_discount")}</p>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        <span>{t(TIER_BASIS_KEY[line.tier_basis])}</span>
        {line.tier === "not_in_public_data" && line.likelihood !== "possible" && line.likelihood !== "rare" && (
          <span>· usually happens ({line.likelihood})</span>
        )}
        {excluded && line.tier !== "possible" && line.tier !== "not_in_public_data" && (
          <span>· {t(EXCLUDED_REASON_KEY[excluded.reason])}</span>
        )}
        <GlossaryChips keys={line.glossary_keys} />
        {line.learn_more.map((l) => (
          <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="underline">
            {l.label} ↗
          </a>
        ))}
      </div>

      {otherPayers && <OtherPayers range={otherPayers} payment={payment} sources={sources} />}
    </div>
  );

  if (!line.ai_suggested) return body;
  return (
    <div className="rounded-md border-2 border-dashed border-primary/60 p-1" data-testid="ai-suggested">
      <p className="px-2 pt-1 text-[11px] font-medium text-ink">{t("receipt.ai_suggested")}</p>
      {body}
    </div>
  );
}

function Elsewhere({
  line,
  sources,
  location,
}: {
  line: ReceiptLine;
  sources: QuoteResponse["sources"];
  location: UserLocation | null;
}) {
  const opts = [...line.elsewhere].sort((a, b) =>
    location ? miles(location, a) - miles(location, b) : 0,
  );
  return (
    <div className="mt-1.5 text-xs">
      <p className="font-medium">{t("receipt.cheapest_elsewhere")}:</p>
      <ul className="space-y-0.5">
        {opts.slice(0, 3).map((o) => (
          <li key={o.site_id} className="flex justify-between gap-2">
            <span>
              {o.site_name}
              {location ? ` · ${milesText(miles(location, o))}` : ""}
            </span>
            <CellView cell={o.cell} sources={sources} />
          </li>
        ))}
      </ul>
    </div>
  );
}
