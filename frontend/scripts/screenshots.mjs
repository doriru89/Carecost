#!/usr/bin/env node
/**
 * Playwright screenshots of the CareCost app at 375 px and 1280 px, into docs/frontend/, plus the
 * insurance-switch timing (plan §4.1: < 300 ms), in mock mode, api mode, or both.
 *
 *   npm run build && npx vite preview --host 127.0.0.1 --port 5180 --strictPort
 *   (api mode also needs the backend: cd backend && uv run --frozen uvicorn app.server:app --port 8100)
 *   MODE=both npm run screenshots          # MODE=mock | api | both (default both); BASE_URL=http://127.0.0.1:5180
 *
 * Mock mode writes docs/frontend/<screen>-<width>.png and switch-timing.json; api mode writes
 * <screen>-api-<width>.png and switch-timing-api.json.
 *
 * D6: a care-path quote opens on the first screen ("Where to go": options, cheapest, alternates), shot as
 * first-screen-bcbs; the breakdown of one place is the "Breakdown" tab (was "Receipt").
 *
 * Api mode (D3, wave2/base 9c54616: C2's contract, Chat merged): the shoulder path with BCBS HMO and no
 * location ("best value overall"), then ZIP 02138 ("nearest"), Medicare near ZIP 02115 at Brigham
 * (price_notes on the OPPS facility lines, G0463; unknown availability) and BIDMC (a data notice),
 * and chat without a provider key (the real server's ai_paused reply).
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../../docs/frontend");
const BASE = process.env.BASE_URL ?? "http://127.0.0.1:5180";
const MODES = (process.env.MODE ?? "both") === "both" ? ["mock", "api"] : [process.env.MODE];
mkdirSync(out, { recursive: true });

const WIDTHS = [375, 1280];

async function startChat(page, mode, text, { payment = "BCBS_MA:HMO" } = {}) {
  await page.goto(`${BASE}/start?data=${mode}`);
  await page.getByTestId("payment-select").selectOption(payment);
  await page.getByTestId("email").fill("test@example.com");
  await page.getByTestId("start-chat").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

async function toPrices(page, width) {
  if (width < 768) await page.getByRole("tab", { name: "Prices" }).click();
}

async function waitQuote(page) {
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="results-pane"]');
    return (
      el &&
      !el.textContent.includes("Pricing…") &&
      (el.querySelector('[data-testid="overview"]') || el.querySelector('[data-testid="receipt"]') || el.querySelector('[data-testid="quote-unavailable"]'))
    );
  });
}

/** Mock: through the scripted chat (clarify -> care path). */
async function openReceiptByChat(page, mode, width) {
  await startChat(page, mode, "My shoulder has hurt for a few months and it clicks when I lift my arm.");
  await page.getByTestId("chip").filter({ hasText: "No, it came on gradually" }).click();
  await page.getByText("Because you said").waitFor();
  await toPrices(page, width);
  // D6: a care path opens on the first screen ("Where to go"); the breakdown is one tab away
  await page.getByTestId("overview").waitFor();
}

/** D6: from the first screen to the breakdown tab (one site's receipt). */
async function toBreakdown(page) {
  await page.getByRole("tab", { name: "Breakdown" }).click();
  await page.getByTestId("receipt").waitFor();
}

/** Api: Skip AI -> Browse -> a care path -> "Price every step" (the two picker routes, then POST /api/quote). */
async function openReceiptByBrowse(page, mode, width, pathTitle, payment = "BCBS_MA:HMO") {
  await page.goto(`${BASE}/start?data=${mode}`);
  await page.getByTestId("payment-select").selectOption(payment);
  await page.getByTestId("skip-ai").click();
  await page.getByTestId("browse-picker").waitFor();
  await page.getByTestId("browse-path").filter({ hasText: pathTitle }).locator("button").first().click();
  await page.getByTestId("path-services").getByText("Only:").first().waitFor();
  await page.getByRole("button", { name: "Price every step" }).click();
  await waitQuote(page);
  void width;
}

async function pickSite(page, name) {
  await page.getByLabel("Pick a place").getByRole("button", { name, exact: true }).first().click();
  await page.getByTestId("receipt").getByRole("heading", { name, exact: true }).waitFor();
}

const ZIPS = JSON.parse(readFileSync(resolve(here, "../src/app/content/ma_zips.json"), "utf8")).zips;

/** Api mode: type a ZIP and wait for the quote whose request key carries that ZIP's `near` point. */
async function setZip(page, zip) {
  const [lat, lon] = ZIPS[zip];
  await page.getByTestId("zip-input").fill(zip);
  // the request key is payment|query|picked_by|<near>|<order_by> (D6 added order_by)
  await page.locator(`[data-testid="results-pane"][data-quote-key*="|${lat},${lon}|"]`).waitFor();
}

