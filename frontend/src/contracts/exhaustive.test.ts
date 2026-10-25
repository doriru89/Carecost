/**
 * Runs in CI (vitest) and imports the locks, so exhaustive.ts is part of the tested build, not a
 * file nothing loads. The type-level gate is `npm run typecheck:contracts` (also in CI); this test
 * adds a runtime check against the committed JSON Schemas.
 */
import { describe, expect, it } from "vitest";

import chatSchema from "../../../contracts/chat_api.schema.json";
import quoteSchema from "../../../contracts/quote_api.schema.json";
import {
  CHAT_REPLY_FULL_PAGE,
  DISPOSITION_RANK,
  GAP_COPY_KEY,
  LIKELIHOOD_TO_TIER,
  TIER_BASIS_KEY,
  TIER_ORDER,
  cellSummary,
} from "./exhaustive";

type Defs = Record<string, { enum?: string[]; oneOf?: { $ref: string }[]; properties?: Record<string, { const?: string }> }>;

function unionKinds(defs: Defs, name: string): string[] {
  return (defs[name].oneOf ?? []).map((r) => {
    const def = defs[r.$ref.split("/").pop() as string];
    return def.properties?.kind?.const as string;
  });
}

const qd = (quoteSchema as unknown as { $defs: Defs }).$defs;
const cd = (chatSchema as unknown as { $defs: Defs }).$defs;

describe("contract exhaustiveness locks", () => {
  it("cover every Gap kind, tier and tier basis", () => {
    expect(Object.keys(GAP_COPY_KEY).sort()).toEqual(unionKinds(qd, "Gap").sort());
    expect(Object.keys(TIER_ORDER).sort()).toEqual([...(qd.CertaintyTier.enum ?? [])].sort());
    expect(Object.keys(LIKELIHOOD_TO_TIER).sort()).toEqual([...(qd.Likelihood.enum ?? [])].sort());
    expect(Object.keys(TIER_BASIS_KEY).sort()).toEqual([...(qd.TierBasis.enum ?? [])].sort());
  });

  it("cover every chat reply kind and disposition", () => {
    expect(Object.keys(CHAT_REPLY_FULL_PAGE).sort()).toEqual(unionKinds(cd, "ChatReply").sort());
    expect(Object.keys(DISPOSITION_RANK).sort()).toEqual([...(cd.Disposition.enum ?? [])].sort());
  });

  it("summarises a cell without inventing a number", () => {
    expect(cellSummary({ kind: "no_source", what: "x", ask: "y" })).toBe("gap.no_source");
  });
});
