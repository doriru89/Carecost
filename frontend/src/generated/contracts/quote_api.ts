// GENERATED from contracts/quote_api.schema.json by `python -m app.api_contracts`. Do not edit.
// A drift test (backend/tests/contracts) fails when this file is stale.

/**
 * C3 item 12: 'with typical time, about $Y'. Anesthesia is paid (base units + minutes / 15)
 * x a conversion factor; the summed line has the base units only. Never summed.
 */
export interface AnesthesiaTime {
  minutes: number;
  base_units: number;
  low: number;
  high: number;
  /**
   * the public CMS file the typical minutes come from
   */
  source: string;
}

/**
 * which part of the bill
 */
export type BillComponent = "facility" | "professional" | "drug" | "supply" | "unknown";

/**
 * D7: links only. The app never posts to these systems and never scrapes them.
 */
export interface BookingOption {
  kind: "deep_link" | "iframe_mgb" | "walk_in" | "call";
  provider: "on_my_way" | "solv" | "clockwise" | "zocdoc" | "mychart_open_scheduling" | "operator_site" | "phone" | "none";
  /**
   * Button text, e.g. 'Reserve a spot'
   */
  label: string;
  url: string | null;
  phone: string | null;
}

export interface CarePathRef {
  id: string;
  version: string;
  title: string;
  /**
   * Not 'approved' -> the UI shows a draft banner
   */
  review_status: "pending_austin" | "changes_requested" | "approved";
}

export interface CashPayment {
  kind: "cash";
}

export type Cell = Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict;

/**
 * D8 display gradient
 */
export type CertaintyTier = "certain" | "likely" | "possible" | "not_in_public_data";

/**
 * C3 R12: within one chain, the same line under the same payer differs by more than the
 * engine.yaml limit (1.5x): flagged for review, both ends named.
 */
export interface ChainSpread {
  chain_id: string;
  /**
   * step key / component / code / modifier
   */
  key: string;
  low_site_id: string;
  low: number;
  high_site_id: string;
  high: number;
  ratio: number;
}

/**
 * Rung 8: ordering only, no dollars (CHIA relative price).
 */
export interface ChiaBadge {
  payer_id: string;
  band: "top_quarter" | "above_median" | "below_median" | "bottom_quarter";
  report_year: number;
}

/**
 * Two sources disagree; both numbers are shown.
 */
export interface Conflict {
  kind: "conflict";
  a: Money;
  b: Money;
}

export interface Coordinates {
  /**
   * Greater Boston scope guard
   */
  lat: number;
  lon: number;
  geocoded_by: "census_batch" | "operator_page" | "manual" | "hospital_registry";
  geocoded_at: string;
}

/**
 * One entry of data/etl/data_quality_notices.yaml (written by people, never by the AI).
 */
export interface DataNotice {
  id: string;
  /**
   * e.g. content_changed_date_unchanged
   */
  kind: string;
  source_id: string;
  observed: string;
  detail: string;
  effect: string | null;
}

/**
 * Shown in 'Sources & dates'. Lets the UI say how old the whole answer is.
 */
export interface DataVersion {
  /**
   * ETL build id, e.g. 20261024-1cb8089d
   */
  build_id: string;
  build_date: string;
  /**
   * e.g. tic-2026-10; None = TiC not loaded yet
   */
  tic_release: string | null;
  sites_version: number;
  care_paths_version: string | null;
}

/**
 * Present on professional lines priced by the 8-rung ladder (plan §2.4, D5, D6).
 */
export interface DoctorFee {
  /**
   * None only for self-pay (no public source)
   */
  rung: number | null;
  explanation_key: "fee.rung_1_npi" | "fee.rung_2_group" | "fee.rung_3_hospital_file" | "fee.rung_4_masshealth" | "fee.rung_5_medicare" | "fee.rung_6_estimate" | "fee.rung_7_medicare_reference" | "fee.rung_8_chia_badge" | "fee.self_pay_no_source";
  /**
   * Physician group, e.g. 'MGPO'
   */
  group_name: string | null;
  group_tin: string | null;
  npi_count: number | null;
  chia_badge: ChiaBadge | null;
  /**
   * D6: per doctor when the NPI is known and prices differ
   */
  by_npi: NpiPrice[] | null;
}

/**
 * A site that does offer a service this site does not. The browser picks the nearest.
 */
export interface ElsewhereOption {
  site_id: string;
  site_name: string;
  lat: number;
  lon: number;
  cell: Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict;
}

