# Government-Mandated Data Sources & Consumer Estimate Requirements

**Date:** 2026-03-28
**Project:** YHack 2026 — Provenance-First Healthcare Shopping
**Scope:** Boston, MA (ZIPs: 02114, 02215, 02115, 02111, 02118, 02130, 02129)
**Validated:** 2026-03-28 (web-verified, 7 corrections applied from original draft)

---

## ANSWER 1: All Government-Mandated Data Sources

### Source A: Hospital Price Transparency Rule (HPT)

**Legal basis:** 45 CFR Part 180 | **Effective:** Jan 2021 | **Applies to:** ~7,000 hospitals (CMS estimate: 7,098 as of July 2023)

**5 Required Standard Charge Types:**

1. **Gross charge** (chargemaster sticker price — 基本没人按这个价付)
2. **Discounted cash price** (自费价 — 起点, 不是终点)
3. **Payer-specific negotiated charge** (per insurer per plan)
4. **De-identified minimum** (lowest negotiated rate across all payers)
5. **De-identified maximum** (highest negotiated rate across all payers)

**Required Data Fields:**

- **Hospital metadata:** hospital_name, last_updated_on, version, location_name, hospital_address, type_2_npi, license_number, attester_name, attestation
- **Service:** description, code (CPT/HCPCS/MS-DRG/APC/NDC/RC/ICD/LOCAL/CDT/CDM...), code_type, setting (inpatient/outpatient/both), drug_unit_of_measurement, drug_type_of_measurement, modifiers
- **Charges:** standard_charge|gross, standard_charge|discounted_cash, standard_charge|[payer]|[plan]|negotiated_dollar, negotiated_percentage, negotiated_algorithm, methodology (case rate/fee schedule/% of billed/per diem/other), standard_charge|min, standard_charge|max
- **New Apr 2026 stats:** median_amount|[payer]|[plan], 10th_percentile, 90th_percentile, count

**Sample Row:**

```
description: "MRI Brain without contrast"
code: "70551" | type: "CPT" | setting: "outpatient"
payer: "Aetna" | plan: "Choice POS II"
gross: $4,200 | discounted_cash: $1,890
negotiated_dollar: $1,250 | methodology: "fee schedule"
min: $890 | max: $2,100
```

**Format:** CSV or JSON, per hospital (~1MB–500MB each)
**Access:** Crawl ~7,000 hospital websites; no central API. CMS schema + validator on GitHub (CMSgov/hospital-price-transparency).
**Compliance reality:** ~21% fully compliant (Patient Rights Advocate, Nov 2024 Seventh Semi-Annual Report). PatientRightsAdvocate found 83% of 31 surveyed MA hospitals noncompliant — naming MGH, BWH, BMC, Children's, and Tufts specifically.
**Value for demo:** HIGH — direct per-payer negotiated rates AND cash prices per hospital per CPT code.

**Boston Hospital MRF Files (all verified 2026-03-28):**

| Hospital | System | Format | Size | NPI |
|---|---|---|---|---|
| Massachusetts General Hospital | Mass General Brigham | ZIP | 31.5 MB | 1023049236 |
| Brigham and Women's Hospital | Mass General Brigham | ZIP | 26.0 MB | 1790717650 |
| Beth Israel Deaconess Medical Center | Beth Israel Lahey | JSON | 9.4 MB | 1598922205 |
| Boston Medical Center | Independent | CSV ZIP | 43.0 MB | 1689892457 |
| Tufts Medical Center | Tufts Medicine | CSV ZIP | 84.2 MB | 1730132515 |
| Dana-Farber Cancer Institute | Dana-Farber | JSON | 4.0 MB | 1851333686 |
| Boston Children's Hospital (Longwood) | BCH | JSON | 131.9 MB | 1710087127 |
| Mount Auburn Hospital | Beth Israel Lahey | JSON | 3.8 MB | 1649254491 |
| New England Baptist Hospital | Beth Israel Lahey | JSON | 3.1 MB | — |

