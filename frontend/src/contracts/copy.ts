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
import type { AiPausedReply, CarePathsReply, ClarifyReply, LlmInvalidReply } from "@/generated/contracts/chat_api";
import type { ErReference, HeadlineRange, ReceiptLine, SourceKind } from "@/generated/contracts/quote_api";
import {
  AVAILABILITY_REASON_KEY,
  CHEAPEST_BASIS_KEY,
  COMPONENT_LABEL_KEY,
  EXCLUDED_REASON_KEY,
  GAP_COPY_KEY,
  HEADLINE_BASIS_KEY,
  KIND_LABEL_KEY,
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
  /** Chinese text where Austin has fixed it (P2: the self-pay label). The UI is English-only today. */
  zh?: string;
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
  | CarePathsReply["copy_keys"][number]
  | NonNullable<ClarifyReply["fixed_text_key"] | CarePathsReply["fixed_text_key"]>
  | ValueOf<typeof KIND_LABEL_KEY>
  | ReceiptLine["price_notes"][number]
  // C4b
  | NonNullable<ValueOf<typeof HEADLINE_BASIS_KEY>>
  | ValueOf<typeof CHEAPEST_BASIS_KEY>
  | ValueOf<typeof AVAILABILITY_REASON_KEY>
  | HeadlineRange["note_keys"][number]
  | ErReference["note_key"];

export const CONTRACT_COPY = {
  // ---- C2 price notes: how a line's number was made (ReceiptLine.price_notes)
  "price.national_unadjusted": {
    en: "Medicare's national rate, not adjusted for Boston",
    review: true,
  },
  "price.anesthesia_base_units_only": {
    en: "Anesthesia base units only. The time units depend on how long the case takes and are not in this number.",
    review: true,
  },
  // P8a (Austin, 2026-10-25): a contract-level outlier is shown and summed, with this note
  "price.group_consistently_higher": {
    en: "This group's prices are consistently higher than similar places here.",
    review: true,
  },
  "price.group_consistently_lower": {
    en: "This group's prices are consistently lower than similar places here.",
    review: true,
  },
  // C4b item 5: the same group/payer/amount on the visit code and on this test's code: counted once, on the visit
  "price.flat_visit_rate": {
    en: "This insurer pays this place one amount per visit. The test may be included in the visit, so it adds $0 here.",
    review: true,
  },
  // C4c: anesthesia estimated from the plan's own anesthesia rates at a typical case time
  "price.anesthesia_typical_time": {
    en: "Estimate: what your plan pays for sleep medicine elsewhere, for a typical length of this procedure. The real bill depends on how long it takes.",
    review: true,
  },
  // C4b item 4 (A6 flag same_npi_pos_multi_rate): the insurer's file lists several rates for the same doctors here
  "price.several_rates_same_doctors": {
    en: "Your insurer's file lists more than one rate for the same doctors here, so we show the range.",
    review: true,
  },

  // ---- C4b headline (HeadlineRange): from_only, basis
  // shown as "from $X — the doctor bills separately"; never as the full price
  "headline.doctor_bills_separately": { en: "the doctor bills separately", review: true },
  // C4c: insured, the insurer's file has no rate for the doctor's bill
  "headline.doctor_bill_not_published": { en: "the doctor's bill isn't published", review: true },
  "headline.basis.includes_estimate": { en: "Includes an estimate", review: true },
  "headline.basis.partial": { en: "Only partial prices found here", review: true },

  // ---- C4b cheapest_basis (Austin 2026-10-25): honest wording next to "cheapest place for this"
  "cheapest.complete": { en: "Cheapest, from their own published prices", review: true },
  "cheapest.includes_estimate": { en: "Cheapest; part of this is an estimate", review: true },
  "cheapest.partial": { en: "Only partial prices found here", review: true },

  // ---- C4b item 7: the ER for comparison (never ranked, never a place in the list)
  "er.visit_alone_costs_more": {
    en: "At the ER, the visit alone usually costs much more than urgent care, before any tests.",
    review: true,
  },

  // ---- Gap kinds (plan §2.5): one fixed sentence each, plus the line's own `what` / `ask`
  "gap.not_published": { en: "Not published. This kind of price file exists, but this place did not list this item." },
  "gap.not_loaded": { en: "Not loaded yet. The price file exists and we have not added it yet." },
  "gap.no_source": { en: "Not in any public file. No law requires this price to be published." },
  "gap.percent_only": { en: "Only a percentage is published, and the price it is a percentage of is not." },
  "gap.conflict": { en: "Two public files disagree. We show both numbers and leave this line out of the total." },

  // ---- Bill components
  "component.facility": { en: "The hospital's or center's own bill (the building, staff and equipment)" },
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
  // C3 (P5): rung 6 is now the peer estimate (the Medicare multiple is gone)
  "fee.rung_6_estimate": {
    en: "Estimate: no file lists this doctor group's rate with your plan, so this is the middle range of what the same plan pays similar places for the same service. The total says it includes an estimate.",
    review: true,
  },
  "fee.rung_7_medicare_reference": {
    en: "For reference only: what Medicare pays. Not your plan's price, and not added to the total.",
    review: true,
  },
  "fee.rung_8_chia_badge": { en: "No price, only a ranking: the state's report says this group is relatively expensive or cheap for your plan." },
  "fee.self_pay_no_source": {
    en: "No public file lists the doctor's fee for self-pay (no insurance). Ask the office before your visit.",
    review: true,
  },

  // ---- Why a line is not in the total
  "total.excluded.possible_tier": { en: "Only possible, so not in the total" },
  "total.excluded.ai_suggested": { en: "Suggested by the AI, so never in the total" },
  "total.excluded.no_dollar_amount": { en: "No dollar amount in public data" },
  "total.excluded.conflict": { en: "Sources disagree, so not in the total" },
  "total.excluded.not_offered_here": { en: "Not offered here" },
  "total.excluded.repeats": { en: "Repeats per session, so not in the one-visit total" },
  "total.excluded.reference_only": { en: "Reference price only" },
  "total.excluded.availability_unknown": {
    en: "Not known whether this place offers it, so not in the total",
    review: true,
  },
  "total.excluded.unusual": { en: "Price looks unusual, being checked, so not in the total", review: true },
  "total.excluded.flat_visit_rate": { en: "Paid as part of the visit, so it adds $0", review: true },

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
    en: "Self-pay (no insurance): you pay the full amount. Ask for the self-pay price before your visit; many places discount it.",
    review: true,
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
  "notice.hmo_referral_for_specialist": {
    en: "Your plan may need a referral from your primary care doctor before you see a specialist. Check with your plan or your doctor first.",
    review: true,
  },
  "notice.chain_price_spread": {
    en: "Some locations of the same chain list the same item at prices more than 1.5× apart. Each location shows its own price; we are checking why.",
    review: true,
  },

  // ---- P6 (Austin, 2026-10-25): an insurer's file is never evidence that a place offers a service
  "receipt.availability.insurer_lists_rate": {
    en: "Your insurer lists a rate for this group, but this place doesn't say it offers this. Call to check.",
    review: true,
  },
  // C4b 3e: the same for a person without insurance (a price file row, not an insurer's rate)
  "receipt.availability.price_file_lists_rate": {
    en: "A price file lists a price for this here, but this place doesn't say it offers it. Call to check.",
    review: true,
  },
  "receipt.availability.no_evidence": {
    en: "This place doesn't say whether it offers this. Call to check.",
    review: true,
  },
  "receipt.availability.site_says_not_offered": { en: "This place says it doesn't offer this.", review: true },

  // ---- X2 / P7: the kind of site, the group headers of a list with no location
  "kind.urgent_care": { en: "Urgent care" },
  "kind.office": { en: "Doctors' offices" },
  "kind.hospital_outpatient": { en: "Hospital outpatient clinics" },
  "kind.ambulatory_surgery_center": { en: "Surgery centers" },

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
  // R18 / P13 (Chat2): fixed copy shown instead of model text. Wording from data/chat/copy.yaml.
  "ai.paused_provider_chips": {
    en: "The assistant can't read typed messages right now. Answer the questions below to find a care path, or browse prices.",
    zh: "助手现在无法读取你输入的文字。回答下面的问题来找到就医路径，或直接浏览价格。",
    review: true,
  },
  "chat.fixed_clarify": {
    en: "One more question helps narrow this down.",
    zh: "再回答一个问题，可以缩小范围。",
    review: true,
  },
  "chat.fixed_paths": {
    en: "These care paths match your answers so far.",
    zh: "这些就医路径符合你目前的回答。",
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
  // P2 (Austin, 2026-10-25): "cash price" is called self-pay / no insurance wherever a person reads it.
  // The enum value stays `cash`.
  "payment.self_pay": { en: "Self-pay (no insurance)", zh: "自费（无保险）", review: true },
  // R15: a new quote is loading; the receipt below is the previous one, dimmed
  "quote.updating": { en: "Updating prices for {payment}… The prices below are from your previous choice and are not current." },
  "quote.timeout": { en: "The price server did not answer within a minute. Try again in a moment." },
  // Cloud Run scales to zero: the first request after a quiet spell waits while the server loads the price data
  "quote.waking": { en: "Starting the price server. After a quiet spell this takes up to 40 seconds; after that, prices load in under a second." },
  // Browse (Austin 2026-11-09): pick a service or CPT code from dropdowns, filter places, see them on the map
  "browse.area": { en: "Body area" },
  "browse.area_all": { en: "All areas" },
  "browse.service": { en: "Service or CPT code" },
  "browse.code_search": { en: "Type a code or name" },
  "browse.group_paths": { en: "Whole visit, step by step" },
  "browse.group_visit": { en: "Visits" },
  "browse.group_imaging": { en: "Imaging" },
  "browse.group_procedure": { en: "Procedures" },
  "browse.group_lab": { en: "Lab tests" },
  "browse.group_other": { en: "Other" },
  "browse.place_kind": { en: "Place type" },
  "browse.kind_all": { en: "All places" },
  "browse.show": { en: "Show" },
  "browse.show_offered": { en: "Every place that offers it" },
  "browse.show_priced": { en: "Only places with a price" },
  "browse.map": { en: "Map" },
  "browse.list": { en: "List" },
  "browse.count": { en: "{shown} of {total} places · {priced} with a price" },
  "browse.none": { en: "No place matches these filters. Try another place type, or show every place." },
  "browse.no_code": { en: "No service matches that code or name." },
  // P3: the map shows a price only for one selected service
  "map.places_only": {
    en: "Places only. The map shows the price of one step at a time: pick a step above, or a single service under Browse. The List shows the full total.",
    review: true,
  },
  "map.price_for": { en: "Prices on the map: {service}" },
  "start.privacy": {
    en: "If you add a ZIP or your location, we send that point (your location rounded to about half a mile) with the price request, only to pick the places nearest you. We do not store it. Distances are computed on your device.",
    review: true,
  },

  "receipt.total": { en: "Estimated total billed (you + your plan)" },
  "receipt.total_floor": { en: "At least this much: some likely steps have no price at this place (see below)." },
  "receipt.includes_estimate": { en: "Includes an estimate" },
  "receipt.includes_late": { en: "Includes a price from a file that is late to refresh" },
  "receipt.includes_stale": { en: "Includes a price we are behind on refreshing" },
  "receipt.ask": { en: "Ask" },
  "receipt.ask_not_loaded": { en: "Is this billed separately, and how much is it?" },
  "gap.label.not_published": { en: "Not published" },
  "gap.label.not_loaded": { en: "Not loaded yet" },
  "gap.label.no_source": { en: "No public source" },
  "receipt.list_price": { en: "List price (almost nobody pays this; never added up)" },
  "receipt.no_cash_discount": {
    en: "No self-pay discount listed: the self-pay price equals the list price.",
    review: true,
  },
  "receipt.ai_suggested": { en: "✦ AI-suggested: public data doesn't say whether this happens" },
  "receipt.per_15_minutes": { en: "per 15 minutes" },
  "receipt.per_visit": { en: "per session; repeats are not in the total" },
  "receipt.not_offered": { en: "Not offered here" },
  "receipt.availability_unknown": { en: "Not known whether this place offers it" },
  "receipt.listed_rate": { en: "The rate your insurer's file lists for this group (not counted)" },
  "receipt.listed_price": { en: "The price in the file (not counted)" },
  "receipt.medicare_reference": { en: "For reference: what Medicare pays (not your plan's price)" },
  "receipt.no_plan_price": { en: "No price for your plan" },
  // P4: a step this place doesn't do is its own line, priced at the places that do
  "receipt.elsewhere_section": { en: "Not done here, not confirmed, or no price here" },
  // C4b elsewhere_estimate: this place does the step but publishes no price for it
  "receipt.elsewhere_estimate_why": {
    en: "This place does this, but we found no price for it here. The typical price nearby is used in the range, marked as an estimate.",
    review: true,
  },
  // C4b: an elsewhere / elsewhere_estimate figure is never this place's own price
  "receipt.elsewhere_about": { en: "About {range} (typical price nearby)", review: true },
  "receipt.elsewhere_basis": {
    en: "The middle half of prices at {n} places that do it, with the same way of paying. Not in this place's total.",
    review: true,
  },
  "receipt.elsewhere_none": { en: "No place in our data has a price for this with your way of paying." },
  // P5: an estimate is the same line at peer places of the same kind
  "receipt.estimate_basis": {
    en: "Estimate: the middle half of prices at {n} similar {kind} for the same item, with the same way of paying.",
    review: true,
  },
  // C4c payer_network: the plan's own rates in its network for the same item
  "receipt.estimate_basis_network": {
    en: "Estimate: the middle half of what your plan pays {n} groups in its network for the same item.",
    review: true,
  },
  "receipt.estimate_basis_system": {
    en: "Estimate: the middle half of prices at {n} groups in this health system for the same item, with the same way of paying.",
    review: true,
  },
  // P8: outside 1/3x-3x of the peer median, not summed
  "receipt.unusual": { en: "Price looks unusual, being checked", review: true },
  "receipt.unusual_set_aside": {
    en: "{n} listed {prices} outside the usual range left out of this range, being checked.",
    review: true,
  },
  // P9: possible steps are never in the headline
  "receipt.might_add": { en: "Might add {range}" },
  "receipt.might_add_detail": { en: "if the doctor decides you need: {steps}", review: true },
  "receipt.anesthesia_time": {
    en: "With a typical time ({minutes} min), about {range}. Not in the total.",
    review: true,
  },
  "receipt.chain_price": { en: "{chain}'s posted self-pay price for all its locations" },
  "receipt.step_included": { en: "Done here" },
  "receipt.loading": { en: "Loading this place's receipt…" },
  "receipt.load_failed": { en: "Could not load this place's receipt. Try again in a moment." },
  "list.no_total": { en: "No price here in public data for this way of paying" },
  "list.done_elsewhere": { en: "{step}: about {range} (typical price nearby)" },
  // P3: on the map, one step's price at a time
  "map.pick_step": { en: "Show the price of one step on the map:" },
  "map.no_step": { en: "Places only" },
  // Austin 2026-11-09: the step chips sit in the chat, next to the care path they belong to
  "steps.pick": { en: "Price one step on the map and list:" },
  "steps.pick_in_chat": { en: "Price one step:" },
  "map.places_only_chat": {
    en: "Places only. Pick a step under the care path in the chat to see its price on each pin. The List shows the full total.",
  },
  "list.step_line": { en: "{step}: {price}" },
  "list.step_estimate": { en: "estimate" },
  "list.step_no_price": { en: "{step}: offered, no price found" },
  "list.step_not_listed": { en: "{step}: not listed as offered here" },
  "chat.helper": { en: "AI helper" },
  "chat.collapse": { en: "Hide the AI helper" },
  "chat.expand": { en: "Show the AI helper" },
  "map.step_price_for": {
    en: "Prices on the map: {step}. Places that don't say they offer it have no pin.",
    review: true,
  },
  "site.children_only": { en: "Children only" },
  "list.scope_near": { en: "The {n} places nearest {label}" },
  // P7 (Austin, 2026-10-25): with no location, every place that does this, grouped by kind, by distance
  // from Boston City Hall. Never "best value overall".
  "list.scope_all": {
    en: "All {n} places that do this, grouped by kind of place, nearest to Boston City Hall first. Add a ZIP or use your location to see the places nearest you.",
    review: true,
  },
  "list.from_city_hall": { en: "{distance} from Boston City Hall" },
  "list.scope_fixture": { en: "Test data: a fixed sample of places, not the ones nearest you." },
  // C2 data-quality notices (data/etl/data_quality_notices.yaml, written by people): one sentence per kind
  "data_notice.content_changed_date_unchanged": {
    en: "This place's price file changed, but the date on it did not. We keep using the file's own date, so its prices may be newer than that date says.",
    review: true,
  },
  "data_notice.generic": { en: "We noticed something unusual about this place's price file.", review: true },
  "data_notice.details": { en: "What we saw ({date})" },
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
  "billing.office_visit": { en: "Billed as an office visit (no separate hospital bill)" },
  "billing.hospital_outpatient": { en: "Billed as a hospital clinic: expect a hospital bill, and the doctor bills separately" },
  "billing.asc": { en: "Billed as a surgery center" },
  // P9: unknown billing is priced as a hospital clinic, never as an office
  "billing.unknown": {
    en: "Billing type not confirmed: priced as a hospital clinic. This place may also send a separate hospital bill.",
    review: true,
  },
  "receipt.facility_fee_possible": {
    en: "This place may also send a separate hospital bill. We could not confirm how it bills.",
    review: true,
  },

  // ---- C4b / D6: the first screen (D-UI-1, D-UI-3). Plain words; every distinction is one tap away.
  "headline.from": { en: "from {low} — {note}", review: true },
  "headline.includes": { en: "Includes the {base}, plus: {items}", review: true },
  "headline.includes_base": { en: "Includes the {base}", review: true },
  "headline.visit_only": { en: "doctor visit", review: true },
  "headline.not_priced": { en: "Not in this figure, no price found: {items}", review: true },
  "overview.title": { en: "Where to go, and roughly what it costs" },
  "overview.lead": {
    en: "What seeing a doctor for this probably costs at each place: the visit and what usually happens. Tap a place to see every bill.",
    review: true,
  },
  "overview.no_options": { en: "Places for this" },
  "option.label": { en: "Option {letter}: {label}" },
  "option.range": { en: "{range} across {n} places" },
  "option.partial_more": { en: "plus {n} {places} with only partial prices", review: true },
  "option.no_range": { en: "No place in this option has a price yet" },
  "option.unpriced": { en: "We don't have prices for this yet.", review: true },
  "option.cheapest": { en: "Cheapest place for this" },
  "option.cheapest_not_here": { en: "The cheapest place for this is not among the places shown." },
  "option.alternates": { en: "Other places" },
  "option.see_all": { en: "See all {n} places in the list" },
  "order.label": { en: "Order:" },
  "order.distance": { en: "Nearest first" },
  "order.price": { en: "Cheapest first" },
  "order.price_note": { en: "Places with their own complete prices come first.", review: true },
  "order.distance_from_city_hall": { en: "Distances are from Boston City Hall. Add a ZIP to see the places nearest you." },
  "nearby.about": { en: "about {range} (typical price nearby)", review: true },
  "may_also.heading": { en: "The doctor may also order (not in the price above)", review: true },
  "may_also.one_of": { en: "One of these, if needed:", review: true },
  "may_also.no_price": { en: "no price found" },
  "flat.adds_zero": { en: "Adds $0: paid as part of the visit", review: true },
  // D-UI-2: the breakdown on tap, how the range was built
  "breakdown.heading": { en: "How this range was built" },
  "breakdown.visit_only": { en: "The visit alone (every bill)" },
  "breakdown.with_likely": { en: "The visit and what usually happens (the price shown above)" },
  "breakdown.with_possible": { en: "If the doctor also orders everything possible" },
  "breakdown.counts": { en: "Counts: {items}" },
  "breakdown.not_priced": { en: "No price found, not counted: {items}", review: true },
  "breakdown.alternatives": { en: "Not counted, a dearer alternative is: {items}", review: true },
  // plain source footnote per number (Fact / Inferred / Assumed in plain words)
  "footnote.own_published": { en: "Fact: their own published price" },
  "footnote.insurer_file": { en: "Fact: from your insurer's price file" },
  "footnote.government": { en: "Fact: the government-set fee" },
  "footnote.own_figure": { en: "Fact: this place's own price" },
  "footnote.estimate": { en: "Estimate: from similar places nearby", review: true },
  "footnote.nearby": { en: "Typical price nearby, not this place's own price", review: true },
  "footnote.not_published": { en: "Not published" },
  "footnote.from_only": { en: "The hospital's own bill only; the doctor's bill has no number", review: true },
  "doctor.bills_separately": { en: "The doctor bills separately", review: true },
  // cheap win (06-coherent-story-v6.md:35): fixed copy, the same for every place
  "call.heading": { en: "3 questions to ask when you call", review: true },
  "call.q_self_pay": { en: "What is your self-pay price for this visit?", review: true },
  "call.q_doctor": { en: "Will the doctor send a separate bill?", review: true },
  "call.q_plan": { en: "Do you take my plan ({plan})?", review: true },
  "call.q_plan_none": { en: "If I have insurance later, which plans do you take?", review: true },
  // C4b item 7: the ER reference, collapsed, never ranked
  "er.summary": { en: "For comparison: the ER" },
  "er.range": { en: "At the ER the visit alone usually costs {range}, before any tests.", review: true },
  "er.hospital_part_only": {
    en: "This covers the hospital's part; the doctor's part is not published for every level here, so the real cost is higher.",
    review: true,
  },
  "er.not_published": { en: "ER prices for this way of paying are not published.", review: true },
  "er.never_ranked": { en: "Shown for comparison only. The ER is not one of the places above.", review: true },
  "er.level": { en: "Level {n}" },
  "er.hospital_part": { en: "hospital" },
  "er.doctor_part": { en: "doctor" },
  // item 8: open now, and which field it comes from
  "hours.from_posted": { en: "Hours: the place's posted hours" },
  "hours.from_site_page": { en: "Hours: the place's own web page" },
  "hours.from_live": { en: "Hours: live from the place's own check-in page" },
  "hours.may_close_early": { en: "Hours: posted, but the place says it may close early" },
  "hours.unknown": { en: "Hours not listed. Call before you go." },
  "map.item_headline": { en: "Whole visit" },
  "map.item_option": { en: "Option {letter}: whole visit" },
  "map.headline_for": {
    en: "Prices on the map: what seeing a doctor for this costs at each place ({option}). One item at a time.",
    review: true,
  },
  "tab.pick": { en: "Where to go" },
  "tab.receipt": { en: "Breakdown" },
  "tab.list": { en: "List" },
  "tab.map": { en: "Map" },
  "tab.browse": { en: "Browse" },

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