export interface ErHospital {
  site_id: string;
  name: string;
  distance_km: number;
  levels: ErLevel[];
}

export interface ErLevel {
  /**
   * ED visit level (99283 = 3 ... 99285 = 5)
   */
  code: string;
  facility: Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict;
  doctor: Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict;
}

/**
 * C4b item 7 (Austin: "急诊应该是一上来医生就贵"): the nearest hospitals' ER visit levels 3-5,
 * facility + doctor, under this payment. Response level only: never ranked, never a site's
 * price. low = the cheapest level-3 sum, high = the dearest level-5 sum (doctor part only where
 * it is published: includes_doctor).
 */
export interface ErReference {
  status: "priced" | "not_published" | "not_loaded";
  note_key: "er.visit_alone_costs_more";
  codes: string[];
  low: number | null;
  high: number | null;
  includes_doctor: boolean;
  hospitals: ErHospital[];
}

export interface ExcludedLine {
  line_id: string;
  reason: "possible_tier" | "ai_suggested" | "no_dollar_amount" | "conflict" | "not_offered_here" | "repeats" | "reference_only" | "availability_unknown" | "unusual" | "flat_visit_rate";
}

/**
 * why a line is not summed
 */
export type ExcludedReason = "possible_tier" | "ai_suggested" | "no_dollar_amount" | "conflict" | "not_offered_here" | "repeats" | "reference_only" | "availability_unknown" | "unusual" | "flat_visit_rate";

/**
 * How current one source is, from two sides that must never be confused (Austin, 2026-10-24).
 *
 * (a) Source side -- ``late_to_refresh``: the publisher (hospital, insurer, agency, clinic) is
 *     past its own deadline. Shown to users as "late to refresh"; the data is still shown.
 * (b) Our side -- ``stale_on_our_side``: OUR last successful fetch/check is older than our own
 *     schedule. That is our fault, never the publisher's; the UI and /our-data say so.
 *
 * Rule: we only call a publisher late when our own check is current. If we are stale we do not
 * know whether they published since, so ``late_to_refresh`` must be False.
 * Build these with ``Freshness.compute`` so every producer applies the same cadences.
 */
export interface Freshness {
  /**
   * (a) The source's own date: file last_updated_on, fee schedule effective date, date printed on a clinic page. None = the source states no date.
   */
  last_updated: string | null;
  /**
   * (a) When the publisher owed a newer version under source_rule. None = no deadline.
   */
  expected_by: string | null;
  /**
   * (a) publisher past its deadline (and our check is current)
   */
  late_to_refresh: boolean;
  source_rule: "hospital_mrf_365_days" | "tic_45_days" | "fee_schedule_annual" | "fee_schedule_quarterly" | "posted_page_date_365_days" | "no_publisher_deadline";
  /**
   * (b) our last successful fetch / check of this source
   */
  fetched_at: string;
  /**
   * (b) when our next fetch/check was due under our_rule. None = no newer release known.
   */
  our_refresh_due: string | null;
  /**
   * (b) we are behind our own schedule
   */
  stale_on_our_side: boolean;
  our_rule: "hospital_monthly" | "tic_monthly" | "nppes_monthly" | "sites_weekly" | "fee_schedule_per_release";
}

export type Gap = NotPublished | NotLoaded | NoSource | PercentOnly | Conflict;

/**
 * C3 (item 9): what a list row shows without the full receipt (receipt.totals when it is
 * present, copied).
 */
export interface Headline {
  likely_low: number | null;
  likely_high: number | null;
  includes_estimate: boolean;
  complete: boolean;
  missing: number;
  comparable: number | null;
  real_steps: number;
  might_add: MightAdd | null;
}

/**
 * C4b item 1 (Austin 2026-10-25): what seeing a doctor for this probably costs here. The range
 * covers the certain and likely steps only: low = the sum of their lows, high = the sum of their
 * highs (this site's own price, or the elsewhere range where it does not do the step). Possible
 * steps are not in it: they are listed in ``may_also_order``. Three subtotals for the breakdown:
 * visit_only (the first visit with all its bills), with_likely (= this range), with_possible
 * (+ possible steps; of one exclusive_group only the dearest member counts).
 */