---

### Source B: Transparency in Coverage Rule (TiC)

**Legal basis:** 45 CFR 147.212 (MRF posting) + 45 CFR 147.211 (cost-sharing estimator) | **Effective:** Jul 2022 | **Applies to:** All group health plans + issuers

#### B1: In-Network Rate Files
**Fields:**

- **Plan metadata:** reporting_entity_name/type, plan_name, plan_id, plan_market_type
- **Provider:** npi[], tin, business_name, network_name
- **Rate:** billing_code (CPT/HCPCS/DRG/NDC...), billing_code_type, negotiation_arrangement (ffs/bundle/capitation), negotiated_rate, negotiated_type (negotiated/derived/fee schedule/percentage/per diem), billing_class (professional/institutional), setting, expiration_date, service_code[], billing_code_modifier[]

**Sample:**

```json
{
  "billing_code": "70551", "billing_code_type": "CPT",
  "negotiated_rates": [{
    "provider_references": [1, 42],
    "negotiated_prices": [{
      "negotiated_rate": 1247.50,
      "negotiated_type": "negotiated",
      "billing_class": "institutional",
      "setting": "outpatient",
      "expiration_date": "2026-12-31"
    }]
  }]
}
```

#### B2: Out-of-Network Allowed Amounts
**Fields:** billing_code, allowed_amount, billed_charge, npi[], tin, billing_class
**Value:** Shows what payers actually paid for OON claims — useful for estimating balance billing exposure.

#### B3: Prescription Drug Pricing — DEFERRED
Enforcement deferred since Aug 2021. Deferral rescinded Sept 2023 but technical specs never released. Trump administration proposed further delays Dec 2025. Effectively still not in force.

**Format:** JSON (gzip), updated monthly. Size: 100+ TB compressed across all payers (Trilliant Health found >20 TB from Aetna + UHC alone).
**Access:** Each payer hosts independently. Index files point to thousands of part files.

**Boston Insurer TiC Portals (all verified 2026-03-28):**

| Insurer | Market Share | Portal |
|---|---|---|
| **BCBS of Massachusetts** | ~50%+ (dominant) | transparency-in-coverage.bluecrossma.com/ |
| **Harvard Pilgrim** (Point32Health) | #2 regional | harvardpilgrim.org/public/machine-readable-files |
| **Tufts Health Plan** (Point32Health) | #2 regional | tuftshealthplan.com/visitor/legal-notices/machine-readable-files |
| **Aetna** | National | health1.aetna.com |
| **UnitedHealthcare** | National | transparency-in-coverage.uhc.com/ |
| **Cigna** | National | cigna.com/legal/compliance/machine-readable-files |

**Value for demo:** HIGHEST — the actual negotiated rate between a specific payer and provider. But impractical to query raw files at hackathon scale → use Turquoise Health / MassCompareCare as pre-processed shortcuts.

---

### Source C: No Surprises Act (NSA)

**Legal basis:** Public Law 116-260 | **Effective:** Jan 2022

#### C1: Good Faith Estimate (GFE) — ACTIVE
**For:** Uninsured/self-pay patients, upon scheduling or request
**Required elements:**

- Patient info, date of service
- Itemized list of ALL expected services across ALL providers (this is the key — it bundles facility + professional + ancillary)
- Per item: diagnosis code (ICD-10), service code (CPT/HCPCS/DRG/NDC), expected charge ($)
- Each provider's name, NPI, TIN
- Dispute resolution info (if final bill exceeds GFE by >$400)

**Sample GFE (knee arthroscopy):**

```
Surgeon (NPI 1234567890):
  CPT 29881 - Arthroscopy knee, surgical:     $4,500
  CPT 29877 - Arthroscopy knee, debridement:  $1,200
Anesthesia Group (NPI 9876543210):
  CPT 01382 - Anesthesia for knee:            $1,800
Hospital Facility (NPI 1111111111):
  REV 0360 - Operating Room:                  $3,200
  REV 0710 - Recovery Room:                   $  800
TOTAL ESTIMATED:                              $11,500
```

