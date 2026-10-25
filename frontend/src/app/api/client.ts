/**
 * The app's only data access: POST /api/quote, POST /api/chat, GET /api/catalog,
 * GET /api/catalog/paths and GET /api/catalog/paths/{id}/services (backend app/quote/api.py).
 *
 * Mode: `mock` (default until integration) answers from contracts/fixtures/*.json; `api` calls the
 * FastAPI server. Pick with VITE_DATA_SOURCE=api|mock at build time or `?data=api` in the URL.
 * Base URL: VITE_API_BASE_URL (default same origin; the vite dev server proxies /api).
 */
import type { Catalog, CatalogPath, CatalogService } from "@/generated/contracts/catalog";
import type { ChatRequest, ChatResponse } from "@/generated/contracts/chat_api";
import type { QuoteRequest, QuoteResponse } from "@/generated/contracts/quote_api";
import { ApiError } from "./errors";
import { mockApi } from "./mock";

export { ApiError, NoMockData } from "./errors";

export interface CareCostApi {
  mode: "mock" | "api";
  quote(req: QuoteRequest): Promise<QuoteResponse>;
  chat(req: ChatRequest): Promise<ChatResponse>;
  /** D3 skip-AI browse: every care path and service */
  catalog(): Promise<Catalog>;
  /** Picker step 1: the care paths */
  catalogPaths(): Promise<CatalogPath[]>;
  /** Picker step 2: the services in one care path (quote the chosen one with service_codes) */
  pathServices(pathId: string): Promise<CatalogService[]>;
}

export const CATALOG_PATH = "/api/catalog";

/**
 * The request body for POST /api/quote. The one place request fields are added.
 *
 * NEXT (stream C2, in parallel): `near` (the person's location for a site filter) and `max_sites`
 * go HERE once the merged contract has them. Do not send them before then: QuoteRequest forbids
 * unknown fields, so the server would answer 422.
 */
export function quoteBody(req: QuoteRequest): string {
  return JSON.stringify(req);
}

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
    quote: (req) => call<QuoteResponse>("/api/quote", { method: "POST", body: quoteBody(req) }),
    chat: (req) => call<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify(req) }),
    catalog: () => call<Catalog>(CATALOG_PATH),
    catalogPaths: () => call<CatalogPath[]>(`${CATALOG_PATH}/paths`),
    pathServices: (id) => call<CatalogService[]>(`${CATALOG_PATH}/paths/${encodeURIComponent(id)}/services`),
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