export interface HeadlineRange {
  low: number;
  high: number;
  /**
   * = with_likely.includes
   */
  includes: string[];
  /**
   * completeness of this figure (see HeadlineBasis)
   */
  basis: "complete" | "includes_estimate" | "partial";
  /**
   * C4b 3b: the visit's doctor fee has no public source (self-pay at a hospital clinic): show 'from $low', with note_keys
   */
  from_only: boolean;
  /**
   * doctor_bills_separately: the doctor's bill has no public source (self-pay); doctor_bill_not_published (C4c): the insurer's file has no rate for it
   */
  note_keys: ("headline.doctor_bills_separately" | "headline.doctor_bill_not_published")[];
  /**
   * the first visit's step(s)
   */
  visit_step_keys: string[];
  visit_only: Subtotal;
  with_likely: Subtotal;
  with_possible: Subtotal;
  may_also_order: MayAlsoOrder[];
}

export interface Hours {
  source: "on_my_way" | "operator_html" | "operator_schema_org" | "manual";
  source_url: string | null;
  checked_at: string;
  /**
   * Empty = by appointment / unknown
   */
  weekly: HoursSpan[];
  /**
   * Operator warns hours vary with clinical capacity
   */
  may_close_early: boolean;
}

export interface HoursSpan {
  days: ("mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun")[];
  opens: string;
  closes: string;
}

export interface InsurancePayment {
  kind: "insurance";
  /**
   * payer_aliases.yaml id, e.g. BCBS_MA
   */
  payer_id: string;
  /**
   * payer_aliases.yaml `products`: HMO, PPO, POS, EPO ...
   */
  product: string;
  /**
   * Optional named network inside the product (TiC network id), e.g. hmo_blue
   */
  network: string | null;
}

/**
 * doctor-fee copy key
 */
export type LadderExplanation = "fee.rung_1_npi" | "fee.rung_2_group" | "fee.rung_3_hospital_file" | "fee.rung_4_masshealth" | "fee.rung_5_medicare" | "fee.rung_6_estimate" | "fee.rung_7_medicare_reference" | "fee.rung_8_chia_badge" | "fee.self_pay_no_source";

export interface LearnMore {
  label: string;
  url: string;
}

/**
 * care path likelihood_tier
 */
export type Likelihood = "certain" | "likely" | "possible" | "rare";

export interface LocalLabel {
  en: string;
  zh: string;
}

/**
 * MassHealth fee-for-service rates. ACO / MCO plans may pay differently (shown as a note).
 */
export interface MassHealthPayment {
  kind: "masshealth";
}

/**
 * C4b (Austin 2026-10-25): a possible step, listed on its own under the headline: 'the doctor
 * may also order'. Never in the headline range.
 */
export interface MayAlsoOrder {
  step_key: string;
  plain_name: string;
  /**
   * its plain purpose, from the care path
   */
  why: string | null;
  low: number | null;
  high: number | null;
  figure: "own" | "estimate" | "elsewhere" | "elsewhere_estimate" | "none";
  exclusive_group: string | null;
  /**
   * C4c: 'from $low', the doctor bills apart
   */
  from_only: boolean;
}

/**
 * Traditional Medicare (FFS). Medicare Advantage is an InsurancePayment (e.g. HUMANA).
 */
export interface MedicarePayment {
  kind: "medicare";
}

/**
 * How the number in a ``Money`` was obtained.
 */
export type Method = "stated" | "derived_pct_x_gross" | "computed_fee_schedule" | "per_unit_x_base_units" | "estimate_peer_range";

export interface MightAdd {
  low: number;
  high: number;
  step_keys: string[];
}

export interface Money {
  kind: "money";
  low: number;
  high: number;
  basis: PriceBasis;
  /**
   * The row the low end comes from
   */
  prov: Provenance;
  /**
   * The row the high end comes from. Required on a range (low < high), absent on a point, so both ends of every range are cited (P1 problem 2). May name another file of the same kind (BCBS publishes HMO Blue as a fully- and a self-insured file).
   */
  prov_high: Provenance | null;
}

/**
 * Where to look from (C2, 208 sites). The browser sends the point the person chose; it is
 * used only to pick the closest sites and is never stored or logged.
 */
export interface Near {
  /**
   * Greater Boston scope guard (as Coordinates)
   */
  lat: number;
  lon: number;
}

/**
 * No public source exists at all (e.g. self-pay physician fee).
 */
export interface NoSource {
  kind: "no_source";
  what: string;
  ask: string;
}

/**
 * A source exists and we have not imported it yet (e.g. UHC TiC).
 */