**Format:** Paper or electronic (not machine-readable at scale). Per-patient, per-request only.
**Value for demo:** CONCEPTUAL — demonstrates why discounted_cash_price alone is insufficient. The GFE is the only mechanism that bundles all charges. But it's not bulk data you can query.

#### C2: Advanced EOB (AEOB) — ENFORCEMENT DEFERRED
Would have required insurers to proactively send cost estimates before scheduled services (including deductible accumulator, cost-sharing math). Proposed AEOB rule expected March 2026. Departments have acknowledged "significant operational challenges." Still effectively deferred as of March 2026.

---

### Source D: Medicare Fee Schedules (Fully Public)

#### D1: Medicare Physician Fee Schedule (MPFS)
**Fields:** HCPCS, modifier, Work_RVU, PE_RVU (facility + non-facility), MP_RVU, Total_RVU, GPCI_Work/PE/MP, Non-Facility_Fee, Facility_Fee, Conversion_Factor

**CY2026 Conversion Factors (per Oct 31, 2025 final rule):**
- **$33.40** (non-qualifying APM — use this as default)
- **$33.57** (qualifying APM participants)

**Sample:** CPT 99213 | Office visit level 3 | Non-Facility: ~$90 | Facility: ~$68 | Locality: Boston

**Formula:** Payment = (Work_RVU × GPCI_W + PE_RVU × GPCI_PE + MP_RVU × GPCI_MP) × CF
**Format:** CSV, ~200MB. **Access:** Direct download from pfs.data.cms.gov
**Value:** THE universal benchmark. Commercial rates expressed as "% of Medicare" (~196% national average per Milliman 2025; MA averages ~180–200%).

#### D2: OPPS (Outpatient Prospective Payment)
**Fields:** HCPCS, APC, relative_weight, payment_rate, copayment
**Sample:** CPT 70551 | MRI brain w/o contrast | APC 5571 | Payment: $303.55 | Copay: $60.71
**Value:** Benchmark for outpatient facility fees (separate from physician fees).

#### D3: Medicare Provider Utilization & Payment Data
**Fields:** NPI, provider_name, specialty, HCPCS, total_beneficiaries, total_services, avg_submitted_charge, avg_allowed_amount, avg_payment
**Sample:** NPI 1234567890 | Smith MD | Ortho | CPT 27447 (TKR) | Avg Submitted: $62,450 | Avg Allowed: $18,750 | Avg Payment: $14,980
**Value:** Shows what Medicare actually pays specific providers. The submitted-to-allowed ratio reveals chargemaster markup.

#### D4: Inpatient PPS (DRG weights + base rates)
**Value:** Benchmark for hospital admissions.

#### D5: ASC Payment System
**Value:** Benchmark for ambulatory surgical centers (often cheaper than hospital outpatient).

---

### Source E: Medicaid Fee Schedules

**Legal basis:** 42 CFR 447.203 | **New mandate:** By Jul 2026, all states must publish FFS rates online + publish comparative payment rate analysis vs Medicare for **primary care, OB/GYN, and outpatient mental health/SUD services** (not all services). 80% of Medicare floor for rate reductions.
**Fields:** procedure_code, rate, facility/non-facility, prior_auth, % of Medicare
**Access:** 50 separate state sources, mostly PDF or Excel. No standard format.
**Value:** Floor benchmark (typically 60-80% of Medicare).

**Massachusetts-specific:** MA publishes via EOHHS/MassHealth. The MA APCD (via CHIA / MassCompareCare.gov) includes Medicaid paid amounts alongside commercial claims — making MA one of the most transparent states for cross-payer comparison.

---

### Source F: Other Mandated Disclosures

