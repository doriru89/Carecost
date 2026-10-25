// GENERATED from contracts/chat_api.schema.json by `python -m app.api_contracts`. Do not edit.
// A drift test (backend/tests/contracts) fails when this file is stale.

export interface AiPausedReply {
  kind: "ai_paused";
  reason: "ip_daily_cap" | "wallet_exhausted" | "provider_unavailable";
  message_key: "ai.paused_ip_cap" | "ai.paused_wallet" | "ai.paused_provider";
  /**
   * UTC; None when unknown (wallet / provider)
   */
  resumes_at: string | null;
  browse_prices_available: true;
}

/**
 * D2. Per hashed IP per UTC day; the wallet is the prepaid ceiling (~$10).
 */
export interface BudgetStatus {
  state: "ok" | "near_soft_cap" | "over_soft_cap" | "paused";
  soft_cap_usd: number;
  hard_cap_usd: number;
  spent_today_usd: number;
  wallet: "ok" | "low" | "exhausted";
  resets_at: string;
}

export interface CandidatePath {
  path_id: string;
  title: string;
  /**
   * entry_matched: the answers satisfy the path's entry rule (deterministic). ai_ranked: the LLM picked it from the catalog.
   */
  match: "entry_matched" | "ai_ranked";
  review_status: "pending_austin" | "changes_requested" | "approved";
}

export interface CarePathsReply {
  kind: "care_paths";
  text: string;
  candidates: CandidatePath[];
  card_ids: string[];
}

export interface CashPayment {
  kind: "cash";
}

export type ChatReply = RedFlagReply | ClarifyReply | CarePathsReply | TextReply | AiPausedReply;

export interface ChatRequest {
  /**
   * Opaque, issued by the server on the first reply; None on the first message
   */
  conversation_id: string | null;
  text: string;
  payment: InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment;
  /**
   * D2: required before AI use, deliberately unverified. The only personal field in any CareCost contract.
   */
  email: string;
  /**
   * Chip answers so far, questions.yaml id -> answer values (client keeps state)
   */
  answers: Record<string, string[]>;
  locale: "en" | "zh";
}

export interface ChatResponse {
  conversation_id: string;
  reply: RedFlagReply | ClarifyReply | CarePathsReply | TextReply | AiPausedReply;
  budget: BudgetStatus;
  /**
   * False for red-flag, ai_paused and cached replies
   */
  llm_called: boolean;
}

export interface ChipAnswer {
  value: string;
  label: Title;
}

export interface ChipQuestion {
  question_id: string;
  text: Title;
  multi: boolean;
  answers: ChipAnswer[];
}

export interface ClarifyReply {
  kind: "clarify";
  /**
   * Short assistant sentence before the chips
   */
  lead_in: string | null;
  questions: ChipQuestion[];
  /**
   * Prices can show from turn one; questions only refine
   */
  candidates: CandidatePath[];
  /**
   * questions.yaml card ids
   */
  card_ids: string[];
}

/**
 * redflags.json dispositions
 */
export type Disposition = "call_911" | "crisis_988" | "er_today" | "seen_today" | "routine";

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

export type Payment = InsurancePayment | MedicarePayment | MassHealthPayment | CashPayment;

/**
 * Full-page stop (plan §4.1). Copy is copied verbatim from redflags.json `dispositions`.
 */
export interface RedFlagReply {
  kind: "red_flag";
  disposition: "call_911" | "crisis_988" | "er_today" | "seen_today" | "routine";
  /**
   * redflags.json flag ids (rf_*)
   */
  flag_ids: string[];
  headline: Title;
  text: Title;
  prices_withheld: true;
}

/**
 * Anything else: out of scope, 'not covered yet', a follow-up answer. No prices in text.
 */
export interface TextReply {
  kind: "text";
  text: string;
  card_ids: string[];
}

export interface Title {
  en: string;
  zh: string | null;
}