export interface NotLoaded {
  kind: "not_loaded";
  what: string;
  eta: string | null;
}

/**
 * The source type exists but this provider did not list this item (in dollars).
 */
export interface NotPublished {
  kind: "not_published";
  what: string;
  ask: string;
  searched: Searched;
}

export interface NpiPrice {
  npi: string;
  /**
   * Public NPPES name; None when only an NPI block is known
   */
  display_name: string | null;
  money: Money;
}

/**
 * min low .. max high of one subtotal over an option's sites in this response.
 */
export interface OptionSpan {
  low: number;
  high: number;
  /**
   * plain names any of its sites counts, path order
   */
  includes: string[];
}

/**
 * Range bar (PriceRangeBar.tsx): same service, same site, every payer we have + cash.
 */
export interface OtherPayerRange {
  line_id: string;
  code: string;
  points: PayerPoint[];
  /**
   * Self-pay price at this site if known; None = not asked
   */
  cash: Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict | null;
  /**
   * Whether the person's own payer is one of the points
   */
  yours: "in_points" | "not_in_points";
}

/**
 * (b) our own refresh schedule
 */
export type OurCadence = "hospital_monthly" | "tic_monthly" | "nppes_monthly" | "sites_weekly" | "fee_schedule_per_release";

/**
 * Future /our-data page: every registered source, both sides, so Austin can tell 'we forgot
 * to update' (stale_on_our_side) from 'the publisher did not publish' (late_to_refresh).
 */
export interface OurDataResponse {
  as_of: string;
  sources: Record<string, SourceInfo>;
}

export interface PayerPoint {
  /**
   * None when the file's payer is not mapped to a registry id
   */
  payer_id: string | null;
  /**
   * Payer + plan as shown, e.g. 'Harvard Pilgrim · self-insured'
   */
  label: string;
  product: string | null;
  money: Money;
}

export type Payment = InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment;

/**
 * C3 (R4, P4, P5, X2): the same line's (or step's) real prices at other sites of the same
 * kind, under the same payer and plan product, one value per distinct billing group (TIN).
 * low / high = p25 / p75 (nearest rank, so each end is a real price); median = the neutral
 * figure ranking uses, so an estimate can neither help nor hurt a site.
 */
export interface PeerRange {
  low: number;
  high: number;
  median: number;
  /**
   * distinct billing groups (TINs / files) behind it
   */
  n_groups: number;
  /**
   * kind of the peer sites; None = every kind (P4)
   */
  kind: "urgent_care" | "office" | "hospital_outpatient" | "ambulatory_surgery_center" | null;
  /**
   * same_system: the site's own health system's groups
   */
  scope: "same_kind" | "same_system" | "payer_network";
  /**
   * whose rates; None for self-pay / fee schedules
   */
  payer_id: string | null;
}

/**
 * Only 'X% of charges' is published and the base charge is not.
 */
export interface PercentOnly {
  kind: "percent_only";
  pct: number;
  of: string;
  searched: Searched;
}

/**
 * D7: the health system's patient portal (MyChart, MGB Patient Gateway). Link only.
 */
export interface PortalLink {
  kind: "mychart" | "patient_gateway";
  /**
   * e.g. mgb, bilh, bmc
   */
  system_id: string;
  label: string;
  url: string;
}

/**
 * What the amount *is* (as opposed to how we got it).
 */
export type PriceBasis = "negotiated" | "gross" | "discounted_cash" | "min_negotiated" | "max_negotiated" | "median_allowed" | "fee_schedule" | "posted_self_pay" | "estimate";

export interface Provenance {
  /**
   * Sources registry id. The UI's source chip is derived from this (never stored separately), so a number cannot sit next to another file's chip.
   */
  source_id: string;
  source_kind: SourceKind;
  /**
   * Basename only; never an absolute or relative path.
   */
  source_file: string;
  source_sha256: string;
  /**
   * The file's own last_updated_on (ISO).
   */
  source_date: string | null;
  method: Method;
  /**
   * <source_id>:<sha256[:12]>:<staged row ordinal>
   */
  row_ref: string;
  /**
   * Whose rate this is (payer_aliases.yaml id) for payer-specific rows (hospital MRF payer rows, TiC); None for fee schedules, cash and chargemaster prices. Lets the quote check that a BCBS receipt only sums BCBS rates.
   */
  payer_id: string | null;
  /**
   * RateRow.row_id (<nk_hash>:<nk_ordinal>), unique per build. Required on insurer TiC numbers: one TiC price row (one row_ref) is shared by every provider group listed with it, so only row_id says which group's number this is (P1 problem 1).
   */
  row_id: string | null;
}