| Source | Contains | Format | Value |
|---|---|---|---|
| Summary of Benefits (SBC) | Deductible, OOP max, copay/coinsurance per service category, coverage examples | Standardized 8-page PDF | CRITICAL for OOP math — but not machine-readable |
| Provider Directories (NPPES) | NPI, name, specialty, address, taxonomy | API at npiregistry.cms.hhs.gov | HIGH for provider identity; ~48–52% of entries contain inaccuracies (CMS/OIG) |
| Hospital Financial Assistance | Eligibility thresholds (% FPL), discount schedules | Hospital websites (501(r)) | Relevant for self-pay patients below 400% FPL |

---

## ANSWER 2: Data Points Needed for Accurate Consumer Estimates

### The Two Paths

**Path 1: Insured (with one of demo payers — BCBS MA primary)**

```
OOP = min(
  deductible_remaining + (allowed_amount - deductible_remaining) × coinsurance,
  oop_max_remaining
)
```

**Path 2: Cash / Self-Pay**

```
Expected bill = Σ (discounted_cash_price per line item across all billing entities)
               + potential ancillary services
Actual range = GFE total (if obtainable) or HPT cash price × bundling multiplier
```

### Required Data Points (Priority Order)

#### Tier 1: MUST HAVE (without these, estimate is meaningless)

| # | Data Point | Best Source → Fallback | Why |
|---|---|---|---|
| 1 | Allowed amount / negotiated rate | BCBS MA MRF → Turquoise SSP → HPT file → Medicare × Milliman multiplier | THE price. Everything else is applied to it. |
| 2 | Deductible remaining | Browser portal retrieval → patient self-report → show both scenarios | Creates 5x variance. The #1 reason existing estimators are useless. |
| 3 | Coinsurance rate or copay | Patient SBC → self-report → assume 20% | Determines patient's share after deductible. |
| 4 | In-network status | Browser-verified directory → published directory → flag unverified | Wrong network flips the entire calculation. |
| 5 | Discounted cash price (for cash path) | HPT file → Turquoise → FAIR Health benchmark | Starting point for self-pay estimate. |

#### Tier 2: SHOULD HAVE (narrows range by 30-50%)

| # | Data Point | Source | Impact |
|---|---|---|---|
| 6 | OOP max remaining | Same as deductible | Cap on total patient responsibility |
| 7 | Place of service (facility vs office) | NPPES taxonomy | Same CPT costs 2-3x more in hospital outpatient vs freestanding |
| 8 | Plan type (HMO/PPO/EPO) | Patient self-report | Determines OON coverage |
| 9 | Ancillary service estimates | Turquoise SSP bundles, NCCI edits | The "surprise bills" — anesthesia, labs, imaging |
| 10 | Facility + professional fee split | Modifier 26/TC data | Warns about multiple bills |

#### Tier 3: NICE TO HAVE (improves accuracy + trust)

| # | Data Point | Source | Impact |
|---|---|---|---|
| 11 | Regional benchmark | FAIR Health (50B+ claims), CMS PPL | "Is this price normal for your area?" |
| 12 | Geographic cost adjustment | Medicare GPCI | Adjusts for local labor/rent costs |
| 13 | Hospital cost-to-charge ratio | CMS HCRIS | Detects inflated chargemasters |
| 14 | Charity care eligibility | Hospital 501(r) policy | Alternative for low-income self-pay patients |
| 15 | Provider quality/volume | CMS Care Compare | Cost-quality tradeoff context |

---

## Beyond Government Data: Boston-Specific Supplementary Sources

