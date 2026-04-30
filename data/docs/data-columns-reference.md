# Boston GI Healthcare Price Transparency Data

**Scope:** 9 Boston hospitals with GI programs × 17 GI CPT codes × BCBS + Aetna
**Built:** 2026-03-28
**For:** YHack 2026 — Provenance-First Healthcare Shopping Assistant

---

## Quick Start

**One CSV for the backend:** `hospital_rates.csv` (30 KB, 147 rows × 28 columns)

```python
import pandas as pd
df = pd.read_csv("hospital_rates.csv")

# Colonoscopy prices across all hospitals
df[df.cpt == "45378"][["hospital_name", "bcbs_price", "aetna_price", "discounted_cash", "turquoise_bundled_price"]]
```

**Supporting files:**
- `plan_configs.json` — insurance plan designs (deductible, coinsurance, OOP max)
- `boston_gi_providers.json` — 200 gastroenterologists (NPI, address, phone)

---

## CSV Column Reference

### Columns 1-7: Hospital + Procedure Identity

| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `hospital_id` | string | Short ID (mgh, brigham, bidmc, bmc, tufts, bmc_brighton, faulkner, childrens, dana_farber) |
| 2 | `hospital_name` | string | Full hospital name |
| 3 | `neighborhood` | string | Boston neighborhood |
| 4 | `system` | string | Health system (Mass General Brigham, Beth Israel Lahey, etc.) |
| 5 | `data_completeness` | enum | `full` = has payer rates, `gross_only` = only chargemaster |
| 6 | `cpt` | string | CPT/HCPCS procedure code |
| 7 | `cpt_desc` | string | Human-readable procedure name |

### Columns 8-11: CMS-Required Charge Types (Hospital Published)

| # | Column | Type | Source | Description |
|---|--------|------|--------|-------------|
| 8 | `gross_charge` | float | Hospital MRF | Chargemaster sticker price. Nobody pays this. |
| 9 | `discounted_cash` | float | Hospital MRF | Self-pay/uninsured rate. **Facility fee only** — does NOT include physician or anesthesia. |
| 10 | `de_identified_min` | float | Hospital MRF | Lowest negotiated rate across all payers at this hospital. |
| 11 | `de_identified_max` | float | Hospital MRF | Highest negotiated rate across all payers. |

### Columns 12-18: Payer-Specific Negotiated Rates

| # | Column | Type | Source | Description |
|---|--------|------|--------|-------------|
| 12 | `bcbs_price` | float | Hospital MRF or BCBS TiC | BCBS negotiated rate. **The key number for BCBS-insured patients.** |
| 13 | `bcbs_source` | string | — | Where bcbs_price came from: `estimated_amount`, `negotiated_dollar`, or `bcbs_tic_insurer_mrf` |
| 14 | `bcbs_plan` | string | — | Which BCBS plan this rate is for |
| 15 | `aetna_price` | float | Hospital MRF | Aetna negotiated rate (only available at Tufts, BMC, BMC Brighton) |
| 16 | `aetna_source` | string | — | Where aetna_price came from |
| 17 | `harvard_pilgrim_price` | float | Hospital MRF | Harvard Pilgrim rate (bonus payer) |
| 18 | `uhc_price` | float | Hospital MRF | UnitedHealthcare rate (bonus payer) |

### Column 19: Cross-Validation

| # | Column | Type | Source | Description |
|---|--------|------|--------|-------------|
| 19 | `bcbs_tic_rate` | float | BCBS MA TiC file | BCBS rate from insurer-published file. Use to cross-validate `bcbs_price`. If both exist, they should be similar. |

### Columns 20-22: Benchmark Prices (Other Sources)

| # | Column | Type | Source | Description |
|---|--------|------|--------|-------------|
| 20 | `turquoise_bundled_price` | float | Turquoise Health | All-in bundled price (facility + physician + anesthesia). Only for colonoscopy + CT abdomen. |
| 21 | `turquoise_quality_rating` | int | Turquoise Health | Hospital quality score (1-5, 5 = best) |
| 22 | `masscomparecare_total_paid` | float | MA APCD (CY2022) | **Ground truth**: actual total paid from insurance claims. Only for colonoscopy. |

### Columns 23-28: FAIR Health Regional Benchmarks

These are **not hospital-specific** — they're the 80th percentile benchmark for Boston ZIP 02114. Use to estimate unbundled cost components.