/**
 * C4b (D-UI-3): where to go first, option A or B (e.g. urgent care vs a skin doctor), each
 * with its own range. ``priced: false`` = listed but not priced yet (no sites).
 */
export interface QuoteOption {
  id: string;
  label: LocalLabel;
  visit_step: string | null;
  /**
   * a specialist visit: an HMO may need a referral first
   */
  specialist: boolean;
  priced: boolean;
  missing_reason: string | null;
  /**
   * sites of this option in this response
   */
  site_count: number;
  /**
   * of them, with a headline_range
   */
  sites_with_range: number;
  /**
   * = with_likely.low
   */
  low: number | null;
  /**
   * = with_likely.high
   */
  high: number | null;
  includes: string[];
  visit_only: OptionSpan | null;
  with_likely: OptionSpan | null;
  with_possible: OptionSpan | null;
  /**
   * Austin 2026-10-25: the site with the lowest headline low within the best completeness basis present (ties: nearest)
   */
  cheapest_site_id: string | null;
  /**
   * the basis of that site's figure: 'complete' = its own published prices; 'partial' = only partial prices are available in this option
   */
  cheapest_basis: "complete" | "includes_estimate" | "partial" | null;
  /**
   * C4c: the best basis present; low / high / the spans come from those sites only
   */
  basis: "complete" | "includes_estimate" | "partial" | null;
  /**
   * C4c: sites with a range, per basis
   */
  sites_by_basis: Record<string, number>;
  /**
   * C4c: sites with only partial prices ('plus N places ...')
   */
  partial_site_count: number;
  /**
   * C4c: a path without entry options gets one implicit option (all its sites), so cheapest_site_id exists; the list keeps its rank / kind_then_distance ordering
   */
  implicit: boolean;
}

export interface QuoteRequest {
  payment: InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment;
  care_path_id: string | null;
  /**
   * Chip answers keyed by questions.yaml id (Q14 -> referral layer, tier modifiers). Ids and values only; never free text.
   */
  answers: Record<string, string[]>;
  /**
   * D3 manual picker: CPT/HCPCS codes from the catalog
   */
  service_codes: string[];
  picked_by: "person" | "assistant";
  /**
   * Only these sites; None = every site that offers the services. A children-only site is quoted only when named here (D27)
   */
  site_ids: string[] | null;
  /**
   * C2: quote the max_sites sites closest to this point (straight-line distance), ranked (I7). None (P7) = every admitted site, grouped by kind of site and ordered by distance from Boston City Hall
   */
  near?: Near | null;
  /**
   * With `near`: at most this many (the closest) sites. Ignored without `near`
   */
  max_sites?: number;
  /**
   * C4b (D-UI-1): for a care path with entry options, sites are grouped by option and ordered by distance (None = distance) or by price (rank_key). Paths without options keep `rank` (with `near` / site_ids) or `kind_then_distance`
   */
  order_by?: "distance" | "price" | null;
  /**
   * C3: without `near` and `site_ids`, the first N sites carry their full receipt (C4b: the first N of each entry option); the rest carry the summary (headline + steps) and are fetched by `site_ids`
   */
  full_receipts?: number;
}

export interface QuoteResponse {
  payment: InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment;
  /**
   * P2: how the payment is named to a person; cash is 'Self-pay (no insurance)'
   */
  payment_label: LocalLabel;
  care_path: CarePathRef | null;
  service_codes: string[];
  picked_by: "person" | "assistant";
  /**
   * The day freshness was computed for (per request, not build)
   */
  as_of: string;
  data_version: DataVersion;
  /**
   * Every source behind a number or a 'not published' claim in this response, stored once (P2); lines point here by prov.source_id / searched.source_id
   */
  sources: Record<string, SourceInfo>;
  /**
   * ordering rank: by rank_key (I7); kind_then_distance: by kind_distance_key (P7)
   */
  sites: SiteQuote[];
  /**
   * C3 P7: rank with a point or named sites, else by kind
   */
  ordering: "rank" | "kind_then_distance" | "option_then_distance" | "option_then_price";
  /**
   * where distance_km is measured from (the point, or City Hall)
   */
  origin: Near | null;
  /**
   * C3 R12: same chain, same line, prices > 1.5x apart
   */
  chain_spreads: ChainSpread[];
  /**
   * Sites filtered out because they offer none of it
   */
  sites_without_service: string[];
  /**
   * D33: a quote reached from a care path carries both fixed lines (common causes, not a diagnosis; when to see a doctor); a manual pick carries none (P1 problem 13)
   */
  copy_keys: ("copy.not_a_diagnosis" | "copy.when_to_see_a_doctor")[];
  /**
   * C4b hmo_referral_for_specialist: the person's plan may need a referral (Q14) and an option is a specialist visit: shown at the top, not inside a receipt
   */
  notices: ("care_path_draft" | "tic_not_loaded" | "late_to_refresh_sources" | "stale_on_our_side_sources" | "masshealth_aco_may_differ" | "medicare_advantage_is_insurance" | "chain_price_spread" | "hmo_referral_for_specialist")[];
  /**
   * C4b: entry options A / B (empty: one option)
   */
  options: QuoteOption[];
  /**
   * C4b: the ER visit for comparison (care path quotes)
   */
  er_reference: ErReference | null;
}

