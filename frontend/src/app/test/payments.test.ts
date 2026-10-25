import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { INSURERS, PAYMENT_CHOICES, paymentId } from "../lib/payments";

const repo = resolve(__dirname, "../../../..");

describe("payment choices (D4)", () => {
  it("match the TiC networks registry: same payers, same products (INDEMNITY / unnamed excluded)", () => {
    const tic = parse(readFileSync(resolve(repo, "data/etl/sources.d/tic.yaml"), "utf8"));
    const payerOf: Record<string, string> = Object.fromEntries(tic.sources.map((s: { source_id: string; payer_id: string }) => [s.source_id, s.payer_id]));
    const nets = parse(readFileSync(resolve(repo, "data/etl/tic_networks.yaml"), "utf8")).networks as { source_id: string; payer_id?: string; product: string }[];
    const want: Record<string, Set<string>> = {};
    for (const n of nets) {
      const p = n.payer_id ?? payerOf[n.source_id];
      if (!n.product || n.product === "INDEMNITY") continue;
      (want[p] ??= new Set()).add(n.product);
    }
    const have = Object.fromEntries(INSURERS.map((i) => [i.payer_id, new Set(i.products)]));
    expect(Object.keys(have).sort()).toEqual(Object.keys(want).sort());
    for (const p of Object.keys(want)) expect([...have[p]].sort()).toEqual([...want[p]].sort());
  });

  it("offers Cash, Medicare and MassHealth, with unique ids", () => {
    const ids = PAYMENT_CHOICES.map((c) => c.id);
    expect(ids).toEqual(expect.arrayContaining(["cash", "medicare", "masshealth", "BCBS_MA:HMO"]));
    expect(new Set(ids).size).toBe(ids.length);
    for (const c of PAYMENT_CHOICES) expect(paymentId(c.payment)).toBe(c.id);
  });
});
