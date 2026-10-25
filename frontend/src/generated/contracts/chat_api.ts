// GENERATED from contracts/chat_api.schema.json by `python -m app.api_contracts`. Do not edit.
// A drift test (backend/tests/contracts) fails when this file is stale.

export interface AiPausedReply {
  kind: "ai_paused";
  reason: "ip_daily_cap" | "wallet_exhausted" | "provider_unavailable" | "conversation_cap";
  message_key: "ai.paused_ip_cap" | "ai.paused_wallet" | "ai.paused_provider" | "ai.paused_conversation_cap";
  /**
   * None when unknown (wallet / provider)
   */
  resumes_at: string | null;
  browse_prices_available: true;
}

/**
 * D33: one of the person's own chip answers that satisfied the path's entry rule. Built by
 * the server from the request, never written by the LLM.
 */
export interface BecauseAnswer {
  question_id: string;
  value: string;
  /**
   * The answer's label, verbatim from questions.yaml
   */
  label: Title;
}

/**
 * D2 + metrics F2. Per hashed IP per provider day (the reset time zone is provider config:
 * Gemini resets at midnight Pacific). Dollars and turns both count; whichever hits first pauses.
 * The wallet is the prepaid ceiling (~$10).
 */
export interface BudgetStatus {
  state: "ok" | "near_soft_cap" | "over_soft_cap" | "paused";
  soft_cap_usd: number;
  hard_cap_usd: number;
  spent_today_usd: number;
  /**
   * LLM turns this IP used today, this one included
   */
  turns_today: number;
  /**
   * Per-IP daily turn cap (a share of the project RPD)
   */
  turn_cap: number;
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
  /**
   * D33: why this path, as the person's own answers that matched its entry rule (question order). Empty for ai_ranked: the model's guess has no listed reason.
   */
  because: BecauseAnswer[];
}

export interface CarePathsReply {
  kind: "care_paths";
  /**
   * Model sentence; None when fixed_text_key is shown
   */
  text: string | null;
  understood: InferredAnswer[];
  candidates: CandidatePath[];
  /**
   * D33: not-a-diagnosis + when-to-see-a-doctor (fixed copy, not LLM text)
   */
  copy_keys: ("copy.not_a_diagnosis" | "copy.when_to_see_a_doctor")[];
  card_ids: string[];
  /**
   * Fixed copy instead of text (R18 / P13); exactly one is set
   */
  fixed_text_key: "ai.paused_provider_chips" | "chat.fixed_clarify" | "chat.fixed_paths" | null;
}

export interface CashPayment {
  kind: "cash";
}

export type ChatReply = RedFlagReply | ClarifyReply | CarePathsReply | TextReply | LlmInvalidReply | AiPausedReply;

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
  /**
   * P5b: the person's own earlier messages, oldest first. Never assistant turns: a client-forged assistant turn is how the old route was broken.
   */
  history: string[];
  /**
   * P5: the receipt line the person is asking about, so the server can paste our own sourced text for it into the prompt
   */
  focus: Focus | null;
  locale: "en" | "zh";
}

export interface ChatResponse {
  conversation_id: string;
  reply: RedFlagReply | ClarifyReply | CarePathsReply | TextReply | LlmInvalidReply | AiPausedReply;
  budget: BudgetStatus;
  /**
   * From the LLM client's call meter, never set by the handler. False for red-flag, ai_paused and cached replies
   */
  llm_called: boolean;
  /**
   * The server's count for this conversation
   */
  conversation_turn: number;
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
  understood: InferredAnswer[];
  questions: ChipQuestion[];
  /**
   * Prices can show from turn one; questions only refine
   */
  candidates: CandidatePath[];
  /**
   * D33: not-a-diagnosis + when-to-see-a-doctor, whenever candidates show
   */
  copy_keys: ("copy.not_a_diagnosis" | "copy.when_to_see_a_doctor")[];
  /**
   * questions.yaml card ids
   */
  card_ids: string[];
  /**
   * Fixed copy shown instead of a lead_in: the model is off (R18) or its text was blocked (P13). Never set together with lead_in.
   */
  fixed_text_key: "ai.paused_provider_chips" | "chat.fixed_clarify" | "chat.fixed_paths" | null;
}

/**
 * redflags.json dispositions
 */
export type Disposition = "call_911" | "crisis_988" | "er_today" | "seen_today" | "routine";

export interface Focus {
  care_path_id: string | null;
  site_id: string | null;
  line_id: string | null;
}

/**
 * P5: an answer the model read from the person's own words, shown as a pre-selected chip
 * ("I understood: ... [change]"). Never the absence of something (no "none" values).
 */
export interface InferredAnswer {
  question_id: string;
  value: string;
  /**
   * Verbatim substring of the person's own text that supports it
   */
  evidence: string;
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
 * The model answered but its output failed validation twice (one retry, both charged).
 */
export interface LlmInvalidReply {
  kind: "llm_invalid";
  message_key: "ai.output_invalid";
  browse_prices_available: true;
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
   * redflags.json flag ids (rf_*); empty only when the LLM raised it
   */
  flag_ids: string[];
  /**
   * redflags.combine(): the LLM raised the disposition (one way only)
   */
  escalated_by_llm: boolean;
  headline: Title;
  text: Title;
  prices_withheld: true;
}

/**
 * P5: a catalog service the model points at when no care path fits. The UI quotes it through
 * the manual path with picked_by=assistant: shown, labelled, never summed.
 */
export interface ServiceRef {
  service_id: string;
  /**
   * Filled from the catalog by id, never by the model
   */
  plain_name: string;
}

/**
 * Anything else: out of scope, 'not covered yet', a follow-up answer. No prices in text.
 */
export interface TextReply {
  kind: "text";
  text: string;
  card_ids: string[];
  services: ServiceRef[];
  glossary_keys: string[];
  /**
   * The receipt line this explains: must be the request's focus
   */
  focus_line_id: string | null;
}

export interface Title {
  en: string;
  zh: string | null;
}