export interface Receipt {
  lines: ReceiptLine[];
  totals: Totals;
}

export interface ReceiptLine {
  line_id: string;
  tier: "certain" | "likely" | "possible" | "not_in_public_data";
  likelihood: "certain" | "likely" | "possible" | "rare";
  /**
   * care path step
   */
  step_id: string | null;
  /**
   * technical detail only, never the label
   */
  codes: string[];
  modifier: string | null;
  /**
   * Primary label (D8)
   */
  plain_name: string;
  /**
   * Small text (D8), e.g. 'Shoulder X-ray'
   */
  technical_name: string;
  /**
   * One sentence, from the care path; None on manual picks
   */
  why: string | null;
  glossary_keys: string[];
  component: "facility" | "professional" | "drug" | "supply" | "unknown";
  /**
   * False when the price file does not say facility vs professional (e.g. CHA)
   */
  component_confirmed: boolean;
  unit: "once" | "per_visit" | "per_15_minutes";
  availability: "offered" | "not_offered" | "unknown";
  /**
   * C3 P6: why the line is not offered; None exactly when offered
   */
  availability_reason: "insurer_lists_rate" | "price_file_lists_rate" | "no_evidence" | "site_says_not_offered" | null;
  /**
   * None only when availability == not_offered
   */
  cell: Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict | null;
  /**
   * The gross charge (chargemaster list price), shown on its own row and never summed. Never the line's price: almost nobody pays it.
   */
  list_price: Money | null;
  tier_basis: "guideline" | "plan_rule" | "our_judgment" | "picked";
  doctor_fee: DoctorFee | null;
  ai_suggested: boolean;
  in_total: boolean;
  /**
   * Cheapest sites that offer it, when not offered here
   */
  elsewhere: ElsewhereOption[];
  learn_more: LearnMore[];
  /**
   * C2: fixed copy keys that explain how the line's number was made (e.g. a Medicare national rate not adjusted for Boston wages). Empty = nothing to add
   */
  price_notes: ("price.national_unadjusted" | "price.anesthesia_base_units_only" | "price.group_consistently_higher" | "price.group_consistently_lower" | "price.flat_visit_rate" | "price.several_rates_same_doctors" | "price.anesthesia_typical_time")[];
  /**
   * C3 (P5): the peer range behind an estimated cell (basis estimate); None otherwise
   */
  estimate: PeerRange | null;
  /**
   * C3 (P8): rows outside 1/3x-3x of the peer median
   */
  unusual: UnusualPrice | null;
  /**
   * C3: the anesthesia fee with a typical time (never summed)
   */
  anesthesia_time: AnesthesiaTime | null;
  /**
   * C3 R12: the price is the chain's posted self-pay price, published on this site's page (it applies at every location of the chain)
   */
  chain_price_from: string | null;
  /**
   * Where this part of the care happens. your_primary_care: an HMO referral visit happens at the person's own primary care office, not at this site; the price is a range over the primary care groups we have, never this site's (P1 problem 15)
   */
  at: "this_site" | "your_primary_care";
}

/**
 * Which file we looked in. Lets a test re-run the lookup, so "the hospital did not publish
 * it" cannot hide our own lookup bug (a missed alias, a wrong code).
 */
export interface Searched {
  source_id: string;
  source_sha256: string;
}

