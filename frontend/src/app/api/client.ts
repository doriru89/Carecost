/**
 * The app's only data access: POST /api/quote, POST /api/chat, GET /api/catalog.
 *
 * Mode: `mock` (default until integration) answers from contracts/fixtures/*.json; `api` calls the
 * FastAPI server. Pick with VITE_DATA_SOURCE=api|mock at build time or `?data=api` in the URL.
 * Base URL: VITE_API_BASE_URL (default same origin; the vite dev server proxies /api).
 */
import type { Catalog } from "@/generated/contracts/catalog";
import type { ChatRequest, ChatResponse } from "@/generated/contracts/chat_api";
import type { QuoteRequest, QuoteResponse } from "@/generated/contracts/quote_api";
import { ApiError } from "./errors";
import { mockApi } from "./mock";

export { ApiError, NoMockData } from "./errors";

export interface CareCostApi {
  mode: "mock" | "api";
  quote(req: QuoteRequest): Promise<QuoteResponse>;
  chat(req: ChatRequest): Promise<ChatResponse>;
  catalog(): Promise<Catalog>;
}

export const CATALOG_PATH = "/api/catalog";

export function httpApi(base = "", fetchImpl: typeof fetch = (...a) => fetch(...a)): CareCostApi {
  const root = base.replace(/\/$/, "");
  async function call<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await fetchImpl(`${root}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!r.ok) throw new ApiError(r.status, `${r.status} ${r.statusText}`);
    return (await r.json()) as T;
  }
  return {
    mode: "api",
    quote: (req) => call<QuoteResponse>("/api/quote", { method: "POST", body: JSON.stringify(req) }),
    chat: (req) => call<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify(req) }),
    catalog: () => call<Catalog>(CATALOG_PATH),
  };
}

export function dataMode(search: string = typeof location !== "undefined" ? location.search : ""): "mock" | "api" {
  const fromUrl = new URLSearchParams(search).get("data");
  if (fromUrl === "api" || fromUrl === "mock") return fromUrl;
  return import.meta.env.VITE_DATA_SOURCE === "api" ? "api" : "mock";
}

let singleton: CareCostApi | null = null;

export function getApi(): CareCostApi {
  if (!singleton) singleton = dataMode() === "api" ? httpApi(import.meta.env.VITE_API_BASE_URL ?? "") : mockApi();
  return singleton;
}