| Rank | Source | Contains | Access | Demo Value |
|---|---|---|---|---|
| 1 | **MassCompareCare.gov** (MA APCD public layer) | Claims-based paid amounts for ~300 procedures at named MA providers + quality metrics | Free web tool (Playwright for extraction) | **HIGHEST for Boston** — real paid amounts, not list prices. E.g., colonoscopy $969–$1,624 |
| 2 | **FAIR Health** (fairhealthconsumer.org) | Benchmark allowed amounts by CPT × ZIP (50B+ claims). Covers E&M codes Turquoise misses. | Free consumer site (Playwright for Boston ZIPs) | HIGH — best free sanity check, fills E&M gap |
| 3 | **Turquoise Health SSP API** | Pre-normalized bundles with real prices per facility | Free consumer / paid enterprise API | HIGH — skip raw MRF parsing for procedural services. No E&M coverage. |
| 4 | **Milliman Commercial Benchmarking** | Commercial rates as % of Medicare by state (~196% national, ~180-200% MA) | Free summary report | HIGH — the conversion factor from Medicare to commercial |
| 5 | **CMS HCRIS** (Hospital Cost Reports) | Cost-to-charge ratios per hospital | Free bulk download | MEDIUM — detects price inflation |
| 6 | **NewChoiceHealth** | 60 Boston-area providers for common procedures, named facility comparisons | Free web tool | MEDIUM — good for validation |
| 7 | **DoltHub** transparency-in-coverage | Pre-processed TiC data in queryable DB | Free | LOW for Boston — only Carney Hospital listed |

**Note on MA APCD (raw via CHIA):** The definitive all-payer claims dataset for MA. Requires IRBNet account + data use agreement with 8–10 week approval. Impractical for hackathon but essential for production. MassCompareCare.gov is the public-facing layer on top of this.

---

## The Cash Price Reality (用户关键洞察)

`discounted_cash_price` in HPT files is just ONE line item. A real visit generates:

```
Scenario: MRI Brain (self-pay)
─────────────────────────────────────────────
HPT discounted_cash_price (CPT 70551):  $1,890  ← what the file shows
+ Radiologist interpretation fee:        $  350  ← separate bill, separate provider
+ Contrast material (if needed):         $  200  ← separate line item
+ Pre-auth / scheduling fee:             $   50  ← some hospitals add this
─────────────────────────────────────────────
Actual expected bill:                   ~$2,490  ← what you actually pay
```

The GFE is the only mechanism that legally bundles all of this for self-pay patients. But it's per-request, not bulk data. For the demo, the approach should be:

1. Show the HPT discounted_cash_price as the base facility price
2. Flag that professional fees and ancillaries are additional (with estimates from Turquoise SSP bundles or FAIR Health)
3. Show provenance: "This is the hospital's published cash price for the facility fee only. Professional fees are typically billed separately."

---

## Corrections Log

7 corrections applied from original draft (validated 2026-03-28):

1. **Hospital count:** ~6,000 → ~7,000 (CMS estimates 7,098)
2. **TiC CFR citation:** 147.211 alone → 147.212 for MRF posting + 147.211 for cost-sharing estimator
3. **Medicare CF:** $32.35 (CY2025) → $33.40/$33.57 (CY2026, per Oct 31, 2025 final rule)
4. **Directory errors:** 55%+ → 48–52% (CMS 2018 audit: 52%, OIG NPPES study: 48%)
5. **91% compliance stat:** Removed — no published source found. 21.1% full compliance confirmed (PRA Nov 2024).
6. **Medicaid comparison scope:** "All services" → primary care, OB/GYN, outpatient mental health/SUD only
7. **State APCD:** CT APCD → MA APCD / MassCompareCare.gov (Boston scope)

---

## Verification Checklist

- [ ] Spot-check one Boston hospital MRF (e.g., Beth Israel 9.4 MB JSON) — confirm schema matches CMS spec
- [ ] Query MassCompareCare.gov for colonoscopy in Boston — confirm named provider pricing
- [ ] Query Turquoise Health for Boston ZIP 02114 — confirm MGH/BWH appear
- [ ] Look up CPT 99213 on FAIR Health for ZIP 02114 — confirm E&M benchmark
- [ ] Verify BCBS MA MRF index file loads at transparency-in-coverage.bluecrossma.com
- [ ] Cross-check Medicare PFS for Boston locality with $33.40 CF
