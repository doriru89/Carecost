// GENERATED from contracts/quote_api.schema.json by `python -m app.api_contracts`. Do not edit.
// A drift test (backend/tests/contracts) fails when this file is stale.

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
 * Shown in 'Sources & dates'. Lets the UI say how old the whole answer is.
 */
export interface DataVersion {
  /**
   * ETL build id, e.g. 20261024-1cb8089d
   */
  build_id: string;
  build_date: string;
  /**
   * e.g. tic-2026-11; None = TiC not loaded yet
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
  multiple: Multiple | null;
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

export interface ExcludedLine {
  line_id: string;
  reason: "possible_tier" | "ai_suggested" | "no_dollar_amount" | "conflict" | "not_offered_here" | "repeats" | "reference_only";
}

/**
 * why a line is not summed
 */
export type ExcludedReason = "possible_tier" | "ai_suggested" | "no_dollar_amount" | "conflict" | "not_offered_here" | "repeats" | "reference_only";

/**
 * How current one data source is. Explicit fields, never free text.
 *
 * ``late_to_refresh`` is computed by whoever builds the payload (ETL / quote engine) as
 * ``as_of > expected_by``. A late source is still shown, with the "late to refresh" label.
 */
export interface Freshness {
  /**
   * The source's own date: file last_updated_on, fee schedule effective date, or the day a posted price was last checked. None = the source does not say.
   */
  last_updated: string | null;
  /**
   * When a newer version was due under `rule`. None = no deadline known.
   */
  expected_by: string | null;
  late_to_refresh: boolean;
  rule: "etl_warn_after_days" | "cms_annual" | "tic_monthly" | "fee_schedule_effective" | "posted_price_weekly_check" | "hours_weekly_check";
}

/**
 * how expected_by was set
 */
export type FreshnessRule = "etl_warn_after_days" | "cms_annual" | "tic_monthly" | "fee_schedule_effective" | "posted_price_weekly_check" | "hours_weekly_check";

export type Gap = NotPublished | NotLoaded | NoSource | PercentOnly | Conflict;

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

/**
 * MassHealth fee-for-service rates. ACO / MCO plans may pay differently (shown as a note).
 */
export interface MassHealthPayment {
  kind: "masshealth";
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
export type Method = "stated" | "derived_pct_x_gross" | "computed_fee_schedule" | "estimate_medicare_multiple" | "ai_drafted";

export interface Money {
  kind: "money";
  low: number;
  high: number;
  basis: PriceBasis;
  prov: Provenance;
}

/**
 * Rung 6: Medicare x the same group's own typical multiple (>= 5 matched codes, D5).
 */
export interface Multiple {
  low: number;
  high: number;
  n_codes: number;
  payer_id: string;
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
 * Only 'X% of charges' is published and the base charge is not.
 */
export interface PercentOnly {
  kind: "percent_only";
  pct: number;
  of: string;
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
  /**
   * Only these sites; None = every site that offers the services
   */
  site_ids: string[] | null;
}

export interface QuoteResponse {
  payment: InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment;
  care_path: CarePathRef | null;
  service_codes: string[];
  data_version: DataVersion;
  sites: SiteQuote[];
  /**
   * Sites filtered out because they offer none of it
   */
  sites_without_service: string[];
  notices: ("care_path_draft" | "tic_not_loaded" | "late_to_refresh_sources" | "masshealth_aco_may_differ" | "medicare_advantage_is_insurance")[];
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
   * None only when availability == not_offered
   */
  cell: Money | NotPublished | NotLoaded | NoSource | PercentOnly | Conflict | null;
  /**
   * One chip per number shown (two for a conflict)
   */
  sources: SourceChip[];
  doctor_fee: DoctorFee | null;
  ai_suggested: boolean;
  in_total: boolean;
  /**
   * Cheapest sites that offer it, when not offered here
   */
  elsewhere: ElsewhereOption[];
  learn_more: LearnMore[];
}

export interface SiteQuote {
  site: SiteSummary;
  receipt: Receipt;
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
  billing_type: "office_visit" | "hospital_outpatient" | "unknown";
  booking: BookingOption[];
  portal_links: PortalLink[];
  hours: Hours | null;
  hours_label: "live_by_operator" | "posted_hours" | "may_close_early" | "unknown";
  price_label: "price_file" | "posted_price" | "price_on_request" | "mixed";
  /**
   * Per site: the oldest price source behind this receipt ('late to refresh')
   */
  price_freshness: Freshness;
  service_areas: ("ortho" | "skin" | "gi" | "urgent_care")[];
}

/**
 * What the source chip on a line shows (hover text keys off source_kind, plan §2.2).
 */
export interface SourceChip {
  source_kind: SourceKind;
  /**
   * Who published it, e.g. 'Mount Auburn Hospital', 'BCBS MA', 'CMS'
   */
  publisher: string;
  /**
   * fixed copy key: source.<source_kind>
   */
  label_key: string;
  /**
   * Per data point: a stale price carries its own flag
   */
  freshness: Freshness;
  /**
   * price-file rows behind the number
   */
  rows: number | null;
}

export type SourceKind = "hospital_mrf" | "insurer_tic" | "medicare_pfs" | "medicare_opps" | "medicare_asc" | "masshealth_fs" | "clinic_posted" | "chia_rp" | "estimate" | "ai_potential";

/**
 * A sum of line Money values. Not a ``Money``: a sum has no single Provenance; each part's
 * provenance stays on its line (``line_ids``).
 */
export interface SummedAmount {
  low: number;
  high: number;
  line_ids: string[];
  /**
   * True when a rung-6 estimate is in the sum
   */
  includes_estimate: boolean;
  /**
   * True when a 'late to refresh' price is in it
   */
  includes_late_source: boolean;
}

export interface Totals {
  /**
   * certain + likely Money lines with in_total; None when nothing can be summed
   */
  likely: SummedAmount | null;
  /**
   * False when a certain/likely line has no dollar amount (the total is a floor)
   */
  complete: boolean;
  excluded: ExcludedLine[];
  you_pay: YouPay;
}

/**
 * What the person actually owes depends on their plan; we say how, never guess the number.
 */
export interface YouPay {
  kind: "deductible_then_coinsurance" | "medicare_20_percent" | "masshealth_small_or_no_copay" | "cash_full_amount";
  note_key: string;
  portal_label: string | null;
  /**
   * Insurer member portal, e.g. MyBlue
   */
  portal_url: string | null;
}
