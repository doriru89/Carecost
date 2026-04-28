# Healthcare Price Transparency -- Consolidated Research Landscape

**Date:** 2026-03-27
**Project:** YHack 2026 -- Provenance-First Healthcare Shopping
**Sources merged:** yhack-healthcare-shopping-landscape.md + deep-research-report.md
**Domain Lens:** Healthcare price transparency / consumer cost estimation
**Evidence standard:** Shipped products, published APIs, regulatory filings, peer-reviewed studies

---

## 1. Executive Synthesis

**The landscape in one paragraph:** Healthcare price transparency is in a strange middle state. The US government has mandated that hospitals publish prices (since 2021) and that insurers publish negotiated rates (since 2022). This created an enormous data exhaust -- over 100 TB of machine-readable files from major payers alone. A cottage industry of enterprise data companies (Turquoise Health, Serif Health, Trilliant Health) has emerged to normalize this data, but almost none of it reaches consumers in a usable form. The existing consumer-facing tools either show cash prices only (GoodRx, Sesame, MDsave), show vague benchmarks without plan-specific estimates (FAIR Health), or are insurer-owned estimators that are slow, confusing, and lack provenance. **No tool clearly separates fact from inference from assumption when showing a cost estimate.**

Federal transparency policies have created real "raw ingredients," but the evidence base consistently reports major usability gaps: missing or inconsistent data, file-format complexity, and prices that can be misleading or difficult to interpret without significant normalization and context.

**What is crowded:**
- Enterprise transparency data platforms (Turquoise, Serif, Trilliant, PayerPrice, Payerset)
- Cash-pay/self-pay marketplaces (GoodRx, Sesame, MDsave, Sidecar Health)
- Hospital compliance tools (CMS validators, HPT file generators)

**What is weak / underserved:**
- Consumer-facing out-of-pocket estimation with provenance and uncertainty
- Translating layperson intent ("my knee hurts") into billable service categories
- Helping users understand their own insurance plan (SBC/EOB interpretation)
- Verifying actual in-network status (ghost network problem affects 55%+ of directories)
- Browser-assisted deductible/accumulator retrieval from insurer portals

