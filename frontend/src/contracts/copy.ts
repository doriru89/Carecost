/**
 * The copy file the contract's copy keys resolve to (plan §2.5, D33; P1 problem 13).
 *
 * Every key the API can send, or that exhaustive.ts maps a contract member to, has English text here.
 * `CONTRACT_COPY` is typed `satisfies Record<ContractCopyKey, Copy>`, so a new Gap kind, rung, notice,
 * cadence, pause reason ... is a compile error (`npm run typecheck:contracts`) until it has text.
 *
 * Review: everything below was drafted by AI (claude-opus-5.5, 2026-10-24) and is pending Austin.
 * `review: true` marks the lines Austin MUST read before launch (safety, clinical framing, what a
 * person owes). The UI never shows the review flag; `copy.test.ts` lists them.
 */
import type { AiPausedReply, CarePathsReply, LlmInvalidReply } from "@/generated/contracts/chat_api";
import type { SourceKind } from "@/generated/contracts/quote_api";
import {
  COMPONENT_LABEL_KEY,
  EXCLUDED_REASON_KEY,
  GAP_COPY_KEY,
  LADDER_COPY_KEYS,
  NOTICE_KEY,
  OUR_CADENCE_KEY,
  PAUSE_REASON_KEY,
  SOURCE_CADENCE_KEY,
  SOURCE_CHIP_KEY,
  TIER_BASIS_KEY,
  TIER_ORDER,
  YOU_PAY_KEY,
} from "./exhaustive";

export interface Copy {
  en: string;
  /** Austin must review this wording before launch. */
  review?: true;
}

type ValueOf<T> = T[keyof T];

/** Every copy key a contract member resolves to. */
export type ContractCopyKey =
  | ValueOf<typeof GAP_COPY_KEY>
  | ValueOf<typeof COMPONENT_LABEL_KEY>
  | keyof typeof LADDER_COPY_KEYS
  | ValueOf<typeof EXCLUDED_REASON_KEY>
  | ValueOf<typeof SOURCE_CADENCE_KEY>
  | ValueOf<typeof OUR_CADENCE_KEY>
  | ValueOf<typeof SOURCE_CHIP_KEY>
  | `source_hover.${SourceKind}`
  | ValueOf<typeof TIER_BASIS_KEY>
  | ValueOf<typeof YOU_PAY_KEY>
  | ValueOf<typeof NOTICE_KEY>
  | ValueOf<typeof PAUSE_REASON_KEY>
  | `tier.${keyof typeof TIER_ORDER}`
  | AiPausedReply["message_key"]
  | LlmInvalidReply["message_key"]
  | CarePathsReply["copy_keys"][number];