| # | Column | Type | Description |
|---|--------|------|-------------|
| 23 | `fh_physician_in_network` | float | Doctor's professional fee (in-network) |
| 24 | `fh_physician_oon` | float | Doctor's professional fee (out-of-network/uninsured) |
| 25 | `fh_anesthesia_in_network` | float | Anesthesiologist fee (in-network) |
| 26 | `fh_facility_hosp_in_network` | float | Hospital outpatient facility fee (in-network) |
| 27 | `fh_facility_asc_in_network` | float | Ambulatory surgery center facility fee (in-network) |
| 28 | `fh_pathology_in_network` | float | Pathology/biopsy fee if applicable (in-network) |

---

## How to Calculate Consumer Price

### Insured Path (BCBS or Aetna)

```python
# 1. Get the negotiated rate (the "allowed amount")
allowed = row['bcbs_price']  # or aetna_price

# 2. Get plan design from plan_configs.json
deductible = 1500  # BCBS PPO
coinsurance = 0.20
oop_max = 6000

# 3. Calculate OOP
deductible_remaining = 1500  # user input or mock scenario
patient_pays = min(
    deductible_remaining + max(0, allowed - deductible_remaining) * coinsurance,
    oop_max  # cap
)

# 4. For all-in estimate, add physician + anesthesia
total_facility = allowed  # from bcbs_price (hospital facility fee)
total_physician = row['fh_physician_in_network'] or 0  # ~$735 for colonoscopy
total_anesthesia = row['fh_anesthesia_in_network'] or 0  # ~$770 for colonoscopy
all_in = total_facility + total_physician + total_anesthesia

# 5. Validate against MassCompareCare (if available)
if row['masscomparecare_total_paid']:
    print(f"Our estimate: ${all_in:.0f} vs actual paid: ${row['masscomparecare_total_paid']}")
```

### Cash/Self-Pay Path

```python
cash_facility = row['discounted_cash']  # hospital published cash price
# Add physician + anesthesia from FAIR Health
total_cash = cash_facility + (row['fh_physician_oon'] or 0) + (row['fh_anesthesia_in_network'] or 0)

# Or use Turquoise bundled price (already includes everything)
turquoise_total = row['turquoise_bundled_price']  # all-in, no unbundling needed
```

---

## Price Source Priority (Fallback Chain)

