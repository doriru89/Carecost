/**
 * Mock mode: answers from the committed contract fixtures (contracts/fixtures/*.json), so the UI runs
 * before streams C and Chat merge. It never builds a number: a request with no matching fixture
 * throws NoMockData and the UI says so.
 *
 * Quote fixtures (stream C's engine on the committed extract): chronic shoulder pain × {BCBS MA HMO,
 * cash, Medicare}, and a manual pick of shoulder X-ray + shoulder MRI (73030, 73221) × MassHealth.
 *
 * Chat is a SCRIPT for demos, not the product's red-flag gate (that runs on the server, Chat stream):
 * crisis words -> the crisis_988 reply (copy verbatim from data/redflags/redflags.json), emergency
 * words -> the call_911 fixture, first message -> clarify, later turns -> care_paths. `#text`,
 * `#invalid` and `#paused` in a message return those fixtures.
 */
import type { Catalog } from "@/generated/contracts/catalog";
import type { ChatRequest, ChatResponse, RedFlagReply } from "@/generated/contracts/chat_api";
import type { QuoteRequest, QuoteResponse } from "@/generated/contracts/quote_api";
import type { CareCostApi } from "./client";
import { NoMockData } from "./errors";

function strip<T>(mod: { default: unknown }): T {
  const { _fixture, _schema, ...rest } = mod.default as Record<string, unknown>;
  void _fixture;
  void _schema;
  return structuredClone(rest) as T;
}

const QUOTES: Record<string, () => Promise<{ default: unknown }>> = {
  "BCBS_MA:HMO": () => import("../../../../contracts/fixtures/quote_bcbs_hmo_shoulder.json"),
  cash: () => import("../../../../contracts/fixtures/quote_cash_shoulder.json"),
  medicare: () => import("../../../../contracts/fixtures/quote_medicare_shoulder.json"),
};

/** Manual picks with a fixture: payment kind | sorted service codes */
const MANUAL_QUOTES: Record<string, () => Promise<{ default: unknown }>> = {
  "masshealth|73030,73221": () => import("../../../../contracts/fixtures/quote_masshealth_manual.json"),
};

export const MOCK_CARE_PATH = "shoulder_chronic_clicking_v1";

export function mockQuoteKey(req: QuoteRequest): string {
  const p = req.payment;
  return p.kind === "insurance" ? `${p.payer_id}:${p.product}` : p.kind;
}

function manualKey(req: QuoteRequest): string {
  return `${mockQuoteKey(req)}|${[...req.service_codes].sort().join(",")}`;
}

function mockLoader(req: QuoteRequest): (() => Promise<{ default: unknown }>) | undefined {
  if (req.care_path_id) return req.care_path_id === MOCK_CARE_PATH ? QUOTES[mockQuoteKey(req)] : undefined;
  return MANUAL_QUOTES[manualKey(req)];
}

export function hasMockQuote(req: QuoteRequest): boolean {
  return mockLoader(req) !== undefined;
}

const CRISIS = /\b(kill(ing)? myself|suicid\w*|end (it all|my life)|hurt(ing)? myself|self[- ]harm)\b/i;
const EMERGENCY = /\b(chest (pain|hurts|pressure)|can'?t breathe|trouble breathing|worst headache|passed out|faint(ed)?)\b/i;

const CHAT: Record<string, () => Promise<{ default: unknown }>> = {
  red_flag: () => import("../../../../contracts/fixtures/chat_red_flag.json"),
  clarify: () => import("../../../../contracts/fixtures/chat_clarify.json"),
  care_paths: () => import("../../../../contracts/fixtures/chat_care_paths.json"),
  text: () => import("../../../../contracts/fixtures/chat_text.json"),
  llm_invalid: () => import("../../../../contracts/fixtures/chat_llm_invalid.json"),
  ai_paused: () => import("../../../../contracts/fixtures/chat_ai_paused.json"),
};

async function crisisReply(): Promise<ChatResponse> {
  const base = strip<ChatResponse>(await CHAT.red_flag());
  const flags = (await import("../../../../data/redflags/redflags.json")).default as {
    dispositions: { id: string; headline: RedFlagReply["headline"]; text: RedFlagReply["text"] }[];
  };
  const d = flags.dispositions.find((x) => x.id === "crisis_988");
  if (!d) throw new NoMockData("redflags.json has no crisis_988 disposition");
  return {
    ...base,
    reply: {
      kind: "red_flag",
      disposition: "crisis_988",
      flag_ids: ["rf_suicide_self_harm"],
      escalated_by_llm: false,
      headline: d.headline,
      text: d.text,
      prices_withheld: true,
    },
  };
}

export function mockChatKind(req: ChatRequest): keyof typeof CHAT | "crisis" {
  const all = [...req.history, req.text].join(" \n ");
  if (CRISIS.test(all)) return "crisis";
  if (EMERGENCY.test(all)) return "red_flag";
  if (/#paused/.test(req.text)) return "ai_paused";
  if (/#invalid/.test(req.text)) return "llm_invalid";
  if (/#text/.test(req.text) || req.focus) return "text";
  if (req.history.length === 0 && Object.keys(req.answers).length === 0) return "clarify";
  return "care_paths";
}

export function mockApi(): CareCostApi {
  return {
    mode: "mock",
    async quote(req) {
      const load = mockLoader(req);
      if (!load)
        throw new NoMockData(
          req.care_path_id
            ? `No fixture for ${req.care_path_id} with ${mockQuoteKey(req)}. Mock fixtures cover chronic shoulder pain with BCBS MA HMO, cash and Medicare.`
            : `No fixture for ${manualKey(req)}. The only manual-pick fixture is shoulder X-ray + MRI (73030, 73221) with MassHealth.`,
        );
      return strip<QuoteResponse>(await load());
    },
    async chat(req) {
      const kind = mockChatKind(req);
      const res = kind === "crisis" ? await crisisReply() : strip<ChatResponse>(await CHAT[kind]());
      return { ...res, conversation_turn: req.history.length + 1 };
    },
    async catalog() {
      return strip<Catalog>(await import("../../../../contracts/fixtures/catalog.json"));
    },
    // same answers as the server's two picker routes, from the same catalog fixture
    async catalogPaths() {
      return (await this.catalog()).care_paths;
    },
    async pathServices(id) {
      const c = await this.catalog();
      if (!c.care_paths.some((p) => p.id === id)) throw new NoMockData(`unknown care path ${id}`);
      return c.services.filter((s) => s.care_paths.includes(id));
    },
  };
}
