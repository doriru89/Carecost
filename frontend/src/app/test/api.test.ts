import { describe, expect, it, vi } from "vitest";
import type { ChatRequest } from "@/generated/contracts/chat_api";
import type { QuoteRequest } from "@/generated/contracts/quote_api";
import { NoMockData, dataMode, httpApi } from "../api/client";
import { mockApi, mockChatKind } from "../api/mock";

const quoteReq = (payment: QuoteRequest["payment"], care_path_id: string | null = "shoulder_chronic_clicking_v1"): QuoteRequest =>
  ({ payment, care_path_id, answers: {}, service_codes: [], picked_by: "person", site_ids: null }) as QuoteRequest;

const chatReq = (text: string, extra: Partial<ChatRequest> = {}): ChatRequest => ({
  conversation_id: null,
  text,
  payment: { kind: "cash" },
  email: "a@b.co",
  answers: {},
  history: [],
  focus: null,
  locale: "en",
  ...extra,
});

describe("mock mode (default until integration)", () => {
  it("is the default and can be switched by URL", () => {
    expect(dataMode("")).toBe("mock");
    expect(dataMode("?data=api")).toBe("api");
  });

  it("serves the BCBS / cash / Medicare fixtures without the fixture markers", async () => {
    const api = mockApi();
    const q = await api.quote(quoteReq({ kind: "insurance", payer_id: "BCBS_MA", product: "HMO", network: null }));
    expect(q.payment).toMatchObject({ payer_id: "BCBS_MA" });
    expect("_fixture" in q).toBe(false);
    expect((await api.quote(quoteReq({ kind: "cash" }))).payment.kind).toBe("cash");
    expect((await api.quote(quoteReq({ kind: "medicare" }))).payment.kind).toBe("medicare");
  });

  it("refuses to invent a quote it has no fixture for", async () => {
    const api = mockApi();
    await expect(api.quote(quoteReq({ kind: "insurance", payer_id: "AETNA", product: "PPO", network: null }))).rejects.toBeInstanceOf(NoMockData);
    await expect(api.quote(quoteReq({ kind: "cash" }, "knee_chronic_v1"))).rejects.toBeInstanceOf(NoMockData);
    await expect(api.quote(quoteReq({ kind: "masshealth" }))).rejects.toBeInstanceOf(NoMockData);
    await expect(api.quote({ ...quoteReq({ kind: "cash" }, null), service_codes: ["73030", "73221"] })).rejects.toBeInstanceOf(NoMockData);
  });

  it("serves the MassHealth manual pick (73030 + 73221) with no D33 lines", async () => {
    const api = mockApi();
    const q = await api.quote({ ...quoteReq({ kind: "masshealth" }, null), service_codes: ["73221", "73030"] });
    expect(q.payment.kind).toBe("masshealth");
    expect(q.care_path).toBeNull();
    expect(q.copy_keys).toEqual([]);
  });

  it("answers the two picker steps from the catalog fixture", async () => {
    const api = mockApi();
    const paths = await api.catalogPaths();
    expect(paths.length).toBeGreaterThan(0);
    const svcs = await api.pathServices(paths[0].id);
    expect(svcs.length).toBeGreaterThan(0);
    expect(svcs.every((s) => s.care_paths.includes(paths[0].id))).toBe(true);
    await expect(api.pathServices("no_such_path_v1")).rejects.toBeInstanceOf(NoMockData);
  });

  it("chat script: crisis words -> crisis_988 with redflags.json copy; emergency -> call_911", async () => {
    const api = mockApi();
    const crisis = await api.chat(chatReq("I want to kill myself"));
    expect(crisis.reply).toMatchObject({ kind: "red_flag", disposition: "crisis_988", prices_withheld: true });
    if (crisis.reply.kind === "red_flag") expect(crisis.reply.headline.en).toBe("Call or text 988 now");
    expect(crisis.llm_called).toBe(false);
    expect((await api.chat(chatReq("my chest hurts"))).reply).toMatchObject({ kind: "red_flag", disposition: "call_911" });
    expect(mockChatKind(chatReq("shoulder clicks"))).toBe("clarify");
    expect(mockChatKind(chatReq("No, it came on gradually", { history: ["shoulder"], answers: { Q2: ["no_injury"] } }))).toBe("care_paths");
    // a crisis phrase in an earlier turn still stops the conversation
    expect(mockChatKind(chatReq("ok", { history: ["I want to end my life"] }))).toBe("crisis");
  });
});

describe("http client", () => {
  it("POSTs the request body as JSON to /api/quote and /api/chat, GETs the catalog", async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const fake = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push([String(url), init]);
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;
    const api = httpApi("http://x/", fake);
    await api.quote(quoteReq({ kind: "cash" }));
    await api.chat(chatReq("hi"));
    await api.catalog();
    await api.catalogPaths();
    await api.pathServices("shoulder_chronic_clicking_v1");
    expect(calls.map((c) => [c[0], c[1]?.method ?? "GET"])).toEqual([
      ["http://x/api/quote", "POST"],
      ["http://x/api/chat", "POST"],
      ["http://x/api/catalog", "GET"],
      ["http://x/api/catalog/paths", "GET"],
      ["http://x/api/catalog/paths/shoulder_chronic_clicking_v1/services", "GET"],
    ]);
    const body = JSON.parse(String(calls[0][1]?.body));
    expect(body.payment).toEqual({ kind: "cash" });
    // near / max_sites are not sent until the contract has them (C2)
    expect(Object.keys(body).sort()).toEqual(["answers", "care_path_id", "payment", "picked_by", "service_codes", "site_ids"]);
  });

  it("turns a non-2xx into an error", async () => {
    const api = httpApi("", (async () => new Response("no", { status: 503, statusText: "Unavailable" })) as typeof fetch);
    await expect(api.catalog()).rejects.toThrow(/503/);
  });
});