export const CONTRACT_COPY = {
  // ---- Gap kinds (plan §2.5): one fixed sentence each, plus the line's own `what` / `ask`
  "gap.not_published": { en: "Not published. This kind of price file exists, but this place did not list this item." },
  "gap.not_loaded": { en: "Not loaded yet. The price file exists and we have not added it yet." },
  "gap.no_source": { en: "Not in any public file. No law requires this price to be published." },
  "gap.percent_only": { en: "Only a percentage is published, and the price it is a percentage of is not." },
  "gap.conflict": { en: "Two public files disagree. We show both numbers and leave this line out of the total." },

  // ---- Bill components
  "component.facility": { en: "Facility fee (the building, staff and equipment)" },
  "component.professional": { en: "Doctor's fee" },
  "component.drug": { en: "Medicine" },
  "component.supply": { en: "Supplies" },
  "component.unknown": { en: "The price file does not say which part of the bill this is" },

  // ---- Doctor-fee ladder (plan §2.4, D5, D6)
  "fee.rung_1_npi": { en: "This doctor's own negotiated rate with your plan." },
  "fee.rung_2_group": { en: "The doctor group's negotiated rates with your plan. The range covers the group's contracts." },
  "fee.rung_3_hospital_file": { en: "The doctor's fee as listed in the hospital's own price file." },
  "fee.rung_4_masshealth": { en: "MassHealth's state-set fee for this doctor's service." },
  "fee.rung_5_medicare": { en: "Medicare's government-set fee for this doctor's service in the Boston area." },
  "fee.rung_6_estimate": {
    en: "Estimate: Medicare's fee times this group's own typical markup with your plan. No file lists this exact price, so the total says it includes an estimate.",
    review: true,
  },
  "fee.rung_7_medicare_reference": { en: "For reference only: what Medicare pays. Not added to the total." },
  "fee.rung_8_chia_badge": { en: "No price, only a ranking: the state's report says this group is relatively expensive or cheap for your plan." },
  "fee.self_pay_no_source": {
    en: "No public file lists the doctor's fee for people paying cash. Ask the office before your visit.",
  },

  // ---- Why a line is not in the total
  "total.excluded.possible_tier": { en: "Only possible, so not in the total" },
  "total.excluded.ai_suggested": { en: "Suggested by the AI, so never in the total" },
  "total.excluded.no_dollar_amount": { en: "No dollar amount in public data" },
  "total.excluded.conflict": { en: "Sources disagree, so not in the total" },
  "total.excluded.not_offered_here": { en: "Not offered here" },
  "total.excluded.repeats": { en: "Repeats per session, so not in the one-visit total" },
  "total.excluded.reference_only": { en: "Reference price only" },

  // ---- Freshness (a) publisher side: "late to refresh"
  "fresh.source.hospital_mrf_365_days": { en: "Hospitals must update their price file at least once a year." },
  "fresh.source.tic_45_days": { en: "Insurers must update their price files every month." },
  "fresh.source.fee_schedule_annual": { en: "The government updates this fee schedule every year." },
  "fresh.source.fee_schedule_quarterly": { en: "The government updates this fee schedule every quarter." },
  "fresh.source.posted_page_date_365_days": { en: "We treat a posted price as late a year after the date printed on the page." },
  "fresh.source.no_publisher_deadline": { en: "The publisher has no deadline for updating this." },

  // ---- Freshness (b) our side: "stale on our side" (our fault, never the publisher's)
  "fresh.ours.hospital_monthly": { en: "We re-download hospital price files every month." },
  "fresh.ours.tic_monthly": { en: "We re-download insurer price files every month." },
  "fresh.ours.nppes_monthly": { en: "We refresh the federal doctor registry every month." },
  "fresh.ours.sites_weekly": { en: "We re-check clinic pages every week." },
  "fresh.ours.fee_schedule_per_release": { en: "We load each new government fee schedule when it is released." },

  // ---- Source chips (short) and their hover sentence (plan §2.2). {publisher} {date} are filled in.
  "source.hospital_mrf": { en: "Hospital price file" },
  "source.insurer_tic": { en: "Insurer price file" },
  "source.medicare_pfs": { en: "Medicare fee" },
  "source.medicare_opps": { en: "Medicare outpatient fee" },
  "source.medicare_asc": { en: "Medicare surgery-center fee" },
  "source.masshealth_fs": { en: "MassHealth fee" },
  "source.clinic_posted": { en: "Posted by the clinic" },
  "source.chia_rp": { en: "State price report" },
  "source_hover.hospital_mrf": { en: "Hospital's own price file, required by federal law · {publisher} · updated {date}" },
  "source_hover.insurer_tic": { en: "{publisher}'s negotiated rate, published under federal law · file {date}" },
  "source_hover.medicare_pfs": { en: "Medicare's Boston-area rate (government-set) · {date}" },
  "source_hover.medicare_opps": { en: "Medicare's hospital outpatient rate (government-set) · {date}" },
  "source_hover.medicare_asc": { en: "Medicare's surgery-center rate (government-set) · {date}" },
  "source_hover.masshealth_fs": { en: "MassHealth fee schedule (state-set) · {date}" },
  "source_hover.clinic_posted": { en: "Posted by {publisher} on its website. No law requires it · checked {date}" },
  "source_hover.chia_rp": { en: "{publisher} relative price report (state report). A ranking, not a price" },

  // ---- What the likelihood rests on (P11)
  "tier_basis.guideline": { en: "Based on a published clinical guideline" },
  "tier_basis.plan_rule": { en: "Based on how plans usually work" },
  "tier_basis.our_judgment": { en: "Our judgment from public sources" },
  "tier_basis.picked": { en: "You picked this" },

  // ---- Tiers (D8). Shown as section labels; the tier itself is carried by visual weight.
  "tier.certain": { en: "Happens at this visit" },
  "tier.likely": { en: "Likely" },
  "tier.possible": { en: "Possible extras, not in the total" },
  "tier.not_in_public_data": { en: "Not in public data" },

  // ---- You pay (P11): how, never the number
  "youpay.deductible_then_coinsurance": {
    en: "What you pay depends on your plan. Until your deductible is met you usually pay the full amount above; after that, a share (coinsurance).",
    review: true,
  },
  "youpay.copay_or_deductible": {
    en: "What you pay depends on your plan: a fixed copay for some visits, or the full amount above until your deductible is met.",
    review: true,
  },
  "youpay.medicare_20_percent": {
    en: "With traditional Medicare you usually pay 20% of the Medicare amount after the yearly Part B deductible. A supplement plan may pay some of it.",
    review: true,
  },
  "youpay.masshealth_small_or_no_copay": {
    en: "MassHealth members usually pay a small copay or nothing. ACO and managed-care plans may differ.",
    review: true,
  },
  "youpay.cash_full_amount": {
    en: "Paying cash, you pay the full amount. Ask for the self-pay price before your visit; many places discount it.",
  },

  // ---- Response notices
  "notice.care_path_draft": { en: "Draft: a clinician has not reviewed this care path yet." },
  "notice.tic_not_loaded": { en: "We have not loaded your insurer's price files yet, so some prices are missing." },
  "notice.late_to_refresh_sources": { en: "Some publishers are late to refresh their price files. We still show their last prices, marked." },
  "notice.stale_on_our_side_sources": { en: "We are behind on refreshing some files. That is our delay, not the publisher's." },
  "notice.masshealth_aco_may_differ": { en: "These are MassHealth fee-for-service rates. ACO and managed-care plans may pay differently." },
  "notice.medicare_advantage_is_insurance": {
    en: "Medicare Advantage plans are private insurance: pick your insurer above instead of Medicare.",
  },

  // ---- AI states. Wording from the Chat stream (git show wave2/chat:data/chat/copy.yaml, review pending_austin)
  "ai.paused_ip_cap": {
    en: "The assistant has reached today's limit for this network. It comes back tomorrow; prices are still here.",
    review: true,
  },
  "ai.paused_wallet": {
    en: "The assistant is paused for today. You can still browse prices.",
    review: true,
  },
  "ai.paused_provider": {
    en: "The assistant isn't available right now. You can still browse prices.",
    review: true,
  },
  "ai.paused_conversation_cap": {
    en: "This conversation is long enough. Start a new one, or browse prices directly.",
    review: true,
  },
  "ai.output_invalid": {
    en: "The assistant couldn't give a clear answer this time. You can still browse prices and pick a care path yourself.",
    review: true,
  },

  // ---- D33: fixed lines shown with every set of care paths and under a receipt reached from a care path.
  // Wording from the Chat stream (data/chat/copy.yaml): patient-facing clinical text, pending Austin + 1 outside reader (P10).
  "copy.not_a_diagnosis": {
    en: "These are common causes, not a diagnosis. A doctor needs to examine you to know what is going on.",
    review: true,
  },
  "copy.when_to_see_a_doctor": {
    en: "See a doctor soon if it gets worse quickly, keeps you up at night, or comes with fever, numbness or weakness. For chest pain, trouble breathing or thoughts of harming yourself, call 911 or 988 now.",
    review: true,
  },
} as const satisfies Record<ContractCopyKey, Copy>;

