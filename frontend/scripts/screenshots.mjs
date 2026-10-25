#!/usr/bin/env node
/**
 * Playwright screenshots of the CareCost app in mock mode, at 375 px and 1280 px, into docs/frontend/,
 * plus the insurance-switch timing (plan §4.1: < 300 ms).
 *
 *   npm run dev:app            # vite on http://127.0.0.1:5180 (mock data by default)
 *   npm run screenshots        # BASE_URL=http://127.0.0.1:5180 by default
 *
 * Writes docs/frontend/<screen>-<width>.png and docs/frontend/switch-timing.json.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../../docs/frontend");
const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5180";
mkdirSync(out, { recursive: true });

const WIDTHS = [375, 1280];
const shot = async (page, name, width, opts = {}) => {
  const path = resolve(out, `${name}-${width}.png`);
  await page.screenshot({ path, fullPage: opts.fullPage ?? true });
  console.log("wrote", path);
};

async function startChat(page, text, { payment = "BCBS_MA:HMO" } = {}) {
  await page.goto(`${BASE}/start`);
  await page.getByTestId("payment-select").selectOption(payment);
  await page.getByTestId("email").fill("test@example.com");
  await page.getByTestId("start-chat").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

async function toPrices(page, width) {
  if (width < 768) await page.getByRole("tab", { name: "Prices" }).click();
}

async function openReceipt(page, width) {
  await startChat(page, "My shoulder has hurt for a few months and it clicks when I lift my arm.");
  await page.getByTestId("chip").filter({ hasText: "No, it came on gradually" }).click();
  await page.getByText("Because you said").waitFor();
  await toPrices(page, width);
  await page.getByTestId("receipt").waitFor();
}

const browser = await chromium.launch();
const timing = [];
try {
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: width < 768 ? 812 : 900 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror", e.message));

    await page.goto(`${BASE}/start`);
    await page.getByTestId("start-page").waitFor();
    await shot(page, "start", width);

    await openReceipt(page, width);
    await shot(page, "receipt-bcbs", width);

    // insurance switch: BCBS -> cash -> Medicare -> BCBS (cached) -> cash (cached)
    const seq = ["cash", "medicare", "BCBS_MA:HMO", "cash"];
    for (const [i, p] of seq.entries()) {
      await page.locator("#payment-switch").selectOption(p);
      await page.waitForFunction((n) => (window.__carecostSwitch ?? []).length >= n, i + 1);
    }
    timing.push({ width, switches: await page.evaluate(() => window.__carecostSwitch ?? []) });
    await page.getByTestId("receipt").waitFor();
    await shot(page, "receipt-cash", width);

    await page.locator("#payment-switch").selectOption("BCBS_MA:HMO");
    await page.getByTestId("zip-input").fill("02135");
    await page.getByRole("tab", { name: "List" }).click();
    await page.getByTestId("site-list").waitFor();
    await page.getByRole("radio", { name: "Nearest" }).click();
    await shot(page, "list", width);

    await page.getByRole("tab", { name: "Map" }).click();
    await page.getByTestId("map-pin").first().waitFor();
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2500);
    await shot(page, "map", width, { fullPage: false });

    if (width >= 768) {
      await page.getByRole("tab", { name: "Receipt" }).click();
      await page.getByRole("button", { name: /Stacked/ }).click();
      await page.getByRole("button", { name: /Flip/ }).click();
      await shot(page, "split-stacked-flipped", width, { fullPage: false });
    }

    await startChat(page, "My chest hurts and my left arm feels numb");
    await page.getByTestId("red-flag-page").waitFor();
    await shot(page, "red-flag", width);

    await startChat(page, "I want to kill myself");
    await page.getByTestId("crisis-page").waitFor();
    await shot(page, "crisis-988", width);

    await ctx.close();
  }
} finally {
  await browser.close();
}
writeFileSync(resolve(out, "switch-timing.json"), JSON.stringify(timing, null, 1) + "\n");
console.log(JSON.stringify(timing));
