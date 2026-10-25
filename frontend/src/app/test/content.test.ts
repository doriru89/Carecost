import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
// @ts-expect-error plain .mjs build script, no types
import { buildAll } from "../../../scripts/build-content.mjs";

describe("bundled content is not stale", () => {
  it("glossary / cards / questions / ZIP JSON equal a fresh build from the YAML sources", () => {
    const built = buildAll() as Record<string, unknown>;
    for (const [name, data] of Object.entries(built)) {
      const committed = readFileSync(resolve(__dirname, "../content", name), "utf8");
      expect(committed, `${name} is stale: run npm run content:build`).toBe(JSON.stringify(data, null, 1) + "\n");
    }
  });
});