**Where the biggest consumer pain still exists:**
- 70% of consumers do not price-shop for healthcare at all (Becker's Hospital Review)
- Among those who try, 42% find estimates confusing or hard to understand
- 53% of people using mental health provider directories encounter inaccuracies
- Patients cannot answer "how much will I actually pay?" before booking

**Where our product differentiates:**
- **Provenance-first estimation**: No existing tool tags every number with its source, confidence, and whether it is a fact, inference, or assumption
- **Uncertainty honesty**: Show ranges, not point estimates; show what you do not know
- **Insurance plan understanding**: Help users decode their own plan before estimating cost
- **Intent-to-service mapping**: Translate common complaints into likely service categories with transparency about the mapping
- **Browser-assisted deductible lookup**: Instead of asking users what they've spent, guide them to their insurer portal via browser automation

---

## 2. Research Buckets

### A. Insurer Cost Estimators

**What they are:** Every major insurer (UHC, Cigna, Aetna, BCBS) is required to provide an online cost estimator tool to members since January 2024 (Stage 3 of Transparency in Coverage rule).

**What they do well:**
- Access to actual plan-specific data (deductible status, coinsurance rates, network contracts)
- Can show personalized estimates based on where the member is in their plan year
- Required to cover all items and services as of 2024

**What they do poorly:**
- Extremely hard to use -- users must know clinical terminology, CPT codes, or specific procedure names
- No explanation of how the estimate was calculated
- No uncertainty display -- shows a single number that implies false precision
- Estimates often do not account for ancillary charges (anesthesia, pathology, facility fees)
- Slow, clunky interfaces built for compliance, not for consumer decision-making
- No comparison across providers in a single view

**How they calculate estimates:**
- Use member's actual plan data (deductible progress, coinsurance, OOP max)
- Use contracted/negotiated rates with specific providers
- Often do not account for unbundled services or surprise add-ons

**Provenance / uncertainty:** Almost none. No existing insurer tool explains "this estimate is based on X contracted rate, Y deductible progress, and assumes Z procedures."

**Regulation-driven requirements:** Plans and issuers must provide cost-sharing information to enrollees via online self-service tools or paper upon request, accompanied by notices describing limitations.

**Key insight for us:** The data exists inside payer systems but the UX is terrible. Our product can be better at the interface layer even without payer data, if we are honest about what we know vs. do not know. Strategic fork: either integrate member-authorized payer APIs over time, or stay in the "shopping + explained range" lane with explicit uncertainty labeling.

### B. Cash-Pay Healthcare Marketplaces

**Key players:** GoodRx, Sesame Care, MDsave, Sidecar Health

**What they surface:**
- GoodRx: pharmacy prices, some provider visit costs
- Sesame: direct-pay visit prices, no insurance involvement, marketplace of providers
- MDsave: bundled procedure prices (single upfront payment), marketplace model
- Sidecar Health: insurance product with transparent per-procedure benefit amounts, no network

**Useful for insured users?** Limited. These platforms optimize for cash-pay / self-pay scenarios. For insured patients, the cash price is often irrelevant because the relevant number is the negotiated rate minus what insurance covers. However, cash prices can serve as a useful benchmark.

**Where they help:** Simple, shoppable services (urgent care visit, basic imaging, dental cleaning). Transparent pricing. Good UX.

**Where they break:** Complex multi-step procedures. Anything requiring prior auth. Anything where the cost depends heavily on findings during the visit.

**Key insight for us:** The UX pattern to emulate is "price is concrete, inclusive, and understandable," but the business logic is not directly transferable to insured out-of-pocket estimation because insurance adjudication introduces deductibles, coinsurance, network tiers, and multi-bill fragmentation.

### C. Transparency Data Infrastructure Platforms

**Key players:** Turquoise Health ($40M Series C, March 2026), Serif Health (YC, 300+ customers), Trilliant Health, PayerPrice, Payerset, OmniRate

**What raw data they use:**
- Hospital Price Transparency (HPT) machine-readable files (negotiated rates by payer by service)
- Transparency in Coverage (TiC) payer MRF files (in-network rates, out-of-network allowed amounts)
- NPPES/NPI provider data
- Claims data (where available)

**How they normalize messy files:**
- Custom parsers for heterogeneous hospital file formats (CSV, JSON, XML, PDF -- yes, some hospitals still post PDFs)
- Streaming JSON parsers for TiC files (some individual files exceed 150 GB uncompressed)
- Entity resolution across different provider identifiers
- Ghost rate filtering (99% of TiC provider-procedure pairs are noise -- only ~1% represent providers who actually perform that service)

**Consumer-grade output?** Mostly no. These are B2B platforms. Turquoise Health has a consumer-facing search tool that is the closest to consumer-grade. Serif Health is API-first. Trilliant recently launched a free AI chatbot for hospital price data.

**Key insight for us:** Do not try to parse raw MRF/HPT files at a hackathon. Use the pre-processed outputs from these companies (Turquoise free consumer search, Turquoise SSP API, DoltHub open database) as data sources. These companies are effectively building the "data plane" we need.

### D. Benchmark / Fair-Price / Reimbursement Reference Tools

**Key players:** FAIR Health, CMS Procedure Price Lookup, Health Care Cost Institute (HCCI / HealthPrices.org), Peterson-KFF Health System Tracker, Valenz Bluebook (formerly Healthcare Bluebook)

**FAIR Health:**
- Nonprofit, independent
- Benchmark allowed amounts by geo-zip (493 geographic areas)
- Consumer site (fairhealthconsumer.org) shows in-network and out-of-network estimates
- Data from 50B+ claim records
- Percentile-based (50th to 95th) -- shows range, not single number
- Free consumer access, premium professional products

**CMS Procedure Price Lookup (PPL) API:**
- ~3,900 procedures covered
- Medicare allowed amounts for hospital outpatient departments and ambulatory surgical centers
- Geographic adjustment via GPCI
- Requires API key (through CMS developer portal)
- Good for benchmarking but Medicare rates are not the same as commercial insurance rates

**CMS Medicare Physician Fee Schedule:**
- Payment rates and associated policy indicators by CPT/HCPCS code, locality, and year
- Useful as a "floor/anchor" for professional services pricing logic

**HCCI HealthPrices.org:**
- Free, shows average prices for healthcare services by metro area
- Based on commercial claims data

**Usefulness for consumer OOP:** These are benchmarks, not personalized estimates. They tell you "a colonoscopy typically costs $X in your area" but not "your specific out-of-pocket will be $Y." Still extremely useful as reference points and as fallback data when plan-specific data is unavailable.

**Key insight for us:** Use FAIR Health or CMS PPL as the "expected price" reference layer. Layer plan-specific estimation on top. Always show the benchmark alongside the estimate so users can calibrate. Benchmarks solve "what's reasonable" better than "what will I pay."

### E. Provider Directory / Network Discovery Tools

**Key players:** Insurer directories, Ribbon Health ($43.5M Series B), NPPES NPI Registry, Zocdoc, Kyruus Health, Quest Analytics

**How they determine in-network status:**
- Insurer directories: based on credentialing/contracting data, updated on varying schedules
- Ribbon Health: aggregates multiple data sources, provides provider + insurance + cost data via API
- NPPES: administrative registry, does NOT indicate network status

**Common failure modes (ghost networks):**
- CMS estimates 55%+ of provider directories contain at least one critical error
- 72% of inactive behavioral health providers should not have been listed
- 33% of users encounter outdated/incorrect information
- Patients using inaccurate directories are 4x more likely to get surprise bills

**Regulatory response (2025-2026):**
- New rolling 90-day provider verification requirement (effective July 2025)
- States beginning to crack down on ghost networks
- Consumer protections when inaccurate directories lead to out-of-network care surprises

**Standards-based paths to network verification (from deep research):**
- **Da Vinci PDex Plan-Net IG:** FHIR interface for insurer plans/networks and participating providers, enabling third-party apps to query payer network participants
- **CMS Provider Directory API:** Impacted payers required to make provider directory information available via a public-facing FHIR endpoint
- **In practice:** Some payers publish developer-facing provider directory API documentation referencing Plan-Net concepts

**Browser automation opportunity:** Instead of relying solely on published directory data, use Playwright to query insurer directory websites directly and cross-reference results. This could:
- Verify network status against the insurer's own search tool
- Capture recency information (when was this listing last verified?)
- Build a curated verification layer on top of unreliable published data

**Key insight for us:** Network status verification is a critical trust problem. Our "AI-last-resort" strategy for network status: (1) try authoritative directory API data when available, (2) fall back to published directory pages or browser-verified results, (3) only then use inference, and keep the answer labeled as uncertain. Never claim certainty about network status.

### F. Insurance Understanding / Benefits Interpretation Tools

**Current state:** This is the most underserved bucket.

**SBC (Summary of Benefits and Coverage):**
- Standardized 8-page document required for all plans
- Contains key cost-sharing info: deductible, coinsurance, copays, OOP max
- **No machine-readable standard exists** -- distributed as PDF only
- Could theoretically be parsed with OCR/LLM, but format varies by insurer
- CMS notes SBCs explain cost-sharing rules and that plans must provide a Uniform Glossary

**EOB (Explanation of Benefits):**
- Generated after a claim is processed
- Shows what was billed, allowed, paid, and owed
- Every payer formats differently
- Tools exist (ABBYY, Sensible, WiseEOB) for enterprise EOB processing
- Consumer-facing EOB understanding tools are essentially nonexistent

**Insurance card parsing:**
- Orbit HC offers an insurance card OCR API
- Basic: extracts plan name, member ID, group number, copay info

**ID card requirements under CAA (Consolidated Appropriations Act):**
- Deductibles and out-of-pocket maximum information pushed to consumer-visible ID card artifacts
- Point users to a phone number/website for coverage/network info
- Important for our onboarding UX: guide users to "where the facts live" instead of asking open-ended questions

**Member-specific data paths (deep research):**
- **Patient Access API regime:** CMS Interoperability and Patient Access final rule requires/encourages payer APIs to share data with patients, including adjudicated claims/encounters
- **X12 270/271 eligibility transactions:** Standard for electronic eligibility/benefits inquiries; CORE content rules specify returning remaining deductibles and copay/coinsurance data elements
- **Practical constraint:** These integrations usually aren't MVP-friendly (access, contracting, authentication), but determine whether we can ever move beyond "estimated ranges" into "high-confidence personalized estimates"

**Browser automation opportunity for deductible access:**
- Instead of asking users "what's your deductible remaining?" (they don't know), use Playwright to:
  - Navigate the user to their insurer's member portal login page
  - After user authenticates, extract deductible remaining and OOP max remaining
  - Feed these real numbers into the estimation engine
- This is a genuine differentiator: no other tool does this

**Key insight for us:** For hackathon MVP, two parallel paths: (1) Ask users 4-5 structured questions about their plan as fallback, (2) Demo browser-assisted deductible retrieval as the wow-factor feature.

### G. Procedure / Visit Normalization Tools

**The problem:** Users say "I need a checkup" or "my back hurts." The billing system speaks in CPT codes (99213, 99214, 72148, etc.). Bridging this gap is hard.

**What exists:**
- CMS HCPCS API (clinicaltables.nlm.nih.gov) -- free, searchable HCPCS code database
- Turquoise Health Standard Service Packages (SSPs) -- open source bundles mapping common visits to likely CPT code sets
- AMA CPT code set -- the canonical reference, but **licensed and not freely redistributable**

**Common approaches:**
- Map common visit types to likely CPT/E&M code ranges
- Use bundled service packages rather than individual codes
- Accept ambiguity: "a routine PCP visit is most likely 99213 or 99214, with a price range of $X-$Y"

**CPT Licensing constraint (legal, not technical):**
- The AMA explicitly states entities using CPT content are expected to obtain an appropriate license
- CMS licensing pages reinforce unauthorized use is prohibited
- For hackathon: use HCPCS public subset + pre-mapped bundles, avoid displaying CPT codes directly
- Post-hackathon: obtain AMA license if model is validated

**Key insight for us:** For MVP, pre-define 10-20 common visit types and map each to likely CPT bundles. Use Turquoise SSPs as a starting reference. AI can help classify user intent into these buckets.

### H. Out-of-Pocket Estimation Engines

**The calculation logic:**

```
1. Start with allowed amount (negotiated rate between provider and payer)
2. Check: has patient met deductible?
   - If no: patient pays min(allowed_amount, remaining_deductible)
   - If yes: proceed to step 3
3. Apply coinsurance: patient pays allowed_amount * coinsurance_rate
4. Check: copay applies instead of coinsurance for this service type?
   - If yes: patient pays copay amount
5. Check: has patient hit OOP maximum?
   - If yes: patient pays $0
   - If approaching: patient pays min(calculated_amount, remaining_OOP_max)
```

**Where estimates fail:**
- Unknown deductible progress (patient may not know how much they have already spent)
- Unbundled services: an "MRI" visit may generate 3 separate bills (facility, radiologist, contrast)
- Prior authorization requirements change the available provider set
- In-vs-out-of-network can flip the entire calculation (separate deductibles, separate OOP max)
- Family vs. individual deductible complexity

**Existing tools:** Insurer estimators (described in Bucket A), ProcedureRates.com calculator (simple web calculator), hospital-specific estimators (Mount Sinai, etc.)

**Key insight for us:** Build a deterministic rules engine, not an AI model. The math is straightforward; the hard part is getting accurate inputs. Be explicit about what inputs are known vs. assumed. Show the calculation step by step. Reference CMS Coverage Examples Calculator as the government-sanctioned methodology.

### I. Provenance / Trust / Explainability Patterns

**Best practices from research:**

1. **Tag every data point with its source type:**
   - Fact (from public data): "Medicare allows $245 for CPT 99214 in this ZIP"
   - Inferred (from transparency data): "Cigna's negotiated rate at this facility is approximately $180-$220"
   - Assumed (default/user-provided): "We assume you have not met your deductible yet"
   - User-provided: "You told us your copay is $30"

2. **Show ranges, not point estimates:** "$45-$120 estimated out-of-pocket" is more honest than "$82"

3. **Explain the calculation:** "Your estimated cost = negotiated rate ($200) x coinsurance (20%) = $40, because you told us you have already met your deductible"

4. **Highlight what would change the estimate:** "If you have NOT met your deductible, your cost would be $200 instead of $40"

5. **Visual confidence indicators:** Use color/size/opacity to indicate confidence level without requiring users to read fine print

**No existing healthcare tool does all of this well.** This is the clearest differentiation opportunity.

---

## 3. Public Data Landscape

### Category 1: Doctor / Facility Transparency

| Data Source | Contains | Granularity | Public | Machine-Readable | Supports OOP? | Hackathon-Suitable | Production-Suitable |
|---|---|---|---|---|---|---|---|
| NPPES NPI Registry | Provider name, specialty, address, taxonomy | Individual provider | Yes | Yes (API + bulk download) | No (no pricing) | YES | YES |
| CMS Care Compare | Provider quality ratings, patient experience | Facility-level | Yes | Yes (API) | No | YES | YES |
| CMS Provider Data Catalog | Profile attributes, quality reporting | Provider/facility | Yes | Yes (datasets) | No | YES | YES |
| Hospital HPT Files | Negotiated rates by payer, cash prices | Facility + procedure | Yes | Partially (format varies wildly) | Partially (allowed amounts) | NO (too messy) | With effort |

### Category 2: General Procedure / Service Transparency

| Data Source | Contains | Granularity | Public | Machine-Readable | Hackathon-Suitable | Production-Suitable |
|---|---|---|---|---|---|---|
| CMS PPL API | Medicare allowed amounts for ~3,900 procedures | CPT + geography | Yes | Yes (API) | YES | YES |
| CMS Medicare Physician Fee Schedule | Payment rates by CPT/HCPCS, locality, year | Code + locality | Yes | Yes (lookup + download) | YES | YES |
| FAIR Health Consumer | Benchmark allowed amounts, charge benchmarks | CPT + 493 geo-zips | Yes (consumer site) | No (no API for free tier) | Manually YES | YES (paid API) |
| HCCI HealthPrices.org | Average commercial prices by metro area | Service category + metro | Yes | No (web only) | Manually YES | Limited |
| DoltHub Hospital Price DB | Crowd-sourced hospital prices, 500+ hospitals | Hospital + CPT/HCPCS | Yes | Yes (SQL, Dolt) | YES | YES |
| Turquoise Health SSP API | Standard service packages, bundled pricing | Service bundle | Yes (free API) | Yes | YES | YES |
| CMS HCPCS Lookup | HCPCS code descriptions | Code-level | Yes | Yes (API) | YES | YES |

### Category 3: Actual Insured Out-of-Pocket Estimation Inputs

| Data Source | Contains | Granularity | Public | Hackathon-Suitable | Notes |
|---|---|---|---|---|---|
| TiC Payer MRF Files | In-network negotiated rates by provider | Provider + CPT + plan | Yes | NO | 100+ TB, requires specialized parsing |
| Insurer cost estimator tools | Personalized OOP estimates | Member-specific | Requires login | NO (but browser automation possible) | Cannot programmatically access without auth |
| SBC Documents | Plan cost-sharing parameters | Plan-level | Mostly public PDFs | Manually YES | No machine-readable standard |
| CMS Coverage Examples Calculator | Template for SBC cost calculations | Plan-level | Yes | YES | Excel-based reference |
| Medicare Physician Fee Schedule | Medicare rates by CPT + locality | CPT + locality | Yes | YES | Download or lookup tool |
| X12 270/271 Eligibility | Deductible remaining, benefits details | Member-specific | Requires contracting | NO for MVP | Standard electronic path to accumulators |
| Patient Access APIs (FHIR) | Adjudicated claims, clinical data | Member-specific | Requires payer auth | NO for MVP | CMS interoperability mandate |

### Category 4: Consumer-Facing Benchmarks

| Source | What It Shows | Usefulness |
|---|---|---|
| FAIR Health Consumer | "In your area, this procedure typically costs $X-$Y" | HIGH -- good reality check |
| Turquoise Health Patient Search | "At Hospital X, Payer Y pays $Z for this service" | HIGH -- specific pricing |
| Sesame Care | "Cash price for this visit is $X" | MEDIUM -- cash-only reference |
| GoodRx | "This prescription costs $X at Pharmacy Y" | HIGH for Rx, irrelevant for procedures |
| Valenz Bluebook | "Fair price" for procedures, quality navigation | MEDIUM -- proprietary methodology |

### Category 5: Data That Sounds Useful But Is Not

| Data | Why It Sounds Useful | Why It Is Not |
|---|---|---|
| Raw hospital chargemaster files | "Full list of hospital prices!" | Chargemaster prices are fantasy numbers that nobody pays. Negotiated rates are what matter. |
| TiC MRF files (raw) | "Every negotiated rate for every provider!" | 100+ TB, 99% ghost rates, requires cloud infrastructure to process |
| Claims data (general) | "Actual paid amounts!" | Not public. Available only to payers, self-insured employers, or data intermediaries |
| Hospital star ratings | "Quality indicators!" | Quality != price. Useful for a quality layer but not for cost estimation |

---

## 4. GitHub / Open-Source Landscape

### Directly Usable for Hackathon

| Repo | What It Does | Maturity | Relevance | Learn From |
|---|---|---|---|---|
| **CMSgov/hospital-price-transparency** | Official CMS schemas, data dictionaries, CSV/JSON templates for HPT files | Production | HIGH | Schema design for normalized price data |
| **CMSgov/hpt-tool** + **hpt-validator** | Validation tools for hospital MRF files (online + CLI + library) | Production | MEDIUM | How CMS structures price data requirements; quality scoring for provenance |
| **turquoisehealth/servicepackages.health** | Open standard service packages mapping visit types to CPT bundles | Early but usable | HIGH | Pre-built visit-type-to-CPT mappings for common services |
| **ropensci/npi** | R package for NPPES NPI Registry API | Mature | MEDIUM | NPI API patterns (port to Python/JS) |
| **TPAFS/transparency-data** | Supplemental data filling gaps in CMS transparency rules | Active | MEDIUM | What data is missing from official sources |
| **dolthub/hospital-price-transparency-v3** | Crowd-sourced hospital price database, 500+ hospitals, SQL queryable | Active | HIGH | Pre-processed price data, queryable without parsing raw files |

### Inspirational / Learn From

| Repo | What It Does | Maturity | Learn From |
|---|---|---|---|
| **danielchalef/mrfparse** | Go parser for TiC MRF files with streaming, outputs Parquet | Functional | How to parse massive MRF JSON files (streaming + filtering by CPT subset) |
| **nathansutton/hospital-price-transparency** | Maps hospital prices to NPI + CPT common data model | Research-grade | Data model for normalized hospital pricing |
| **CMSgov/price-transparency-guide** | Technical implementation guide for TiC rule (schemas) | Reference | Full JSON/XML schemas for payer MRF files; validation approach |
| **postman-open-technologies/us-cms-price-transparency** | Postman workspace with CMS transparency API specs | Reference | API design patterns for healthcare price data |
| **Databricks MRF accelerator** | Notebook-based streaming ingest for payer MRF JSON | Reference | Approach for extreme file sizes and JSON structural challenges |
| **Self-healing hospital transparency scraper** | Collects/archives hospital transparency data at scale | Design inspiration | Crawling + link maintenance patterns |

### FHIR-Based Network and Claims Projects

| Repo/Standard | What It Does | Learn From |
|---|---|---|
| **HL7 Plan-Net IG** | Network API model (plans, networks, providers, organizations) | Standardized payer directory API model |
| **CARIN Blue Button IG** | Claims-oriented patient access FHIR spec | Reference implementations for patient access |
| **CARIN Alliance reference implementations** | Server/client for CPCDS/FHIR | Conformance testing, credibility layer |
| **Inferno test kit** | Validates required data elements from CARIN IG | Testing infrastructure for payer API conformance |

### Not Found But Would Be Valuable

- No open-source consumer-facing OOP estimation engine exists
- No open-source SBC parser exists
- No open-source "symptom to CPT" or "visit intent to billing code" mapper exists
- No open-source insurance benefits rules engine exists
- No open-source browser automation for insurer portal data extraction exists

---

## 5. Company / Product Landscape

| Company | Category | Target Customer | Stack Coverage | Strengths | Weaknesses | Learn From |
|---|---|---|---|---|---|---|
| **Turquoise Health** | Data infrastructure + consumer | Enterprise + consumer | Price data, provider search, contracting | Best-in-class price data normalization, free consumer search, free SSP API | Consumer UX is basic search, not guided shopping | Their SSP standard, API design, data model |
| **Serif Health** | Data infrastructure | Enterprise (300+ cos) | Transparency data APIs | Clean API products, YC-backed, focused on data quality | No consumer product, enterprise pricing | API design, how they normalize messy data |
| **Ribbon Health** | Provider data API | Enterprise | Provider directory + insurance + cost + quality | Most comprehensive provider data API, clean developer experience | Not consumer-facing, paid | Provider data model, multi-source verification |
| **Trilliant Health** | Market intelligence | Providers/payers | Price analytics, provider directory, demand forecasting | Recently launched free AI chatbot for hospital price data | Enterprise-focused, heavy analytics | AI chatbot approach to price data |
| **FAIR Health** | Benchmark pricing | Consumer + professional | Allowed amount benchmarks, consumer estimator | Independent, nonprofit, massive dataset (50B+ claims), consumer app | No plan-specific personalization, no API for free tier | Benchmark display UX, geo-zip methodology |
| **Sidecar Health** | Insurance product | Employer/consumer | Full insurance with transparent benefit amounts | Radical transparency: members see exact benefit amount per procedure | Only for Sidecar members, not applicable to traditional insurance | UX for showing "what your plan pays" alongside "what you pay" |
| **GoodRx** | Rx + care marketplace | Consumer | Pharmacy prices, some provider costs | Dominant in Rx, massive brand recognition | Provider pricing is thin, not insurance-aware | Consumer UX for price comparison |
| **Sesame Care** | Cash-pay marketplace | Consumer | Direct-to-consumer visits, cash pricing | Clean UX, clear prices, no insurance complexity | Cash-only, useless for insured cost estimation | Consumer shopping UX, service category design |
| **MDsave** | Bundled procedures | Consumer | Bundled cash prices, marketplace | Single upfront price for procedures, proprietary "fair price" algorithm | Cash-only, limited service coverage | Bundling concept, price benchmarking approach |
| **Zocdoc** | Provider booking | Consumer | Find doctors, book appointments, insurance check | Consumer-facing network-discovery UX pattern | Network accuracy still depends on underlying data correctness | "Find doctor who takes your insurance" UX pattern |
| **Transcarent** | Healthcare navigation | Employer/consumer | Benefits navigation + care guidance + scheduling | Consumer-facing navigation layer, WayFinding experience | Employer-focused, not open | Navigation + benefits + scheduling integration |
| **Castlight Health** | Healthcare navigation | Employer | Navigation and transparency, cost/quality info | Long track record in employer transparency tools | Employer-only, not consumer-accessible | Cost/quality information display patterns |
| **Goodbill** | Bill negotiation | Consumer | Post-bill review and negotiation | Alternative wedge: reduce costs by detecting errors post-bill | Post-service, not pre-service | Error detection patterns, negotiation value prop |
| **Kyruus Health** | Care access platform | Providers/payers | Provider data management, "find care" experiences | Enterprise provider directory management | Not consumer-facing | Provider data management, member search UX |
| **Quest Analytics** | Provider data | Providers/payers | Provider data accuracy and verification | Shows directory accuracy is a persistent monetizable pain | Enterprise tooling only | Verification approach patterns |

---

## 6. Prior Art / Key Ideas

### Must-Read Resources

| Resource | Source | Why It Matters | Key Insight |
|---|---|---|---|
| "The New Price Transparency Laws and Turquoise Health" | Out-of-Pocket Health (Nikhil Krishnan) | Best accessible explanation of how transparency data actually works and where it breaks | The data exists but is nearly unusable without massive processing; even processed data has quality gaps |
| "Enhancing Healthcare Cost Transparency: Implementation Challenges" | PMC (2025) | Academic review of what works and fails in price transparency | Consumer tools show no measurable decrease in spending -- the problem is UX and comprehensibility, not data availability |
| "Price Transparency With Gaps" | AJMC | Assesses completeness of payer TiC data | Major payers have significant gaps; data is not as comprehensive as the mandate suggests |
| "Technical Challenges with Private Health Insurance Price Transparency Data" | Congressional Research Service (2025) | Congressional analysis of why TiC data is hard to use | File sizes, format inconsistency, ghost rates, and lack of consumer-grade tools are systemic problems |
| "Health Care Consumer Shopping Behaviors and Sentiment" | PMC / JMIR (2020) | Qualitative study of 54 adults trying to shop for healthcare | 83% tried to negotiate; negative sentiment correlated with seeking value -- users want to shop but the experience defeats them |
| "The Hospital Price Transparency Rule Is Working, But Patients Still Need Help" | Brookings Institution | Balanced policy analysis | Self-pay patients do respond to price data when it is available, relevant, and actionable |
| "Necessity for and Limitations of Price Transparency" | AMA Journal of Ethics (2022) | Ethical and practical analysis | Price transparency is necessary but not sufficient -- need benefits understanding, network verification, and uncertainty communication |
| CMS Coverage Examples Calculator instructions | CMS.gov | Official template for how SBC cost examples should be calculated | This IS the government-sanctioned OOP calculation methodology -- use it as our rules engine reference |

### Key Design Insight

**No existing tool implements a "provenance chain" for healthcare cost estimates.** The closest analogy is how financial sites show "delayed 15 min" on stock prices, or how weather apps show confidence bands. Healthcare needs this pattern desperately. Every number should carry metadata: source, freshness, confidence, what would change it.

---

## 7. Browser Automation Opportunities

### Deductible / Accumulator Retrieval

**The problem:** The single biggest gap in consumer OOP estimation is not knowing how much of the deductible has been used. Users rarely know this number. Insurer portals have it behind a login.

**Browser automation approach:**
1. User tells us their insurer (or we detect from insurance card)
2. We open their insurer's member portal login page via Playwright
3. User authenticates (we never touch credentials)
4. After auth, we navigate to the "benefits summary" or "deductible tracker" page
5. Extract: deductible remaining, OOP max remaining, plan year dates
6. Feed real numbers into the estimation engine

**Why this is differentiated:** Every other tool either (a) asks the user to self-report (inaccurate) or (b) requires enterprise API integration (slow, expensive, requires contracting). Browser automation is a middle path that works now.

**Hackathon feasibility:** High for a demo with 1-2 insurers. Playwright MCP is already available. Main risk is insurer portal anti-automation defenses.

### Network Verification via Browser

**The problem:** Published directory data is 55%+ inaccurate. But insurer directory search tools are the closest thing to a "source of truth" for network status.

**Browser automation approach:**
1. Given a provider NPI and insurer, navigate to the insurer's "find a doctor" page
2. Search for the specific provider
3. Capture: whether they appear, what network/tier they're listed under, last verification date
4. Cross-reference with published data to assign confidence scores

**Value:** Creates a real-time verification layer on top of stale published data. Every verification result gets timestamped and becomes part of our provenance chain.

### Curated Data Book (Alternative)

If browser automation proves too fragile for production:
- Pre-verify top 50-100 providers in target geography via browser + manual spot checks
- Create a curated "verified provider book" with verification dates
- Update on a rolling basis
- More reliable than published data, more feasible than real-time scraping

---

## 8. Hackathon Data Strategy

### The ONE category question

For the hackathon demo, we need to pick the service category with the BEST coverage across all three data dimensions:

| Dimension | What we need | Best coverage |
|---|---|---|
| **Price data** | Negotiated rates or benchmark prices per provider | Primary care visits (most hospital MRFs, most benchmark data) |
| **Network accuracy** | Reliable in-network status | Primary care / general practice (largest provider pool, most directory entries) |
| **Deductible relevance** | Service type where deductible matters for OOP | Imaging (MRI, X-ray) -- often subject to deductible, meaningful price variation |

**Recommendation: Primary care new patient visit (CPT 99203-99205)**

Why:
- Most data available in transparency files (highest coverage in both hospital MRFs and TiC data)
- Largest provider pool for network verification demos
- Simple enough to estimate with reasonable confidence (single visit, no unbundling)
- Relatable to every consumer ("I need to see a doctor")
- Turquoise SSP has pre-built bundles for this

**Secondary demo (stretch goal): Basic imaging (X-ray)**
- Shows deductible impact on pricing (deductible usually applies)
- Good price variation between facilities (hospital vs. freestanding)
- More dramatic provenance display (more assumptions to show)

### Data sources for hackathon (priority order)

1. **Turquoise Health SSP API** -- service package pricing (FREE, API-ready)
2. **NPPES NPI API** -- provider identity + location (FREE, API-ready)
3. **CMS PPL API** -- Medicare benchmark prices (FREE, needs API key)
4. **DoltHub hospital-price-transparency-v3** -- facility-specific prices (FREE, SQL-ready)
5. **FAIR Health consumer site** -- benchmark ranges (FREE, manual extraction)
6. **Browser-automated insurer directory** -- network verification (Playwright, demo-ready)
7. **Browser-automated member portal** -- deductible remaining (Playwright, demo-ready)

### What to mock vs. what to use real data for

| Component | Real data | Mock data |
|---|---|---|
| Provider identity + location | NPPES API | - |
| Price benchmarks | CMS PPL + Turquoise SSP | - |
| Facility-specific prices | DoltHub | Fill gaps with FAIR Health ranges |
| Network status | Browser-verified (demo) | Default "unverified" with explanation |
| Insurance plan details | - | 2-3 mock plan configurations (high-deductible, copay-based, HMO) |
| Deductible remaining | Browser demo (1 insurer) | User-input fallback with assumptions labeled |

---

## 9. Standards-Based Integration Paths (Production Roadmap)

### Path 1: Payer Directory APIs (FHIR Plan-Net)
- **What:** Standardized API for querying network participation
- **Standard:** Da Vinci PDex Plan-Net Implementation Guide
- **Status:** Some payers have developer portals; adoption uneven
- **Timeline:** Useful for production, not hackathon
- **Value:** Replaces browser scraping with structured API calls

### Path 2: Eligibility / Benefits Inquiry (X12 270/271)
- **What:** Electronic query for deductible remaining, benefits details
- **Standard:** HIPAA X12 270/271 + CORE content rules
- **Status:** Mature standard, but requires clearinghouse contracting
- **Timeline:** Production feature, requires business relationships
- **Value:** Real-time personalized accumulator data

### Path 3: Patient Access API (CMS Interoperability)
- **What:** Patient-authorized access to adjudicated claims + clinical data
- **Standard:** CMS Interoperability and Patient Access final rule
- **Status:** Required for impacted payers, adoption growing
- **Timeline:** Production feature
- **Value:** Full claims history enables accurate accumulator calculation

### Path 4: SBC Document Parsing
- **What:** Extract plan parameters from Summary of Benefits and Coverage PDFs
- **Standard:** No machine-readable standard; PDF only
- **Status:** Feasible with LLM-assisted OCR
- **Timeline:** Post-hackathon enhancement
- **Value:** Automated plan onboarding without manual user input

---

## 10. Legal / Licensing Constraints

### CPT Code Licensing
- AMA owns the CPT code set
- Displaying CPT codes or CPT-derived content requires license
- **Hackathon mitigation:** Use HCPCS public subset; describe services in plain language; use Turquoise SSP service package names instead of raw CPT codes
- **Production path:** Obtain AMA license if model is validated

### Regulatory Positioning
- Frame as "decision support tool showing publicly available data"
- Do NOT position as medical advice or insurance guidance
- Include disclaimers: "estimates are not guarantees," "verify with your insurer before booking"
- Consider state-specific consumer protection implications

### Data Usage Rights
- Hospital MRFs and TiC files are public data -- free to use
- NPPES data is public -- free to use
- CMS PPL API has terms of use -- review before production
- FAIR Health free tier is consumer use only -- paid API for commercial products
- DoltHub hospital price data has its own license terms

---

## 11. Conflicts / Disagreements in Sources

- **Does price transparency reduce spending?** Studies disagree. Some show self-pay patients respond to pricing (Brookings). Others show no measurable decrease in insured patient spending (RAND, AJMC). The disagreement likely reflects that insured patients have less price sensitivity than self-pay patients. Our thesis: price matters, but non-transparency created learned helplessness. Show comparable rates + recommendations to break the pattern.
- **How accurate is TiC data?** Turquoise/Serif say it is comprehensive enough to build products on. Academic studies (AJMC) say it has significant gaps. Both are probably true: enough data for benchmarking, not enough for precise personalized estimates.
- **AI role in healthcare cost estimation:** Some startups (Trilliant) are using AI chatbots. Research evidence suggests deterministic rules are more trustworthy for cost calculation. AI is better suited for intent classification and explanation generation.
- **Why haven't data companies built consumer tools?** Possible explanations: (a) B2B monetization is easier and more immediate, (b) consumer trust bootstrapping is hard, (c) the consumer UX problem requires product thinking, not just data engineering, (d) the regulatory/compliance burden for consumer-facing tools is higher. Our bet: the opportunity is real but requires a different team DNA than data infrastructure companies have.

---

## Appendix A: Master Research Prompt

Use this two-step prompt to force comprehensive landscape research:

### Step 1: Landscape Research

```text
You are a research analyst helping build a provenance-first consumer healthcare shopping tool.

Core goal:
Help insured users find likely in-network providers/facilities and estimate out-of-pocket cost ranges BEFORE booking, with transparent explanations and a provenance layer that labels:
- source-backed facts,
- user-provided facts,
- deterministic assumptions,
- and inferred mappings.

Constraints:
- AI is a last resort.
- Prefer real datasets, regulated disclosures, and published APIs over "asking the user" or "model guessing."
- We must never imply estimates are guaranteed; uncertainty must be explicit.

Deliver a structured report covering ALL modules below. For each module:
1) prior art (companies/products)
2) open source / GitHub projects and what they enable
3) data sources (public, semi-public, member-auth, provider-facing)
4) practical limitations / failure modes
5) what we should learn and reuse
6) what is feasible for MVP vs production

Modules to cover:
A) Hospital price transparency data (MRFs, shoppable services)
B) Health plan price transparency data (in-network negotiated rates, allowed amounts)
C) Provider identity + "doctor transparency"
D) Network verification
E) Benefits understanding
F) Member-specific personalization
G) Service/procedure normalization
H) Out-of-pocket estimation engines
I) Provenance + trust UX
```

### Step 2: Modular System Plan

```text
Now convert your research into a modular system plan.

For each module (A-I), output:
- Inputs/outputs as JSON schema (minimal but explicit)
- Deterministic steps vs AI-permitted steps (AI only for intake/explanation/clarification)
- Provenance fields required for every output (source, timestamp, confidence, known/assumed/inferred)
- Top 3 failure modes and how the UI should communicate them
- MVP implementation approach using only the most feasible datasets and open-source components
```

---

## Appendix B: Top 10 Product / Trust / Data Insights

1. **The data exists but is buried.** 100+ TB of transparency data is published but nearly unusable without processing.
2. **Ghost rates are the #1 data quality problem.** 99% of provider-procedure pairs in TiC data are noise.
3. **Provider directories are 55%+ inaccurate.** Never claim network status certainty.
4. **No existing tool shows provenance.** This is the biggest UX gap and our differentiation.
5. **70% of consumers do not try to shop.** The problem is not data availability -- it is comprehensibility and trust.
6. **Cash-pay marketplaces are a solved problem.** Do not compete with GoodRx/Sesame on cash prices.
7. **SBC documents have no machine-readable standard.** Plan understanding must be user-input driven for now.
8. **Deterministic rules beat AI for cost calculation.** The math is simple; the inputs are hard.
9. **FAIR Health benchmarks are the best free reference.** 50B+ claims, 493 geo areas, percentile-based.
10. **Browser automation for deductible access is a unique, underexplored wedge.** No one else does this.

---

## Sources Cited

- [CMS Hospital Price Transparency](https://github.com/CMSgov/hospital-price-transparency)
- [CMS HPT Tool](https://cmsgov.github.io/hpt-tool/)
- [CMS Procedure Price Lookup API](https://developer.cms.gov/ppl-api/)
- [NPPES NPI Registry API](https://npiregistry.cms.hhs.gov/api-page)
- [FAIR Health Consumer](https://www.fairhealthconsumer.org/)
- [Turquoise Health](https://turquoise.health/)
- [Serif Health](https://www.serifhealth.com/)
- [Ribbon Health](https://www.ycombinator.com/companies/ribbon-health)
- [DoltHub Hospital Price Transparency](https://www.dolthub.com/repositories/dolthub/hospital-price-transparency-v3)
- [DoltHub Blog: State of Hospital Price Transparency Data (2025)](https://www.dolthub.com/blog/2025-01-28-state-of-hospital-price-transparency-data/)
- [DoltHub Blog: Parsing MRFs with ijson](https://www.dolthub.com/blog/2022-11-02-parsing-mrfs-with-ijson/)
- [mrfparse (Go MRF parser)](https://github.com/danielchalef/mrfparse)
- [TPAFS transparency-data](https://github.com/TPAFS/transparency-data)
- [CMS Price Transparency Guide](https://github.com/CMSgov/price-transparency-guide)
- [Turquoise Health Service Packages](https://github.com/turquoisehealth/servicepackages.health)
- [HCPCS API (NLM)](https://clinicaltables.nlm.nih.gov/apidoc/hcpcs/v3/doc.html)
- [HCCI HealthPrices.org](https://healthcostinstitute.org/all-hcci-reports/welcome-to-healthprices-org-hccis-free-price-transparency-tool/)
- [CMS Coverage Examples Calculator](https://www.cms.gov/files/document/coverage-examples-calculator-instructions-060723.pdf)
- [Trilliant Health AI Chatbot](https://www.fiercehealthcare.com/health-tech/trilliant-rolls-out-free-ai-chatbot-dig-hospital-price-transparency-data)
- [Congressional Research Service: Technical Challenges with TiC Data](https://www.congress.gov/crs-product/R48570)
- [Brookings: Hospital Price Transparency Rule Working](https://www.brookings.edu/articles/the-hospital-price-transparency-rule-is-working-but-patients-still-need-help-using-it/)
- [AJMC: Price Transparency With Gaps](https://www.ajmc.com/view/price-transparency-with-gaps-assessing-the-completeness-of-payer-transparency-in-coverage-data)
- [AMA Journal of Ethics: Necessity and Limitations](https://journalofethics.ama-assn.org/article/necessity-and-limitations-price-transparency-american-health-care/2022-11)
- [Health Affairs: Ghost Networks](https://www.healthaffairs.org/doi/10.1377/hlthaff.2019.01501)
- [PMC: Consumer Shopping Behaviors](https://pmc.ncbi.nlm.nih.gov/articles/PMC7434061/)
- [Becker's: 70% Don't Price Shop](https://www.beckershospitalreview.com/finance/70-of-consumers-don-t-price-shop-for-healthcare-services-5-things-to-know.html)
- [Serif Health Blog: CMS TiC Rule Update 2025](https://www.serifhealth.com/blog/cms-tic-rule-update-2025)
- [CMS Transparency in Coverage Proposed Rule (2025)](https://www.cms.gov/newsroom/fact-sheets/transparency-coverage-proposed-rule-cms-9882-p)
- [Da Vinci PDex Plan-Net IG](https://build.fhir.org/ig/HL7/davinci-pdex-plan-net/)
- [CARIN Blue Button IG](https://build.fhir.org/ig/HL7/carin-bb/)
- [CMS Interoperability and Patient Access Final Rule](https://www.cms.gov/regulations-and-guidance/guidance/interoperability/index)
