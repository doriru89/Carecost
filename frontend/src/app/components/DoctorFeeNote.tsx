import { t } from "@/contracts/copy";
import type { DoctorFee, QuoteResponse } from "@/generated/contracts/quote_api";
import { InfoTip } from "./InfoTip";
import { MoneyWithChip } from "./CellView";

const BAND: Record<NonNullable<DoctorFee["chia_badge"]>["band"], string> = {
  top_quarter: "among the most expensive",
  above_median: "more expensive than most",
  below_median: "cheaper than most",
  bottom_quarter: "among the cheapest",
};

/** The doctor-fee ladder note (§2.4): fixed copy per rung, the group, a rung-6 multiple, and D6 by-NPI. */
export function DoctorFeeNote({ fee, sources }: { fee: DoctorFee; sources: QuoteResponse["sources"] }) {
  return (
    <div className="mt-1 text-[11px] text-muted-foreground space-y-0.5" data-testid="doctor-fee">
      <p>
        {t(fee.explanation_key)}
        {fee.group_name ? ` Group: ${fee.group_name}.` : ""}
        {fee.npi_count ? ` ${fee.npi_count} doctors.` : ""}
      </p>
      {fee.multiple && (
        <p>
          Markup used: {fee.multiple.low.toFixed(2)}×{fee.multiple.high !== fee.multiple.low ? `–${fee.multiple.high.toFixed(2)}×` : ""} Medicare, from {fee.multiple.n_codes} of
          this group's own codes.
        </p>
      )}
      {fee.chia_badge && (
        <p>
          State report {fee.chia_badge.report_year}: this group is {BAND[fee.chia_badge.band]} for this insurer.
        </p>
      )}
      {fee.by_npi && fee.by_npi.length > 0 && (
        <InfoTip
          label="Price by doctor"
          trigger={<span className="underline decoration-dotted">Price by doctor ({fee.by_npi.length})</span>}
        >
          <p className="font-semibold text-foreground mb-1">Each doctor's rate with your plan</p>
          <ul className="space-y-1">
            {fee.by_npi.map((d) => (
              <li key={d.npi} className="flex justify-between gap-2">
                <span>{d.display_name ?? `NPI ${d.npi}`}</span>
                <MoneyWithChip m={d.money} sources={sources} />
              </li>
            ))}
          </ul>
        </InfoTip>
      )}
    </div>
  );
}
