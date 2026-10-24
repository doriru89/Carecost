/**
 * Exhaustiveness locks for the wave-2 contracts (plan §2.5: enforced, not advisory).
 *
 * Every closed set in the API (Gap kinds, certainty tiers, chat reply kinds, dispositions, doctor-fee
 * copy keys ...) has one map here typed `satisfies Record<Union, ...>`. Add a member on the Python side,
 * regenerate (`python -m app.api_contracts`), and `npm run typecheck:contracts` fails until the
 * frontend handles it. Remove one and the stale key fails too (excess property check).
 *
 * The UI streams import these maps instead of writing their own switch statements.
 */
import type {
  BillComponent,
  Cell,
  CertaintyTier,
  ExcludedReason,
  Gap,
  LadderExplanation,
  OurCadence,
  Likelihood,
  Payment,
  QuoteResponse,
  SourceCadence,
  SourceKind,
} from "@/generated/contracts/quote_api";
import type { ChatReply, Disposition } from "@/generated/contracts/chat_api";

/** One fixed copy key per Gap kind (backend: app.etl.contracts.GAP_GLOSSARY). */
export const GAP_COPY_KEY = {
  not_published: "gap.not_published",
  not_loaded: "gap.not_loaded",
  no_source: "gap.no_source",
  percent_only: "gap.percent_only",
  conflict: "gap.conflict",
} as const satisfies { [K in Gap["kind"]]: `gap.${K}` };

/** Cell = Money | Gap: every kind a price cell can hold. */
export const CELL_HAS_DOLLARS = {
  money: true,
  conflict: true,
  percent_only: false,
  not_published: false,
  not_loaded: false,
  no_source: false,
} as const satisfies Record<Cell["kind"], boolean>;

/** D8 gradient, strongest first. Visual weight only; the UI never prints the number. */
export const TIER_ORDER = {
  certain: 0,
  likely: 1,
  possible: 2,
  not_in_public_data: 3,
} as const satisfies Record<CertaintyTier, number>;

export const LIKELIHOOD_TO_TIER = {
  certain: "certain",
  likely: "likely",
  possible: "possible",
  rare: "possible",
} as const satisfies Record<Likelihood, CertaintyTier>;

export const COMPONENT_LABEL_KEY = {
  facility: "component.facility",
  professional: "component.professional",
  drug: "component.drug",
  supply: "component.supply",
  unknown: "component.unknown",
} as const satisfies Record<BillComponent, string>;

export const LADDER_COPY_KEYS = {
  "fee.rung_1_npi": 1,
  "fee.rung_2_group": 2,
  "fee.rung_3_hospital_file": 3,
  "fee.rung_4_masshealth": 4,
  "fee.rung_5_medicare": 5,
  "fee.rung_6_estimate": 6,
  "fee.rung_7_medicare_reference": 7,
  "fee.rung_8_chia_badge": 8,
  "fee.self_pay_no_source": null,
} as const satisfies Record<LadderExplanation, number | null>;

export const EXCLUDED_REASON_KEY = {
  possible_tier: "total.excluded.possible_tier",
  ai_suggested: "total.excluded.ai_suggested",
  no_dollar_amount: "total.excluded.no_dollar_amount",
  conflict: "total.excluded.conflict",
  not_offered_here: "total.excluded.not_offered_here",
  repeats: "total.excluded.repeats",
  reference_only: "total.excluded.reference_only",
} as const satisfies Record<ExcludedReason, string>;

/** (a) Publisher side: "late to refresh" is the publisher's delay, shown with the data. */
export const SOURCE_CADENCE_KEY = {
  hospital_mrf_365_days: "fresh.source.hospital_mrf_365_days",
  tic_45_days: "fresh.source.tic_45_days",
  fee_schedule_annual: "fresh.source.fee_schedule_annual",
  fee_schedule_quarterly: "fresh.source.fee_schedule_quarterly",
  posted_page_date_365_days: "fresh.source.posted_page_date_365_days",
  no_publisher_deadline: "fresh.source.no_publisher_deadline",
} as const satisfies Record<SourceCadence, string>;

/** (b) Our side: "stale on our side" is OUR missed refresh. Never worded as the publisher's fault. */
export const OUR_CADENCE_KEY = {
  hospital_monthly: "fresh.ours.hospital_monthly",
  tic_monthly: "fresh.ours.tic_monthly",
  nppes_monthly: "fresh.ours.nppes_monthly",
  sites_weekly: "fresh.ours.sites_weekly",
  fee_schedule_per_release: "fresh.ours.fee_schedule_per_release",
} as const satisfies Record<OurCadence, string>;

/** Source chip copy key per price source (SourceChip.label_key = `source.<kind>`). */
export const SOURCE_CHIP_KEY = {
  hospital_mrf: "source.hospital_mrf",
  insurer_tic: "source.insurer_tic",
  medicare_pfs: "source.medicare_pfs",
  medicare_opps: "source.medicare_opps",
  medicare_asc: "source.medicare_asc",
  masshealth_fs: "source.masshealth_fs",
  clinic_posted: "source.clinic_posted",
  chia_rp: "source.chia_rp",
  estimate: "source.estimate",
  ai_potential: "source.ai_potential",
} as const satisfies { [K in SourceKind]: `source.${K}` };

export const PAYMENT_KINDS = {
  insurance: true,
  medicare: true,
  masshealth: true,
  cash: true,
} as const satisfies Record<Payment["kind"], true>;

/** Chat replies the UI must render. red_flag replaces the whole page (no prices). */
export const CHAT_REPLY_FULL_PAGE = {
  red_flag: true,
  clarify: false,
  care_paths: false,
  text: false,
  ai_paused: false,
} as const satisfies Record<ChatReply["kind"], boolean>;

/** Response-level notices. The two freshness notices are worded differently (publisher vs us). */
export const NOTICE_KEY = {
  care_path_draft: "notice.care_path_draft",
  tic_not_loaded: "notice.tic_not_loaded",
  late_to_refresh_sources: "notice.late_to_refresh_sources",
  stale_on_our_side_sources: "notice.stale_on_our_side_sources",
  masshealth_aco_may_differ: "notice.masshealth_aco_may_differ",
  medicare_advantage_is_insurance: "notice.medicare_advantage_is_insurance",
} as const satisfies Record<QuoteResponse["notices"][number], string>;

export const DISPOSITION_RANK = {
  call_911: 4,
  er_today: 3,
  seen_today: 2,
  routine: 1,
} as const satisfies Record<Disposition, number>;

export function assertNever(x: never): never {
  throw new Error(`unhandled contract member: ${JSON.stringify(x)}`);
}

/** Example narrowing the UI can copy: a switch over Cell that fails to compile if a kind is added. */
export function cellSummary(cell: Cell): string {
  switch (cell.kind) {
    case "money":
      return cell.low === cell.high ? `$${cell.low.toFixed(2)}` : `$${cell.low.toFixed(2)}–$${cell.high.toFixed(2)}`;
    case "conflict":
      return "sources disagree";
    case "percent_only":
      return `${cell.pct}% of ${cell.of}`;
    case "not_published":
    case "not_loaded":
    case "no_source":
      return GAP_COPY_KEY[cell.kind];
    default:
      return assertNever(cell);
  }
}
