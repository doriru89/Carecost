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
import type { Near, QuoteRequest, QuoteResponse } from "@/generated/contracts/quote_api";
import type { LatLon } from "../lib/geo";
import { ApiError } from "./errors";
import { mockApi } from "./mock";

export { ApiError, NoMockData } from "./errors";

/** How the request picks its sites (C2): from a point the person gave us, or the best value overall. */
export interface QuoteOptions {
  /** The person's ZIP centroid or device location; null = no location given */
  location?: LatLon | null;
  /** R15: CareApp aborts a request it no longer wants (the person changed the choice) or that took too long */
  signal?: AbortSignal;
}

export interface CareCostApi {
  mode: "mock" | "api";
  quote(req: QuoteRequest, opts?: QuoteOptions): Promise<QuoteResponse>;
  chat(req: ChatRequest): Promise<ChatResponse>;
  /** D3 skip-AI browse: every care path and service */
  catalog(): Promise<Catalog>;
  /** Picker step 1: the care paths */
  catalogPaths(): Promise<CatalogPath[]>;
  /** Picker step 2: the services in one care path (quote the chosen one with service_codes) */
  pathServices(pathId: string): Promise<CatalogService[]>;
}

export const CATALOG_PATH = "/api/catalog";

/** Sites per response (C2: default 12, max 50). The list and the map show all of them. */
export const MAX_SITES = 12;

/** The server's scope guard on `near` (backend app/quote/contracts.py `Near`: lat 41.0-43.5, lon -72.5 to -69.5). */
const NEAR_BOUNDS = { latMin: 41.0, latMax: 43.5, lonMin: -72.5, lonMax: -69.5 };

/** A device fix is rounded to 2 decimals (about 0.7 mi) before it is sent; a ZIP centroid is already coarse. */
const round2 = (x: number) => Math.round(x * 100) / 100;

/**
 * The `near` point a request will carry, or null. Null when there is no location, or when the point is
 * outside the server's scope guard (a western-MA ZIP): the request then asks for the best value overall
 * instead of failing with 422.
 */
export function nearFor(location: (LatLon & { kind?: "zip" | "device" }) | null | undefined): Near | null {
  if (!location) return null;
  const { lat, lon } = location.kind === "device" ? { lat: round2(location.lat), lon: round2(location.lon) } : location;
  const b = NEAR_BOUNDS;
  if (!(lat >= b.latMin && lat <= b.latMax && lon >= b.lonMin && lon <= b.lonMax)) return null;
  return { lat, lon };
}

/**
 * The request body for POST /api/quote. The one place request fields are added.
 *
 * C2: `max_sites` is always sent; `near` only when the person gave a location (typed ZIP or device).
 * Without `near` the server returns the max_sites best-ranked sites of the whole registry (I7), so the
 * list says "best value overall", never "nearest". The point is used only to choose sites; the server
 * does not store or log it (QuoteRequest.near).
 */
export function quoteBody(req: QuoteRequest, opts: QuoteOptions = {}): string {
  const { near: _n, max_sites: _m, ...rest } = req;
  void _n;
  void _m;
  const near = nearFor(opts.location);
  const body: QuoteRequest = { ...rest, max_sites: MAX_SITES, ...(near ? { near } : {}) };
  return JSON.stringify(body);
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
    quote: (req, opts) => call<QuoteResponse>("/api/quote", { method: "POST", body: quoteBody(req, opts), signal: opts?.signal }),
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