export interface SiteQuote {
  site: SiteSummary;
  /**
   * C4b: the entry option this site is in
   */
  option_id: string | null;
  headline: Headline;
  /**
   * C4b: the range a person reads first; None when the first visit has no figure
   */
  headline_range: HeadlineRange | null;
  /**
   * C3 (P3): one per step of the quote, in path order
   */
  steps: StepSummary[];
  /**
   * From the request's point, or from Boston City Hall when there is none (P7)
   */
  distance_km: number | null;
  /**
   * C3: None for a site past `full_receipts` in a no-location list; ask for it with `site_ids`
   */
  receipt: Receipt | null;
  other_payers: OtherPayerRange[];
}

export interface SiteSummary {
  site_id: string;
  name: string;
  site_type: "urgent_care" | "hospital_outpatient" | "ortho_walk_in" | "specialist_office" | "primary_care_office" | "imaging_center" | "ambulatory_surgery_center";
  system_id: string | null;
  coords: Coordinates;
  address_line: string;
  phone: string | null;
  billing_type: "office_visit" | "hospital_outpatient" | "asc" | "unknown";
  booking: BookingOption[];
  portal_links: PortalLink[];
  hours: Hours | null;
  /**
   * site_page_hours (C4c): hours read from the site's own web page (site facts, agreed by two independent reads or reviewed by Austin)
   */
  hours_label: "live_by_operator" | "posted_hours" | "may_close_early" | "site_page_hours" | "unknown";
  price_label: "price_file" | "posted_price" | "price_on_request" | "mixed";
  /**
   * The site's own price source (its hospital MRF or posted page); its freshness is QuoteResponse.sources[price_source_id]. None = the site has its own price source but we do not read it yet (e.g. a clinic's self-pay page): its lines are not_loaded (P1 problem 9)
   */
  price_source_id: string | null;
  /**
   * registry_only sites are never quoted (to-verify queue, D27)
   */
  listing_status: "web_verified" | "multi_registry";
  service_areas: ("ortho" | "skin" | "gi" | "urgent_care")[];
  /**
   * X2 / P7: the kind of site (engine.yaml kind_by_billing)
   */
  kind: "urgent_care" | "office" | "hospital_outpatient" | "ambulatory_surgery_center";
  /**
   * C3 R12: the chain whose posted prices apply here
   */
  chain_id: string | null;
  /**
   * C4b: the chain's name as a person reads it, e.g. 'AFC Urgent Care'
   */
  chain_name: string | null;
  /**
   * Pediatric-only site (D27)
   */
  children_only: boolean;
  /**
   * C2: data-quality notices about this site's own price file (data/etl/data_quality_notices.yaml), e.g. its content changed but its date did not
   */
  data_notices: DataNotice[];
}

/**
 * (a) publisher deadline rule
 */
export type SourceCadence = "hospital_mrf_365_days" | "tic_45_days" | "fee_schedule_annual" | "fee_schedule_quarterly" | "posted_page_date_365_days" | "no_publisher_deadline";

/**
 * One source, stored once per response (P2). Every number points at it by
 * ``prov.source_id``; that is its chip. The chip copy key is ``source.<source_kind>``.
 */
export interface SourceInfo {
  source_kind: SourceKind;
  /**
   * Who published it, e.g. 'Mount Auburn Hospital', 'BCBS MA', 'CMS'
   */
  publisher: string;
  /**
   * Both sides, computed on the response's as_of: (a) publisher late to refresh, (b) stale on our side
   */
  freshness: Freshness;
}

export type SourceKind = "hospital_mrf" | "insurer_tic" | "medicare_pfs" | "medicare_opps" | "medicare_asc" | "masshealth_fs" | "clinic_posted" | "chia_rp";

/**
 * C3 (P3, item 10): one step at one site, so the map can show one selected service's price.
 * low / high: the step's summed lines here (own / estimate) or the elsewhere range.
 */
