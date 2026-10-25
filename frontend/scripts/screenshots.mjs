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
 * Api mode, chat: the merged backend has no POST /api/chat yet (the Chat branch is not merged), so
 * "chat-404-api" is the real 404 state. "chat-paused-api" answers /api/chat in the browser with the
 * reply the Chat service builds without a provider key (_paused("provider_unavailable", None)); the
 * quote and catalog calls still go to the real server. It is a stand-in until Chat merges.
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
    return el && !el.textContent.includes("Pricing…") && (el.querySelector('[data-testid="receipt"]') || el.querySelector('[data-testid="quote-unavailable"]'));
  });
}

/** Mock: through the scripted chat (clarify -> care path). */
async function openReceiptByChat(page, mode, width) {
  await startChat(page, mode, "My shoulder has hurt for a few months and it clicks when I lift my arm.");
  await page.getByTestId("chip").filter({ hasText: "No, it came on gradually" }).click();
  await page.getByText("Because you said").waitFor();
  await toPrices(page, width);
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
  await page.getByLabel("Pick a place").getByRole("button", { name }).click();
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
        await page.screenshot({ path, fullPage: opts.fullPage ?? true });
        console.log("wrote", path);
      };

      await page.goto(`${BASE}/start?data=${mode}`);
      await page.getByTestId("start-page").waitFor();
      await shot("start");

      if (mode === "mock") await openReceiptByChat(page, mode, width);
      else await openReceiptByBrowse(page, mode, width, "Shoulder pain that came on gradually");
      await shot("receipt-bcbs");

      // a hospital receipt with ranges: both ends cited (prov / prov_high)
      await pickSite(page, "Tufts Medical Center");
      await page.getByTestId("receipt").getByText("Tufts Medical Center").first().waitFor();
      await shot("receipt-bcbs-tufts");
      await pickSite(page, "AFC Urgent Care Watertown");

      // insurance switch. Mock: the three fixtures, then two cached. Api: five payments the server
      // has not been asked yet, then two cached.
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
      await page.getByTestId("zip-input").fill("02135");
      await page.getByRole("tab", { name: "List" }).click();
      await page.getByTestId("site-list").waitFor();
      await page.getByRole("radio", { name: "Nearest" }).click();
      await shot("list");

      if (mode === "api") {
        // a manual pick with MassHealth: the doctor's reading is rung 7 (Medicare as a reference, not summed),
        // and a manual pick carries no D33 lines
        await page.getByRole("tab", { name: "Browse" }).click();
        await page.getByLabel("Search services").fill("73221");
        await page.getByTestId("browse-picker").getByRole("button", { name: /Shoulder MRI/ }).last().click();
        await page.locator("#payment-switch").selectOption("masshealth");
        await waitQuote(page);
        await pickSite(page, "Tufts Medical Center");
        await page.getByTestId("receipt").getByText("Tufts Medical Center").first().waitFor();
        await shot("receipt-masshealth-mri");

        // chat on the merged base: no /api/chat route yet -> 404 -> a plain error, browse stays open
        await startChat(page, mode, "My shoulder clicks when I lift my arm");
        await page.getByTestId("chat-error").waitFor();
        await shot("chat-404", { fullPage: false });

        // chat without a provider key (stand-in for the Chat service, see the header)
        const paused = JSON.parse(readFileSync(resolve(here, "../../contracts/fixtures/chat_ai_paused.json"), "utf8"));
        delete paused._fixture;
        delete paused._schema;
        paused.llm_called = false;
        paused.reply = { kind: "ai_paused", reason: "provider_unavailable", message_key: "ai.paused_provider", resumes_at: null, browse_prices_available: true };
        await page.route("**/api/chat", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...paused, conversation_turn: 1 }) }));
        await startChat(page, mode, "My shoulder clicks when I lift my arm");
        await page.getByText("isn't available right now").waitFor();
        await shot("chat-paused", { fullPage: false });
        await page.unroute("**/api/chat");
      } else {
        await page.getByRole("tab", { name: "Map" }).click();
        await page.getByTestId("map-pin").first().waitFor();
        await page.waitForLoadState("networkidle").catch(() => {});
        await page.waitForTimeout(2500);
        await shot("map", { fullPage: false });

        if (width >= 768) {
          await page.getByRole("tab", { name: "Receipt" }).click();
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
