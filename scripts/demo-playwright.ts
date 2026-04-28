/**
 * YHack Demo — Playwright automation for screen recording.
 *
 * Run with: npx playwright test scripts/demo-playwright.ts --headed --timeout=120000
 *
 * Best demo config:
 *   Carrier: BCBS — Blue Cross HMO Blue
 *   Flow 1: GI → Screening Colonoscopy → Click Tufts (14/14 sources, $0 ACA)
 *   Flow 2: Derm → Skin Biopsy → Click CHA Cambridge (11/11 sources, $395/$39)
 *
 * Prerequisites:
 *   - Backend: MONGODB_URI=mongodb://localhost:27017 uv run uvicorn app.main:app --port 8000
 *   - Frontend: npm run dev (port 8081)
 */

import { test, expect } from '@playwright/test';

const BASE = 'http://localhost:8081';
const PAUSE = 1500; // ms between actions for screen recording pacing

function wait(ms = PAUSE) {
  return new Promise(r => setTimeout(r, ms));
}

test('CareCost Demo — GI Screening + Derm Biopsy', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  // ═══════════════════════════════════════════════
  // FLOW 1: GI — Screening Colonoscopy (BCBS HMO)
  // ═══════════════════════════════════════════════

  // Landing page
  await page.goto(BASE);
  await wait(2000);

  // Navigate to onboarding
  await page.click('text=Get started free');
  await wait();

  // Step 1: About You
  await page.fill('input[type="text"]', 'Sarah Chen');
  await wait(500);
  await page.getByRole('textbox', { name: 'Date of birth' }).fill('03/15/1978');
  await wait(500);
  await page.getByRole('textbox', { name: '02101' }).fill('02115');
  await wait();
  await page.click('button:has-text("Continue")');
  await wait();

  // Step 2: Coverage — Select BCBS
  await page.getByRole('combobox').filter({ hasText: 'Select your insurer' }).click();
  await wait(800);
  await page.getByRole('option', { name: 'Blue Cross Blue Shield (BCBS)' }).click();
  await wait();

  // Select HMO Blue plan
  await page.getByRole('combobox').filter({ hasText: 'Select a plan' }).click();
  await wait(800);
  await page.getByRole('option', { name: 'Blue Cross HMO Blue (HMO)' }).click();
  await wait();

  // Verify auto-fill
  await expect(page.getByRole('spinbutton').first()).toHaveValue('500'); // deductible
  await wait();
  await page.click('button:has-text("Continue")');
  await wait();

  // Step 3: Specialty — GI (default)
  await page.click('button:has-text("Continue")');
  await wait();

  // Step 4: Procedure — Colon → Screening
  await page.click('button:has-text("Colon / rectum")');
  await wait();
  await page.click('button:has-text("Screening")');
  await wait();

  // Confirm procedure
  await expect(page.locator('text=Screening colonoscopy')).toBeVisible();
  await expect(page.locator('text=CPT 45378')).toBeVisible();
  await wait();
  await page.click('button:has-text("Use this for estimates")');
  await wait();
  await page.click('button:has-text("Finish setup")');
  await wait();

  // View map
  await page.click('button:has-text("View map")');
  await wait(3000); // let map + data load

  // Verify map has price pins
  await expect(page.locator('text=Screening colonoscopy')).toBeVisible();
  await wait(2000);

  // Click Tufts Medical Center in the list (best data: 14/14 sources)
  await page.click('button:has-text("Tufts Medical Center")');
  await wait(2000);

  // Click a doctor to see expanded ProviderCard
  const tuftsDoctor = page.locator('[class*="cursor-pointer"]').filter({ hasText: 'Gastroenterology' }).filter({ hasText: 'Tufts Medical Center' }).first();
  await tuftsDoctor.click();
  await wait(2000);

  // Verify $0 ACA preventive
  await expect(page.locator('text=ACA preventive')).toBeVisible();
  await wait();

  // Expand "All price sources"
  await page.click('button:has-text("All price sources")');
  await wait(3000); // let viewer read the sources

  // Verify key sources visible
  await expect(page.locator('text=BCBS negotiated rate')).toBeVisible();
  await expect(page.locator('text=BCBS TiC (insurer-reported)')).toBeVisible();
  await expect(page.locator('text=FAIR Health 80th %ile')).toBeVisible();
  await wait(3000);

  // ═══════════════════════════════════════════════
  // FLOW 2: Derm — Skin Biopsy
  // ═══════════════════════════════════════════════

  // Go back to onboarding to switch specialty
  await page.goto(`${BASE}/onboarding`);
  await wait();

  // Fill step 1 again
  await page.fill('input[type="text"]', 'Sarah Chen');
  await page.getByRole('textbox', { name: 'Date of birth' }).fill('03/15/1978');
  await page.getByRole('textbox', { name: '02101' }).fill('02115');
  await page.click('button:has-text("Continue")');
  await wait();

  // Step 2: Same BCBS HMO
  await page.getByRole('combobox').filter({ hasText: 'Select your insurer' }).click();
  await wait(500);
  await page.getByRole('option', { name: 'Blue Cross Blue Shield (BCBS)' }).click();
  await wait(500);
  await page.getByRole('combobox').filter({ hasText: 'Select a plan' }).click();
  await wait(500);
  await page.getByRole('option', { name: 'Blue Cross HMO Blue (HMO)' }).click();
  await wait();
  await page.click('button:has-text("Continue")');
  await wait();

  // Step 3: Switch to Dermatology
  await page.getByRole('combobox').click();
  await wait(800);
  await page.getByRole('option', { name: 'Dermatology' }).click();
  await wait();
  await page.click('button:has-text("Continue")');
  await wait();

  // Step 4: Biopsy → Shave/tangential
  await page.click('button:has-text("Biopsy")');
  await wait();
  await page.click('button:has-text("Shave / tangential")');
  await wait();

  // Confirm
  await expect(page.locator('text=Skin Biopsy')).toBeVisible();
  await expect(page.locator('text=CPT 11102')).toBeVisible();
  await wait();
  await page.click('button:has-text("Use this for estimates")');
  await wait();
  await page.click('button:has-text("Finish setup")');
  await wait();

  // View map
  await page.click('button:has-text("View map")');
  await wait(3000);

  // Click CHA Cambridge Hospital (11/11 sources, best derm data)
  await page.click('button:has-text("CHA Cambridge Hospital")');
  await wait(2000);

  // Expand price sources at hospital level
  await page.click('button:has-text("Price sources")');
  await wait(3000);

  // Let viewer read the derm pricing
  await wait(3000);

  console.log('Demo complete!');
});