For **BCBS negotiated rate**, use the first available:
1. `bcbs_price` where `bcbs_source` = `negotiated_dollar` (most precise)
2. `bcbs_price` where `bcbs_source` = `estimated_amount` (MGB hospitals use this)
3. `bcbs_price` where `bcbs_source` = `bcbs_tic_insurer_mrf` (from BCBS's own TiC file)
4. `turquoise_bundled_price` (bundled, includes physician+anesthesia — not directly comparable)
5. `fh_facility_hosp_in_network` (regional benchmark, not hospital-specific)

For **cash price**, use:
1. `discounted_cash` + `fh_physician_oon` + `fh_anesthesia_in_network` (unbundled)
2. `turquoise_bundled_price` (already bundled)

For **validation**, compare against:
- `masscomparecare_total_paid` — actual claims data (ground truth, colonoscopy only)
- `bcbs_tic_rate` — cross-validates `bcbs_price` from hospital side

---

## Hospital Coverage Summary

| Hospital | BCBS | Aetna | Cash | Gross | Source |
|----------|------|-------|------|-------|--------|
| MGH | $3,411 | — | $2,912 | $3,883 | HPT + TiC |
| Brigham | $2,963 | — | $2,912 | $3,883 | HPT + TiC |
| BIDMC | — | — | — | $2,406 | Gross only (Turquoise: $3,128) |
| BMC | $1,251 | $1,501 | $418 | $1,672 | HPT |
| Tufts | $1,641 | $1,617 | $1,811 | $2,587 | HPT + TiC |
| BMC Brighton | $1,115 | $1,115 | $609 | $1,354 | HPT + TiC |
| Faulkner | $3,017 | — | $2,722 | $3,629 | HPT |
| Children's | $255 | — | $1,947 | $1,947 | TiC (low rate = pediatric?) |
| Dana-Farber | $60 | — | $2,519 | $3,359 | TiC (low rate = oncology-specific?) |

*Prices shown for colonoscopy (CPT 45378). Children's and Dana-Farber TiC rates appear unusually low — may reflect partial/professional-only component. Flag to user with provenance.*

---

## 17 GI CPT Codes

| CPT | Description | Category |
|-----|-------------|----------|
| 43235 | EGD diagnostic | Upper Endoscopy |
| 43239 | EGD with biopsy | Upper Endoscopy |
| 43244 | EGD band ligation | Upper Endoscopy |
| 43249 | EGD with dilation | Upper Endoscopy |
| 43255 | EGD bleeding control | Upper Endoscopy |
| 43259 | EGD with ultrasound | Upper Endoscopy |
| 45378 | Colonoscopy diagnostic | Colonoscopy |
| 45380 | Colonoscopy with biopsy | Colonoscopy |
| 45384 | Colonoscopy polyp removal (hot) | Colonoscopy |
| 45385 | Colonoscopy polyp removal (snare) | Colonoscopy |
| 45388 | Colonoscopy ablation | Colonoscopy |
| 74176 | CT abdomen/pelvis w/o contrast | Imaging |
| 74177 | CT abdomen/pelvis w/ contrast | Imaging |
| 74178 | CT abdomen/pelvis w/ and w/o contrast | Imaging |
| 76700 | Abdominal ultrasound complete | Imaging |
| 76705 | Abdominal ultrasound limited | Imaging |
| 91110 | GI tract capsule endoscopy | Capsule |

---

## Data Sources (6 total)

| # | Source | Legal Basis | What It Provides | File |
|---|--------|------------|------------------|------|
| 1 | Hospital MRFs | CMS HPT Rule (45 CFR 180) | Per-payer negotiated rates, cash, gross, min, max | 9 hospitals downloaded |
| 2 | BCBS MA TiC | CMS TiC Rule (45 CFR 147.212) | BCBS negotiated rates from insurer side | 111 MB file, stream-parsed |
| 3 | FAIR Health | Private (50B+ claims) | Physician/anesthesia/facility fee split by ZIP | Playwright scraped |
| 4 | MassCompareCare | MA APCD (state law) | Real total-paid amounts at named providers | Playwright scraped |
| 5 | Turquoise Health | Private (HPT + TiC + claims) | Bundled all-in cash prices + quality ratings | Playwright scraped |
| 6 | NPPES | CMS provider registry | Gastroenterologist directory (NPI, address) | API queried |

---

## Key Caveats

1. **`discounted_cash` is facility fee only** — add FAIR Health physician + anesthesia columns for all-in cash estimate
2. **Children's and Dana-Farber TiC rates are suspiciously low** — $60-$255 for colonoscopy from BCBS TiC file. Likely professional component only, not facility. Flag with provenance.
3. **BIDMC has no payer-specific rates from any source** — only gross charge + Turquoise bundled price
4. **MGB hospitals (MGH, Brigham, Faulkner) use `estimated_amount`** instead of `negotiated_dollar` — same meaning, different field in their MRF
5. **MassCompareCare data is CY2022** — two years old, prices have likely increased
6. **FAIR Health columns are regional benchmarks (ZIP 02114)** — same values for all hospitals in a row. Not hospital-specific.
7. **VA Boston and Lemuel Shattuck** are exempt from price transparency rules — not in the CSV

---

## Files in This Directory

| File | Purpose | Size |
|------|---------|------|
| **`hospital_rates.csv`** | **THE file. Give this to the backend.** | 30 KB |
| **`plan_configs.json`** | Insurance plan designs for OOP calculation | 4 KB |
| **`boston_gi_providers.json`** | 200 gastroenterologists (NPI, address) | 463 KB |
| `README.md` | This documentation | — |
| `backend_ready.json` | Same data as CSV but in JSON (legacy) | 453 KB |
| `build_csv.py` | Script that generates hospital_rates.csv | — |
| `build_backend_data.py` | Script that generates backend_ready.json | — |
| `extract_gi.py` | Script that extracts GI CPTs from hospital MRFs | — |
| `parse_bcbs_tic.py` | Script that stream-parses BCBS TiC file | — |
| `fairhealth_boston_gi.json` | FAIR Health scraped data | 4 KB |
| `masscomparecare_boston_gi.json` | MassCompareCare scraped data | 3 KB |
| `turquoise_boston_*.json` | Turquoise Health scraped data | 5 KB |
| `bcbs_tic_boston_gi.json` | BCBS TiC matched rates | 105 KB |
| `bcbs_ma_hmo_blue.json.gz` | Raw BCBS TiC file (don't load into app) | 111 MB |
| `*_standardcharges.*` | Raw hospital MRF files (don't load into app) | ~155 MB |