const browser = await chromium.launch();
const results = {};
try {
  for (const mode of MODES) {
    const sfx = mode === "api" ? "-api" : "";
    const timing = [];
    const errors = [];
    for (const width of WIDTHS) {
      const ctx = await browser.newContext({ viewport: { width, height: width < 768 ? 812 : 900 }, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      page.on("pageerror", (e) => errors.push(`${width} pageerror ${e.message}`));
      page.on("console", (m) => m.type() === "error" && !/404/.test(m.text()) && errors.push(`${width} console ${m.text()}`));
      const shot = async (name, opts = {}) => {
        const path = resolve(out, `${name}${sfx}-${width}.png`);
        const before = await page.locator('[data-testid="receipt"] h2').first().textContent({ timeout: 200 }).catch(() => null);
        await page.screenshot({ path, fullPage: opts.fullPage ?? true });
        const after = await page.locator('[data-testid="receipt"] h2').first().textContent({ timeout: 200 }).catch(() => null);
        console.log("wrote", path, before ? `(receipt: ${before}${after !== before ? ` -> ${after}` : ""})` : "");
      };

      await page.goto(`${BASE}/start?data=${mode}`);
      await page.getByTestId("start-page").waitFor();
      await shot("start");

      if (mode === "mock") await openReceiptByChat(page, mode, width);
      else await openReceiptByBrowse(page, mode, width, "Shoulder pain that came on gradually");
      await page.getByTestId("overview").waitFor();
      await shot("first-screen-bcbs");
      await toBreakdown(page);
      await shot("receipt-bcbs");

      if (mode === "api") {
        // no location: the server's 12 best-ranked sites, labelled "best value overall"
        await page.getByRole("tab", { name: "List" }).click();
        await page.getByTestId("site-list").waitFor();
        await shot("list-overall");
        await page.getByRole("tab", { name: "Breakdown" }).click();
        await setZip(page, "02138");
      }

      // a hospital receipt with ranges: both ends cited (prov / prov_high)
      await pickSite(page, "Mount Auburn Hospital");
      await shot("receipt-bcbs-mta");

      // insurance switch. Mock: the three fixtures, then two cached. Api: five payments the server
      // has not been asked yet (near 02138), then two cached.
      const seq =
        mode === "mock"
          ? ["cash", "medicare", "BCBS_MA:HMO", "cash"]
          : ["cash", "medicare", "masshealth", "BCBS_MA:PPO", "AETNA:PPO", "BCBS_MA:HMO", "cash"];
      await page.evaluate(() => (window.__carecostSwitch = []));
      for (const [i, p] of seq.entries()) {
        await page.locator("#payment-switch").selectOption(p);
        await page.waitForFunction((n) => (window.__carecostSwitch ?? []).length >= n, i + 1);
      }
      timing.push({ width, switches: await page.evaluate(() => window.__carecostSwitch ?? []) });
      await page.getByTestId("receipt").waitFor();
      await shot("receipt-cash");

      await page.locator("#payment-switch").selectOption("BCBS_MA:HMO");
      await waitQuote(page);
      if (mode === "mock") await page.getByTestId("zip-input").fill("02138");
      await page.getByRole("tab", { name: "List" }).click();
      await page.getByTestId("site-list").waitFor();
      await page.getByRole("radio", { name: "Nearest" }).click();
      await shot("list");

      if (mode === "api") {
        // Medicare near Longwood: Brigham's facility lines are OPPS national rates (price_notes), its
        // visit looks up G0463, and several lines have no evidence either way (availability unknown)
        await page.getByRole("tab", { name: "Breakdown" }).click();
        await page.locator("#payment-switch").selectOption("medicare");
        await waitQuote(page);
        await setZip(page, "02115");
        await pickSite(page, "Brigham and Women's Hospital");
        // data-dependent probes (C4c changed Brigham's lines): wait briefly, never fail the run on them
        await page.getByTestId("price-note").first().waitFor({ timeout: 5000 }).catch(() => console.log("note: no price_notes line at Brigham"));
        await page.getByTestId("availability-unknown").first().waitFor({ timeout: 5000 }).catch(() => console.log("note: no availability-unknown line at Brigham"));
        await shot("receipt-medicare-brigham");
        await page.getByRole("tab", { name: "List" }).click();
        await page.getByTestId("site-list").waitFor();
        await shot("list-medicare-02115");
        await page.getByRole("tab", { name: "Breakdown" }).click();
        await pickSite(page, "Beth Israel Deaconess Medical Center");
        await shot("receipt-medicare-bidmc");

        // chat without a provider key: the merged Chat service answers ai_paused(provider_unavailable)
        await startChat(page, mode, "My shoulder clicks when I lift my arm");
        // Chat2 (R18): without a key the server answers with the chips copy (ai.paused_provider_chips) or ai.paused_provider
        await page.getByText(/isn't available right now|can't read typed messages/).first().waitFor();
        await shot("chat-paused", { fullPage: false });
      } else {
        await page.getByRole("tab", { name: "Map" }).click();
        await page.getByTestId("map-pin").first().waitFor();
        await page.waitForLoadState("networkidle").catch(() => {});
        await page.waitForTimeout(2500);
        await shot("map", { fullPage: false });

        if (width >= 768) {
          await page.getByRole("tab", { name: "Breakdown" }).click();
          await page.getByRole("button", { name: /Stacked/ }).click();
          await page.getByRole("button", { name: /Flip/ }).click();
          await shot("split-stacked-flipped", { fullPage: false });
        }

        await startChat(page, mode, "My chest hurts and my left arm feels numb");
        await page.getByTestId("red-flag-page").waitFor();
        await shot("red-flag");

        await startChat(page, mode, "I want to kill myself");
        await page.getByTestId("crisis-page").waitFor();
        await shot("crisis-988");
      }
      await ctx.close();
    }
    writeFileSync(resolve(out, `switch-timing${sfx}.json`), JSON.stringify(timing, null, 1) + "\n");
    results[mode] = { timing, errors };
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify(results));
