# Healthcare Price Data Pipeline — Playbook

**Purpose:** Repeatable process for collecting healthcare price transparency data for any specialty + geography + payer combination.
**First run:** GI (gastroenterology) × Boston × BCBS + Aetna (March 2026)
**Next run:** Dermatology × Boston + Cambridge × BCBS

---

## What We Deliver

**3 CSVs + 1 README** per specialty:

| File | Content | Format |
|------|---------|--------|
| `hospital_rates.csv` | One row per hospital × CPT. All price sources merged into 28 columns. | CSV |
| `providers.csv` | Specialist doctors: NPI, name, address, phone. | CSV |
| `plan_configs.csv` | Insurance plan designs: deductible, coinsurance, OOP max. | CSV |
| `README.md` | Column reference, calculation formulas, data caveats. | Markdown |

**Column structure of hospital_rates.csv:**

```
IDENTITY:        hospital_id, hospital_name, neighborhood, system, data_completeness, cpt, cpt_desc
CMS 5 CHARGES:   gross_charge, discounted_cash, de_identified_min, de_identified_max
PAYER RATES:     bcbs_price, bcbs_source, bcbs_plan, aetna_price, aetna_source, harvard_pilgrim_price, uhc_price
CROSS-VALIDATE:  bcbs_tic_rate
BENCHMARKS:      turquoise_bundled_price, turquoise_quality_rating, masscomparecare_total_paid
FAIR HEALTH:     fh_physician_in_network, fh_physician_oon, fh_anesthesia_in_network, fh_facility_hosp_in_network, fh_facility_asc_in_network, fh_pathology_in_network
```

---

## 6 Data Sources

### Source 1: Hospital MRFs (CMS Hospital Price Transparency Rule)

**What:** Each hospital publishes a machine-readable file with 5 charge types (gross, cash, per-payer negotiated, min, max) for every service.
**Legal basis:** 45 CFR Part 180
**Format:** CSV (in ZIP) or JSON. 1 MB – 1 GB per hospital.
**Coverage:** Gross + cash at all hospitals. Payer-specific rates at ~60-70% of hospitals (rest are non-compliant).

**How to get it:**

1. Find the hospital's MRF URL. Each hospital posts a `cms-hpt.txt` file at their web root, or links from their billing/pricing page. For health systems:
   - Mass General Brigham: `massgeneralbrigham.org/content/dam/mgb-global/en/price-transparency/<EIN>_<name>_StandardCharges.zip`
   - Beth Israel Lahey: `bidmc.org/<EIN>_<name>_standardcharges.json`
   - Tufts Medicine: `tuftsmedicine.org/sites/default/files/<date>/<EIN>_<name>_standardcharges.csv.zip`
   - BMC: `bmc.org/sites/default/files/documents/BostonMedicalCenter_standardcharges.xlsx` (non-standard naming)
   - BMC Brighton: `bmchealthsystem.org/wp-content/uploads/<EIN>_<name>_standardcharges.csv.zip`
   - Children's: `childrenshospital.org/sites/default/files/cms-hpt/comp-2026/<EIN>_<name>_StandardCharges.zip`
   - Dana-Farber: hosted on Widen DAM platform (URL found via web search)

2. Download with curl:
   ```bash
   curl -L -o <hospital>_standardcharges.zip "<URL>"
   ```

3. Extract specialty CPT codes using `extract_gi.py` pattern:
   - Define target CPT codes for the specialty
   - Stream-parse CSV/JSON, filter to target CPTs
   - Output per-hospital JSON with all payer rates

4. Combine into `boston_gi_all_payers.json` (or equivalent for new specialty)

**Encoding note:** MGB system files use `latin-1` encoding, not UTF-8.

**Key gotcha:** Some hospitals use `negotiated_dollar`, others use `estimated_amount`. Must coalesce: `price = negotiated_dollar || estimated_amount`.

---

### Source 2: BCBS MA TiC File (Insurer-Published Rates)

