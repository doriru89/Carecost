import { describe, expect, it } from "vitest";
import chatSchema from "../../../../contracts/chat_api.schema.json";
import { CONTRACT_COPY, hasCopy, reviewKeys, t } from "@/contracts/copy";
import { SOURCE_CHIP_KEY, YOU_PAY_KEY } from "@/contracts/exhaustive";
import glossary from "../content/glossary.json";
import { ALL_QUOTES } from "./fixtures";

const terms = (glossary as { terms: Record<string, unknown> }).terms;

describe("copy file (P1 problem 13, D33)", () => {
  it("has English text for every copy key the fixtures send", () => {
    const keys = new Set<string>();
    for (const q of ALL_QUOTES) {
      q.notices.forEach((n) => keys.add(`notice.${n}`));
      for (const s of q.sites) {
        keys.add(s.receipt.totals.you_pay.note_key);
        for (const l of s.receipt.lines) if (l.doctor_fee) keys.add(l.doctor_fee.explanation_key);
      }
    }
    const missing = [...keys].filter((k) => !hasCopy(k));
    expect(missing).toEqual([]);
  });

  it("has the D33 lines, every source hover and every you-pay rule", () => {
    expect(t("copy.not_a_diagnosis")).toMatch(/not a diagnosis/);
    expect(t("copy.when_to_see_a_doctor").length).toBeGreaterThan(40);
    for (const kind of Object.keys(SOURCE_CHIP_KEY)) expect(hasCopy(`source_hover.${kind}`)).toBe(true);
    for (const key of Object.values(YOU_PAY_KEY)) expect(hasCopy(key)).toBe(true);
  });

  it("covers every chat message_key and copy_key enum in the committed schema", () => {
    const text = JSON.stringify(chatSchema);
    const keys = [...text.matchAll(/"((?:ai|copy)\.[a-z_]+)"/g)].map((m) => m[1]);
    expect(keys.length).toBeGreaterThan(4);
    expect(keys.filter((k) => !hasCopy(k))).toEqual([]);
  });

  it("every glossary key a fixture line uses has hover text", () => {
    const used = new Set(ALL_QUOTES.flatMap((q) => q.sites.flatMap((s) => s.receipt.lines.flatMap((l) => l.glossary_keys))));
    expect([...used].filter((k) => !(k in terms))).toEqual([]);
  });

  it("fills placeholders and never returns blank for an unknown key", () => {
    expect(t("source_hover.clinic_posted", { publisher: "AFC", date: "Oct 24, 2026" })).toContain("Posted by AFC");
    expect(t("no.such.key")).toBe("no.such.key");
  });

  it("marks the safety and money wording for Austin's review", () => {
    const r = reviewKeys();
    for (const k of ["copy.not_a_diagnosis", "copy.when_to_see_a_doctor", "crisis.call_988", "fee.rung_6_estimate"]) expect(r).toContain(k);
    expect(Object.keys(CONTRACT_COPY).length).toBeGreaterThan(60);
  });
});
