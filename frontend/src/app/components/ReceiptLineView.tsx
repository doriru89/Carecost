import { t } from "@/contracts/copy";
import { COMPONENT_LABEL_KEY, EXCLUDED_REASON_KEY, TIER_BASIS_KEY } from "@/contracts/exhaustive";
import type { ExcludedLine, OtherPayerRange, Payment, PeerRange, QuoteResponse, ReceiptLine, SiteSummary } from "@/generated/contracts/quote_api";
import { cn } from "@/lib/utils";
import { range } from "../lib/format";
import { miles, milesText, type UserLocation } from "../lib/geo";
import { cellHasDollars, chainName, noCashDiscount, priceHidden } from "../lib/receipt";
import { CellView, GapDetail, MoneyChips } from "./CellView";
import { DoctorFeeNote } from "./DoctorFeeNote";
import { GlossaryChips } from "./Glossary";
import { OtherPayers } from "./OtherPayers";

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
  site,
}: {
  line: ReceiptLine;
  sources: QuoteResponse["sources"];
  payment: Payment;
  excluded?: ExcludedLine;
  otherPayers?: OtherPayerRange;
  location: UserLocation | null;
  /** the site the receipt is for (P9 facility-fee note, R12 chain line) */
  site?: SiteSummary;
}) {
  // Rung 6 (plan §2.4, D5): an estimate, in the total but marked. Rung 7: Medicare as a reference, never summed.
  const estimate = line.cell?.kind === "money" && line.cell.basis === "estimate";
  const reference = excluded?.reason === "reference_only" || line.doctor_fee?.explanation_key === "fee.rung_7_medicare_reference";
  // P2 / P6 / P8: a number that must not read as this place's price is folded away, labelled (lib/receipt.ts)
  const hidden = priceHidden(line, payment);
  const body = (
    <div className={cn("pl-3 pr-2 py-2.5 rounded-r-md", TIER_CLASS[line.tier])} data-testid="receipt-line" data-tier={line.tier}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-[11rem] flex-1">
          <p className={cn("text-sm leading-snug", NAME_CLASS[line.tier])}>{line.plain_name}</p>
          {line.availability === "unknown" && (
            // C2: no positive evidence either way. Not "offered", and never "not offered".
            <p
              className="mt-0.5 inline-block rounded border border-dashed border-muted-foreground/60 px-1.5 py-0.5 text-[11px] text-muted-foreground"
              data-testid="availability-unknown"
            >
              {t("receipt.availability_unknown")}
            </p>
          )}
          {line.availability !== "offered" && line.availability_reason && (
            <p className="mt-0.5 text-[11px] text-foreground/80" data-testid="availability-why">
              {t(`receipt.availability.${line.availability_reason}`)}
            </p>
          )}
          {line.at === "your_primary_care" && (
            <p className="mt-0.5 text-[11px] font-medium text-ink" data-testid="at-primary-care">
              {t("receipt.at_your_primary_care")}
            </p>
          )}
          <p className="text-[11px] text-muted-foreground">
            {line.technical_name}
            {line.codes.length > 0 && <> · {line.codes.join(", ")}{line.modifier ? `-${line.modifier}` : ""}</>}
            {!line.component_confirmed && <> · {t(COMPONENT_LABEL_KEY.unknown)}</>}
          </p>
        </div>
        <div className={cn("ml-auto max-w-full shrink-0 text-right sm:max-w-[18rem]", reference && "opacity-70")}>
          {hidden ? (
            <HiddenPrice line={line} sources={sources} hidden={hidden} />
          ) : (
            <>
              {(estimate || reference) && (
                <p
                  className={cn(
                    "mb-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold",
                    estimate ? "bg-amber-100 text-amber-900" : "bg-muted text-muted-foreground",
                  )}
                  data-testid={estimate ? "estimate-tag" : "reference-tag"}
                >
                  {t(estimate ? "receipt.estimate_tag" : "receipt.reference_tag")}
                </p>
              )}
              {line.cell ? (
                <CellView cell={line.cell} sources={sources} strong={line.tier === "certain" && !reference} />
              ) : (
                <span className="text-sm text-muted-foreground">{t("receipt.not_offered")}</span>
              )}
            </>
          )}
          {line.price_notes.map((k) => (
            <p key={k} className="text-[11px] text-muted-foreground" data-testid="price-note" data-note={k}>
              {t(k)}
            </p>
          ))}
          {line.unit !== "once" && (
            <p className="text-[11px] text-muted-foreground">
              {t(line.unit === "per_15_minutes" ? "receipt.per_15_minutes" : "receipt.per_visit")}
            </p>
          )}
        </div>
      </div>

      {line.estimate && !hidden && <EstimateBasis peer={line.estimate} />}
      {line.unusual && !line.unusual.whole_line && line.unusual.set_aside.length > 0 && (
        <p className="mt-1 text-[11px] text-warn" data-testid="unusual-set-aside">
          {t("receipt.unusual_set_aside", { n: line.unusual.set_aside.length, prices: line.unusual.set_aside.length === 1 ? "price" : "prices" })}
        </p>
      )}
      {line.anesthesia_time && (
        <p className="mt-1 text-[11px] text-muted-foreground" data-testid="anesthesia-time">
          {t("receipt.anesthesia_time", { minutes: line.anesthesia_time.minutes, range: range(line.anesthesia_time.low, line.anesthesia_time.high) })}
        </p>
      )}
      {line.chain_price_from && (
        <p className="mt-1 text-[11px] text-muted-foreground" data-testid="chain-price">
          {t("receipt.chain_price", { chain: chainName(site?.chain_id ?? null) })}
        </p>
      )}
      {site?.billing_type === "unknown" && line.component === "facility" && !cellHasDollars(line) && (
        <p className="mt-1 text-[11px] font-medium text-warn" data-testid="facility-fee-possible">
          {t("receipt.facility_fee_possible")}
        </p>
      )}

      {line.why && <p className="mt-1 text-xs text-muted-foreground"><span className="font-medium text-foreground/80">Why:</span> {line.why}</p>}

      {line.cell && <GapDetail cell={line.cell} sources={sources} />}

      {line.availability === "not_offered" && line.elsewhere.length > 0 && (
        <Elsewhere line={line} sources={sources} location={location} />
      )}

      {line.doctor_fee && <DoctorFeeNote fee={line.doctor_fee} sources={sources} />}

      {line.list_price && (
        <p className="mt-1 text-[11px] text-muted-foreground flex flex-wrap items-center gap-1">
          {t("receipt.list_price")}: <span className="tabular-nums">{range(line.list_price.low, line.list_price.high)}</span>
          <MoneyChips m={line.list_price} sources={sources} />
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
        {excluded && !reference && line.tier !== "possible" && line.tier !== "not_in_public_data" && (
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

const PEER_KIND: Record<NonNullable<PeerRange["kind"]>, string> = {
  urgent_care: "urgent care centers",
  office: "doctors' offices",
  hospital_outpatient: "hospital clinics",
  ambulatory_surgery_center: "surgery centers",
};

/** P5: what an estimate rests on, from the line's own peer range. */
function EstimateBasis({ peer }: { peer: PeerRange }) {
  return (
    <p className="mt-1 text-[11px] text-amber-900" data-testid="estimate-basis">
      {peer.scope === "same_system"
        ? t("receipt.estimate_basis_system", { n: peer.n_groups })
        : t("receipt.estimate_basis", { n: peer.n_groups, kind: peer.kind ? PEER_KIND[peer.kind] : "places" })}
    </p>
  );
}

/**
 * A number shown only folded away, under a label that says what it is (and is not). P2: a Medicare
 * figure (rung 7) is never a non-Medicare person's price. P6: an insurer's rate at a place that does
 * not say it offers the service is not this place's price. P8: an unusual price is being checked.
 */
function HiddenPrice({
  line,
  sources,
  hidden,
}: {
  line: ReceiptLine;
  sources: QuoteResponse["sources"];
  hidden: NonNullable<ReturnType<typeof priceHidden>>;
}) {
  const head =
    hidden === "unusual" ? t("receipt.unusual") : hidden === "medicare_reference" ? t("receipt.no_plan_price") : null;
  const summary =
    hidden === "medicare_reference" ? t("receipt.medicare_reference") : hidden === "listed_rate" ? t("receipt.listed_rate") : t("receipt.listed_price");
  return (
    <div className="space-y-0.5" data-testid="hidden-price" data-hidden={hidden}>
      {head && (
        <p className={cn("text-sm font-medium", hidden === "unusual" ? "text-warn" : "text-muted-foreground")} data-testid={hidden === "unusual" ? "unusual" : undefined}>
          {head}
        </p>
      )}
      <details className="text-[11px] text-muted-foreground">
        <summary className="cursor-pointer select-none">{summary}</summary>
        <div className="mt-1 flex flex-col items-end gap-0.5 opacity-80">
          {hidden === "medicare_reference" && (
            <p className="inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground" data-testid="reference-tag">
              {t("receipt.reference_tag")}
            </p>
          )}
          {line.cell && <CellView cell={line.cell} sources={sources} />}
        </div>
      </details>
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