export interface StepSummary {
  /**
   * care path step id, or the codes of a manual pick
   */
  key: string;
  step_id: string | null;
  /**
   * C4b: the step's plain name (map label)
   */
  plain_name: string;
  likelihood: "certain" | "likely" | "possible" | "rare";
  availability: "offered" | "not_offered" | "unknown";
  figure: "own" | "estimate" | "elsewhere" | "elsewhere_estimate" | "none";
  low: number | null;
  high: number | null;
  /**
   * the neutral figure in `comparable` (None: not counted)
   */
  rank_value: number | null;
  estimated: boolean;
  /**
   * a line of the step was set aside as unusual (P8)
   */
  unusual: boolean;
  /**
   * the step's lines are in totals.likely
   */
  in_total: boolean;
  /**
   * counted in totals.missing
   */
  missing: boolean;
  line_ids: string[];
  /**
   * P4: the step's price at sites that do it (same payer)
   */
  elsewhere: PeerRange | null;
  /**
   * C4b: this insurer pays this place one amount per visit and lists it on this step's code too: the step adds $0 here (low = high = 0), 'the test may be included'
   */
  flat_visit_rate: boolean;
  /**
   * C4c: 'from $low': the hospital's bill is priced, the doctor's bill has no number (no public source / not published). Still counted in `missing`, never in the ranking figure
   */
  from_only: boolean;
}

/**
 * C4b (D-UI-2): one scenario of the breakdown. low / high = the first visit's low / high plus
 * the low / high of every step in ``step_keys`` (its StepSummary figure: this site's own price,
 * an estimate, or the elsewhere range; a flat-rate step adds $0).
 */
export interface Subtotal {
  low: number;
  high: number;
  /**
   * the steps counted on top of the first visit
   */
  step_keys: string[];
  /**
   * their plain names, in the same order: 'includes: belly CT, blood tests'
   */
  includes: string[];
  /**
   * steps of this scenario with no figure (not counted)
   */
  not_priced: string[];
  /**
   * exclusive_group members left out because a dearer alternative is counted
   */
  alternatives: string[];
  /**
   * an estimate or an elsewhere range is in it
   */
  estimated: boolean;
}

/**
 * A sum of line Money values. Not a ``Money``: a sum has no single Provenance; each part's
 * provenance stays on its line (``line_ids``).
 */
export interface SummedAmount {
  low: number;
  high: number;
  line_ids: string[];
  /**
   * Derived: a peer estimate (estimate_peer_range) is in the sum
   */
  includes_estimate: boolean;
  /**
   * Derived: a summed price's source is late to refresh (publisher side)
   */
  includes_late_source: boolean;
  /**
   * Derived: we are behind on refreshing a summed price's source (our side)
   */
  includes_stale_source: boolean;
}

/**
 * what a line's likelihood rests on
 */
export type TierBasis = "guideline" | "plan_rule" | "our_judgment" | "picked";

export interface Totals {
  /**
   * certain + likely Money lines with in_total; None when nothing can be summed. Shown as what the care is billed at (you plus your plan), not as what you owe.
   */
  likely: SummedAmount | null;
  /**
   * False when a certain/likely line has no dollar amount (the total is a floor)
   */
  complete: boolean;
  /**
   * Derived (I7, C3): expected (certain/likely, non-AI) steps with no figure here (no own price, no estimate, no 'elsewhere' range) although some admitted site has a price for that step: one per step, not per line. A step nobody has a price for is not counted (it is the same everywhere). Counted over every admitted site, never over the response
   */
  missing: number;
  excluded: ExcludedLine[];
  you_pay: YouPay;
  /**
   * C3 (P1, P4): the ranking figure: this site's real prices (each line's median row) plus estimates and steps done elsewhere at their neutral peer median; steps with no figure are left out (they count in `missing`). None when no step has a figure
   */
  comparable: number | null;
  /**
   * C3: expected steps priced from this site's own real prices
   */
  real_steps: number;
  /**
   * C3 (P9): possible steps this site offers, 'might add $X-$Y' (X = the cheapest one, Y = all of them); never in `likely`
   */
  might_add: MightAdd | null;
}

/**
 * C3 P8: a price more than 3x or less than 1/3x the same line's peer median (same payer,
 * same kind of site). Rows outside the band are set aside (shown, never summed); when every row
 * is outside, the whole line is unusual and not summed: "price looks unusual, being checked".
 */
export interface UnusualPrice {
  peer_median: number;
  n_groups: number;
  whole_line: boolean;
  /**
   * the rows left out of the line's range (cited)
   */
  set_aside: Money[];
}

/**
 * What the person actually owes depends on their plan; we say how, never guess the number.
 */
export interface YouPay {
  kind: "deductible_then_coinsurance" | "copay_or_deductible" | "medicare_20_percent" | "masshealth_small_or_no_copay" | "cash_full_amount";
  note_key: string;
  portal_label: string | null;
  /**
   * Insurer member portal, e.g. MyBlue
   */
  portal_url: string | null;
}