**What:** BCBS publishes negotiated rates for every provider in their network. Fills gaps where hospitals are non-compliant (don't publish payer rates on their side).
**Legal basis:** 45 CFR 147.212 (Transparency in Coverage Rule)
**Format:** Gzipped JSON, ~111 MB compressed per plan type.
**Coverage:** Every in-network provider × every billing code.

**How to get it:**

1. Get the index file via Playwright:
   ```
   Navigate to: https://transparency-in-coverage.bluecrossma.com
   Check "Fully-Insured TOC"
   Click Download → Proceed
   Downloads: 2026-03-01_..._index.json (~3.8 MB)
   ```

2. Parse the index to find MA-specific file URLs:
   ```python
   # Key files for MA:
   # "HMO Blue Fully Insured" — most common MA plan
   # "Blue Care Elect Fully Insured" — PPO plan
   # "MA-HMO Blue-23C0" — BlueCard network
   ```

3. Download the rate file (~111 MB):
   ```bash
   curl -L -o bcbs_ma_hmo_blue.json.gz "<signed URL from index>"
   ```
   **Note:** URLs have expiration timestamps in the signature. Download promptly after getting the index.

4. Stream-parse with `parse_bcbs_tic.py`:
   - Uses `ijson` for streaming (never loads full file into memory)
   - First pass: scan `in_network` items, filter to target CPT codes, collect all rate records
   - Second pass: scan `provider_references` to map provider_group_id → NPI
   - Match NPIs to our hospital registry
   - Output: `bcbs_tic_boston_gi.json`

**Adapting for dermatology:** Change the `GI_CPTS` set in `parse_bcbs_tic.py` to dermatology CPT codes. Change `HOSPITAL_NPIS` to dermatology-capable hospital NPIs. Same file, same process.

**Adapting for Cambridge:** Same BCBS file covers all of MA. Just add Cambridge hospital NPIs to the matching set.

---

### Source 3: FAIR Health (Regional Benchmarks)

**What:** 80th percentile benchmark prices by CPT × ZIP, based on 50B+ commercial claims. Breaks down physician fee, anesthesia, facility fee (hospital vs ASC), and pathology separately.
**Format:** Web scraping via Playwright.
**Coverage:** Most CPT codes, but some return N/A for specific ZIPs.

**How to get it (Playwright session):**

```
1. Navigate to: https://www.fairhealthconsumer.org
2. Click "Medical and Hospital Costs"
3. Enter ZIP: 02114 (or target ZIP)
4. Select from dropdown → click "Next"
5. Enter CPT code in search box (e.g., "45378")
6. Terms of Use dialog → click "Agree"
7. Select the CPT radio button → click "Get your cost"
8. Extract prices from the results page:
   - Out-of-Network/Uninsured Price (physician)
   - In-Network Price (physician)
   - Related Costs: Anesthesia, Pathology
   - Facility Costs: ASC price, Hospital Outpatient price
```

**Automation:** After agreeing to Terms once per session, you can loop through CPT codes by navigating directly to:
```
https://www.fairhealthconsumer.org/medical/search/<CPT_CODE>
```
Then click the code option → "Get your cost" → extract from page text.

**Script pattern (from our GI run):**
```javascript
// Playwright code to scrape multiple CPTs
for (const cpt of cptCodes) {
  await page.goto(`/medical/search/${cpt}`);
  await page.getByText(`CODE: ${cpt}`).first().click();
  await page.getByText('Get your cost').first().click();
  await page.waitForTimeout(2000);
  const bodyText = await page.evaluate(() => document.body.innerText);
  // Parse prices from bodyText
}
```

**Output:** `fairhealth_boston_<specialty>.json`

---

### Source 4: MassCompareCare (Real Claims Data)

**What:** Actual total-paid amounts from MA All-Payer Claims Database (CY2022). Named providers, total cost (facility + physician + anesthesia combined). The ground truth.
**Format:** Web scraping via Playwright.
**Coverage:** ~300 common procedures. Limited to what's on the site.

**How to get it (Playwright session):**

```
1. Navigate to: https://www.masscomparecare.gov/cost
2. reCAPTCHA dialog appears → check "I'm not a robot" → Submit
3. Browse by type → click category (e.g., "Colonoscopy and Endoscopy")
4. Select sub-procedure (e.g., "Diagnostic")
5. Enter ZIP in the "zip code" field → press Enter
6. Results table appears with: Provider name, Type, City, Price
```

**Key detail:** reCAPTCHA must be solved once per session. After that, navigation works.

**For dermatology:** Check if MassCompareCare has a "Dermatology" or "Skin Procedures" category. Browse the main `/cost` page to see available categories.

**Output:** `masscomparecare_boston_<specialty>.json`

---

### Source 5: Turquoise Health (Bundled Prices, No Login)

**What:** All-in bundled prices (facility + physician + anesthesia) per provider. Quality ratings (1-5). Based on HPT + TiC + claims data. No login required for consumer search.
**Format:** Web scraping via Playwright.
**Coverage:** ~40 common services. Not all specialties covered.

**How to get it (Playwright session):**

```
1. Navigate to: https://turquoise.health/patients
2. Check available services by searching in the service dropdown
3. For each available service:
   - Navigate to: https://turquoise.health/care/search/?service=<CODE>&location=<ZIP>%2C+MA&plan=specified-no-plan&action=search-bar&sort_by=price-asc
   - Extract provider cards: name, price, city, distance, quality rating
   - Paginate if multiple pages (click page 2, 3...)
```

**Service codes found for GI:**
- `GA002` = Colonoscopy
- `RA004` = CT of Abdomen and Pelvis

**For dermatology:** Search "skin", "biopsy", "excision", "mole", "dermatology" in the service dropdown to find available codes.

**Output:** `turquoise_boston_<service>.json`

---

### Source 6: NPPES (Provider Directory)

**What:** NPI registry — all licensed healthcare providers with name, specialty, address, phone.
**Format:** REST API, no auth required.
**Coverage:** Every provider in the US.

**How to get it:**

```bash
curl -s "https://npiregistry.cms.hhs.gov/api/?version=2.1&taxonomy_description=<SPECIALTY>&city=<CITY>&state=MA&limit=200"
```

**For GI:** `taxonomy_description=Gastroenterology`
**For dermatology:** `taxonomy_description=Dermatology`
**For Cambridge:** Add `&city=Cambridge` or do two calls (Boston + Cambridge)

**Output:** `boston_<specialty>_providers.json` → then convert to `providers.csv`

---

## Step-by-Step Process (for a new specialty)

### Phase 1: Identify Scope (30 min)

1. **Pick CPT codes** for the specialty. Sources:
   - AMA CPT code search
   - FAIR Health category browser (shows common codes per specialty)
   - Ask a domain expert

2. **Identify hospitals** that offer this specialty in the target geography:
   - Query NPPES for specialists → map addresses to hospitals
   - Cross-reference with hospital websites

3. **Check which hospitals have MRFs** (machine-readable files):
   - Reference the hospital URLs from our GI run (most are the same hospitals)
   - For new hospitals: check `<hospital-domain>/cms-hpt.txt`

### Phase 2: Download Hospital MRFs (1-2 hours)

1. Download MRFs for each hospital (if not already downloaded from GI run — same file has ALL procedures):
   ```bash
   curl -L -o <hospital>_standardcharges.<ext> "<URL>"
   ```

2. Create `extract_<specialty>.py` based on `extract_gi.py`:
   - Change `GI_CPTS` dict to new specialty CPTs
   - Keep same extraction functions (CSV, JSON, v3 CSV, XLSX)
   - Run: `uv run python3 extract_<specialty>.py`

3. Output: `boston_<specialty>_all_payers.json`

### Phase 3: Get BCBS TiC Data (30 min)

1. **If BCBS file already downloaded** (same `bcbs_ma_hmo_blue.json.gz` from GI run — it has ALL billing codes):
   - Just update `parse_bcbs_tic.py` with new CPT codes and hospital NPIs
   - Re-run: `uv run python3 parse_bcbs_tic.py`

2. **If not downloaded yet:**
   - Follow Source 2 Playwright steps to get index
   - Download the ~111 MB file
   - Parse with updated CPT codes

3. Output: `bcbs_tic_boston_<specialty>.json`

### Phase 4: Scrape Supplementary Sources (1-2 hours)

Run these Playwright sessions:

1. **FAIR Health** — enter each CPT code, extract physician/facility/anesthesia breakdown
2. **MassCompareCare** — check if specialty procedures are available, extract named provider prices
3. **Turquoise Health** — search for specialty services, extract bundled prices
4. **NPPES** — API call for specialists in target geography

### Phase 5: Build Backend Deliverables (30 min)

1. Update `build_backend_data.py`:
   - Include new specialty rates
   - Merge BCBS TiC data
   - Add new supplementary source data

2. Run `build_csv.py` to generate flat CSV

3. Generate `providers.csv` and `plan_configs.csv` (plan configs reusable across specialties)

4. Copy to delivery folder:
   ```bash
   mkdir -p "data/For Issac/<specialty>"
   cp hospital_rates.csv providers.csv plan_configs.csv README.md "data/For Issac/<specialty>/"
   ```

---

## Adapting for Dermatology × Boston + Cambridge × BCBS

### Dermatology CPT Codes (likely set)

```python
DERM_CPTS = {
    # Office visits (E&M with skin focus)
    "99213": "Office visit est patient lvl 3",
    "99214": "Office visit est patient lvl 4",
    # Skin biopsies
    "11102": "Tangential biopsy skin single lesion",
    "11104": "Punch biopsy skin single lesion",
    "11106": "Incisional biopsy skin single lesion",
    # Lesion excision (benign)
    "11400": "Excision benign lesion trunk/ext 0.5cm or less",
    "11401": "Excision benign lesion trunk/ext 0.6-1.0cm",
    "11402": "Excision benign lesion trunk/ext 1.1-2.0cm",
    # Lesion excision (malignant)
    "11600": "Excision malignant lesion trunk/ext 0.5cm or less",
    "11601": "Excision malignant lesion trunk/ext 0.6-1.0cm",
    "11602": "Excision malignant lesion trunk/ext 1.1-2.0cm",
    # Destruction (cryotherapy, electrodessication)
    "17000": "Destruction benign/premalignant lesion first",
    "17003": "Destruction benign/premalignant lesion 2nd-14th each",
    "17110": "Destruction benign lesions up to 14",
    # Mohs surgery
    "17311": "Mohs surgery first stage trunk/ext up to 5 blocks",
    "17312": "Mohs surgery each additional block",
    "17313": "Mohs surgery first stage head/neck/hands up to 5 blocks",
    # Pathology
    "88305": "Pathology exam tissue intermediate",
    # Phototherapy
    "96910": "Photochemotherapy tar + UVB",
    "96920": "Laser treatment skin <250 sq cm",
}
```
**Verify these before running** — check FAIR Health category browser for what's available.

### Cambridge Hospitals to Add

Query NPPES for dermatologists in Cambridge. Likely hospitals:
- Mount Auburn Hospital (already in our registry)
- Cambridge Health Alliance (already in our registry)
- Any freestanding dermatology clinics

### What's Reusable from GI Run

| Asset | Reusable? | Notes |
|-------|-----------|-------|
| Hospital MRF files (raw) | **YES** | Same files contain ALL procedures. Don't re-download. |
| BCBS TiC file (111 MB) | **YES** | Same file has all billing codes. Just re-parse with new CPTs. |
| `plan_configs.csv` | **YES** | Same BCBS/Aetna plans apply to all specialties. |
| `extract_gi.py` | **TEMPLATE** | Copy, rename, change CPT dict. |
| `parse_bcbs_tic.py` | **TEMPLATE** | Change CPT set + add any new hospital NPIs. |
| `build_csv.py` | **TEMPLATE** | Change column names if needed (e.g., no anesthesia for derm). |
| FAIR Health session | **RE-RUN** | New CPT codes, same ZIP. |
| MassCompareCare | **RE-RUN** | Check if derm procedures available. |
| Turquoise Health | **RE-RUN** | Search for derm services. |
| NPPES | **RE-RUN** | Change taxonomy to "Dermatology". |

### Estimated Time for Dermatology Run

| Phase | Time | Notes |
|-------|------|-------|
| Define CPTs + identify hospitals | 30 min | NPPES query + manual review |
| Extract from existing MRFs | 15 min | Same files, just new CPT filter |
| Re-parse BCBS TiC file | 5 min | Same file, new CPTs |
| FAIR Health Playwright | 30 min | ~20 CPT codes to scrape |
| MassCompareCare Playwright | 15 min | If derm procedures exist |
| Turquoise Playwright | 15 min | If derm services exist |
| Build CSVs + README | 15 min | Template from GI |
| **Total** | **~2 hours** | Vs ~6 hours for GI (first run) |

---

## Files Reference (GI Run)

### Build Scripts (in `data/hospital_mrfs/`)

| Script | Purpose | Dependencies |
|--------|---------|-------------|
| `extract_gi.py` | Extract GI CPTs from 9 hospital MRF files → per-hospital JSON | `openpyxl` (for BMC XLSX) |
| `parse_bcbs_tic.py` | Stream-parse BCBS TiC 111MB file → matched Boston hospital rates | `ijson` |
| `build_backend_data.py` | Combine all sources → `backend_ready.json` | — |
| `build_csv.py` | Convert `backend_ready.json` → `hospital_rates.csv` | — |

### Raw Data Files (don't load into app)

| File | Size | Content |
|------|------|---------|
| `mgh_standardcharges.zip` | 30 MB | MGH full MRF (151 MB unzipped) |
| `brigham_standardcharges.zip` | 25 MB | Brigham full MRF |
| `bidmc_standardcharges.json` | 9 MB | BIDMC full MRF (gross only) |
| `tufts_standardcharges.zip` | 80 MB | Tufts full MRF (1.1 GB unzipped) |
| `bmc_standardcharges.xlsx` | 8.4 MB | BMC full MRF |
| `faulkner_standardcharges.zip` | 13 MB | Faulkner full MRF |
| `bmc_brighton_standardcharges.zip` | 17 MB | BMC Brighton full MRF |
| `childrens_standardcharges.zip` | 4 MB | Children's full MRF |
| `danafaber_standardcharges.json` | 3.8 MB | Dana-Farber full MRF |
| `bcbs_ma_hmo_blue.json.gz` | 111 MB | BCBS MA TiC in-network rates (all codes, all providers) |

### Intermediate Files

| File | Content |
|------|---------|
| `boston_gi_all_payers.json` | 7,556 rows — raw extracted GI data from hospital MRFs |
| `bcbs_tic_boston_gi.json` | 206 BCBS rates matched to Boston hospitals |
| `fairhealth_boston_gi.json` | FAIR Health benchmarks for 8 GI CPTs |
| `masscomparecare_boston_gi.json` | Real claims data for colonoscopy at 17 providers |
| `turquoise_boston_colonoscopy.json` | Turquoise colonoscopy prices at 35 providers |
| `turquoise_boston_ct_abdomen.json` | Turquoise CT abdomen prices at 40 providers |
| `backend_ready.json` | All sources merged (JSON version of hospital_rates.csv) |

### Deliverables (in `data/For Issac/`)

| File | Size | Rows × Cols |
|------|------|-------------|
| `hospital_rates.csv` | 30 KB | 147 × 28 |
| `providers.csv` | 12 KB | 152 × 10 |
| `plan_configs.csv` | 1 KB | 3 × 19 |
| `README.md` | 11 KB | Column reference + formulas |

---

## Known Limitations

1. **BIDMC** publishes zero payer-specific rates in their MRF (17,731 items, all gross only). Not in BCBS HMO Blue network file either. Only Turquoise has a bundled price.

2. **Children's and Dana-Farber TiC rates are suspiciously low** ($60-$255 for colonoscopy). Likely professional component only, not full facility rate. Flag to users.

3. **MassCompareCare data is CY2022** — two years old. Prices have likely increased 5-10%.

4. **FAIR Health returns N/A** for some CPT × ZIP combinations. Approximately 50% coverage for our 17 GI codes.

5. **Turquoise consumer search** only covers ~40 common services. Many specialty procedures won't be available.

6. **BCBS TiC signed URLs expire.** Download promptly after getting the index file. The index itself is stable.

7. **Hospital MRF formats vary wildly.** MGB uses CSV (latin-1 encoding, 2 header rows + data). BMC uses XLSX with non-standard column names. BIDMC/Children's/Dana-Farber use CMS v2.2 JSON. BMC Brighton uses CMS v3.0 CSV with percentile columns. Each requires custom parsing.