/** App copy that is not tied to a contract member but carries meaning (safety pages, receipt framing). */
export const APP_COPY = {
  "start.title": { en: "What does this care cost near Boston?" },
  "start.payment": { en: "How are you paying?" },
  "start.chat_placeholder": { en: "Describe what's going on, e.g. my shoulder has hurt for months and clicks" },
  "start.email": { en: "Email (needed to use the AI helper; we do not verify it)" },
  "start.skip_ai": { en: "Skip AI → Browse prices" },
  "start.privacy": { en: "Your location never leaves this browser. Distances are computed on your device." },

  "receipt.total": { en: "Estimated total billed (you + your plan)" },
  "receipt.total_floor": { en: "At least this much: some likely items have no public price." },
  "receipt.includes_estimate": { en: "Includes an estimate" },
  "receipt.includes_late": { en: "Includes a price from a file that is late to refresh" },
  "receipt.includes_stale": { en: "Includes a price we are behind on refreshing" },
  "receipt.ask": { en: "Ask" },
  "receipt.ask_not_loaded": { en: "Is this billed separately, and how much is it?" },
  "gap.label.not_published": { en: "Not published" },
  "gap.label.not_loaded": { en: "Not loaded yet" },
  "gap.label.no_source": { en: "No public source" },
  "receipt.list_price": { en: "List price (almost nobody pays this; never added up)" },
  "receipt.no_cash_discount": { en: "No cash discount listed: the cash price equals the list price." },
  "receipt.ai_suggested": { en: "✦ AI-suggested: public data doesn't say whether this happens" },
  "receipt.per_15_minutes": { en: "per 15 minutes" },
  "receipt.per_visit": { en: "per session; repeats are not in the total" },
  "receipt.not_offered": { en: "Not offered here" },
  "receipt.at_your_primary_care": {
    en: "Happens at your own primary care office, not at this place. Not priced at this place.",
  },
  "receipt.estimate_tag": { en: "Estimate" },
  "receipt.reference_tag": { en: "Reference only, not added" },
  "receipt.price_source_not_read": {
    en: "This place has its own price list, but we do not read it yet. Its prices show as not loaded.",
  },
  "receipt.d33_heading": { en: "Before you go" },
  "receipt.cheapest_elsewhere": { en: "Available elsewhere" },
  "receipt.other_payers": { en: "Same item here, other ways of paying" },
  "receipt.sources": { en: "Sources & dates" },
  "fresh.late_label": { en: "Late to refresh" },
  "fresh.stale_label": { en: "Stale on our side" },
  "fresh.current_label": { en: "Current" },
  "billing.office_visit": { en: "Billed as an office visit (no hospital facility fee)" },
  "billing.hospital_outpatient": { en: "Billed as a hospital outpatient department: expect a separate facility fee" },
  "billing.asc": { en: "Billed as a surgery center" },
  "billing.unknown": { en: "Billing type not confirmed" },

  "chat.unreachable": { en: "The AI helper could not answer (server error {status}). You can still browse prices." },
  "chat.unreachable_network": { en: "The AI helper could not be reached. You can still browse prices." },

  "redflag.no_prices": { en: "We've stopped here and are not showing prices." },
  "redflag.back_home": { en: "Back to the home page", review: true },
  "redflag.call_911": { en: "Call 911", review: true },
  "crisis.call_988": { en: "Call 988", review: true },
  "crisis.text_988": { en: "Text 988", review: true },
  "crisis.chat_988": { en: "Chat at 988lifeline.org", review: true },
  "crisis.danger_911": { en: "In immediate danger? Call 911", review: true },
  "crisis.not_alone": {
    en: "988 is the Suicide & Crisis Lifeline. It is free, confidential, and open 24 hours a day, every day.",
    review: true,
  },
} as const satisfies Record<string, Copy>;

export type AppCopyKey = keyof typeof APP_COPY;
export type CopyKey = ContractCopyKey | AppCopyKey;

const ALL: Record<string, Copy> = { ...CONTRACT_COPY, ...APP_COPY };

/** Text for a key. Unknown keys (a backend key the frontend has not seen) show the key, never blank. */
export function t(key: CopyKey | string, vars?: Record<string, string | number | null | undefined>): string {
  let s = ALL[key]?.en ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v == null ? "" : String(v));
  }
  return s;
}

export function hasCopy(key: string): boolean {
  return key in ALL;
}

/** Keys Austin must review before launch. */
export function reviewKeys(): string[] {
  return Object.entries(ALL)
    .filter(([, c]) => c.review)
    .map(([k]) => k);
}
