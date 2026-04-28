# Product Document: Provenance-First Healthcare Shopping Assistant

**Version:** 1.1 (YHack 2026)
**Date:** 2026-03-27
**Status:** Pre-hackathon

---

## The Problem

Consumer healthcare is still a broken shopping experience.

People can compare flights, hotels, and consumer goods in minutes. But when they need care, they still cannot easily answer basic pre-purchase questions:

- Where should I go for the care I need?
- Which doctors or facilities near me are likely relevant?
- Do they likely take my insurance?
- What will I probably pay out of pocket?
- Which parts of that answer are facts, and which are assumptions?

This is not because data does not exist. The U.S. healthcare system now has massive transparency data: insurer machine-readable files, hospital price files, provider registries, and benchmark datasets. Over 100 TB of machine-readable pricing data has been published since 2022.

The problem is that this data is fragmented, messy, hard to interpret, and not packaged into a usable consumer experience:
- 70% of consumers do not price-shop for healthcare at all
- Among those who try, 42% find estimates confusing or hard to understand
- 55%+ of provider directories contain at least one critical error
- No existing tool separates facts from inferences from assumptions

**The opportunity is not "more AI." It is to turn raw transparency data into a decision-ready, provenance-first shopping experience for insured consumers.**

---

## What We Are Building

A provenance-first healthcare shopping assistant that helps consumers:

1. **Describe** the care they need in plain language
2. **Find** relevant nearby providers and facilities
3. **Check** likely in-network status (with visible confidence)
4. **Retrieve** their actual deductible/OOP status via browser-assisted portal access
5. **Estimate** likely out-of-pocket cost ranges
6. **Understand** why the estimate looks the way it does -- what is known versus assumed
7. **Act** by navigating to the provider via Google Maps with phone number for booking

This is NOT a booking tool. It is a **pre-call preparation tool** that compresses a fragmented multi-hour research workflow into a single decision flow:

```
need care --> describe it --> compare local options --> understand likely cost --> call with confidence
```

---

## Why This Matters

Today, consumers have to stitch together:
- insurer directory
- Google / Maps
- provider websites
- phone calls
- portal signups
- vague billing answers

And even after all that, they still often book care without knowing the likely price.

We compress that into a single decision flow where every number carries its source, freshness, and confidence level.

---

## Sharper Thesis

The market has solved pieces of the stack, but not the consumer experience:
- Transparency data exists (100+ TB of published MRFs)
- Provider and pricing infrastructure exists (Turquoise $40M, Serif 300+ customers, Ribbon $43.5M)
- Benchmarks exist (FAIR Health 50B+ claims)
- Consumers still cannot shop effectively

**The bottleneck is now packaging, trust, and workflow design.** Not raw data access.

The missing product is not another dataset or another generic chatbot -- it is a **consumer-facing decision layer** built on top of existing transparency infrastructure.

**Why these infrastructure companies haven't built this themselves:** They optimized for B2B monetization (faster revenue, simpler sales cycle). The consumer UX problem requires product thinking, not just data engineering. This is a different team DNA.

---

## Stronger Differentiation

The real wedge is not "AI for healthcare." That framing is weak and crowded.

The real wedge is: **a provenance-first, trust-aware healthcare shopping layer.**

### 1. Provenance on Every Answer

Not just "Dr. X is in-network" or "estimated cost is $240."

Instead:
- source(s) checked (CMS PPL, Turquoise SSP, insurer directory)
- last updated (directory listing verified 2026-03-15)
- confidence level (high / medium / low with explanation)
- known ambiguity (deductible status unknown -- using assumption)
- assumptions used in estimate (assuming deductible not yet met)

This is a real differentiator because most products collapse raw data and assumptions into one opaque answer.

### 2. Browser-Assisted Real Data Retrieval

**This is our unique technical wedge.**

Instead of asking users "what's your deductible remaining?" (they don't know), we use browser automation (Playwright) to:
- Navigate users to their insurer's member portal
- After user authenticates, extract deductible remaining and OOP max
- Verify network status against the insurer's own directory search
- Feed real data into the estimation engine

No other tool does this. Every competitor either asks the user (inaccurate), requires enterprise API integration (slow, expensive), or ignores accumulators entirely (wide useless ranges).

### 3. Consumer Workflow, Not Backend Infrastructure

Many players solve provider data, network data, benchmark pricing, or claims infrastructure. But very few solve the actual user flow:

> "I have this need, with this insurance, near this location -- where should I go and what will it likely cost?"

### 4. Deterministic Estimation, AI Only Where Appropriate

Use deterministic rules for:
- plan logic (deductible / coinsurance / copay / OOP max)
- price range estimation
- known-vs-assumed output structure
- provenance tagging

Use AI only for:
- intent classification ("my knee hurts" --> "orthopedic consultation")
- plain-language explanation of estimates
- consumer-language-to-care-category translation

This makes the product more credible, more auditable, and easier to defend.

---

## Cleaner Problem Statement

U.S. healthcare transparency has created a huge amount of public pricing and provider data, but not a usable consumer shopping experience. Patients still struggle to answer simple questions before booking care: where to go, whether it is likely in-network, what they will likely pay, and why. Existing solutions solve pieces of the stack but not the full decision journey with visible provenance. The remaining gap is not data availability -- it is trust-preserving product packaging.

---

## Why Now

This product is newly possible because:
- **Transparency data is now available at scale** -- hospital MRFs mandated since 2021, payer TiC files since 2022, standardized templates since July 2024
- **Provider registries and public APIs are accessible** -- NPPES, CMS PPL, Turquoise SSP all free and API-ready
- **Browser automation is production-grade** -- Playwright enables the "portal assistant" wedge that wasn't feasible 2 years ago
- **Consumers are more price-sensitive than ever** -- high-deductible health plans now cover 55%+ of employer-insured workers
- **Deterministic pipelines can now be paired with lightweight AI UX layers** -- the AI handles natural language, not the math
- **The infrastructure companies chose B2B** -- leaving the consumer-facing product layer wide open
- **Regulatory direction is toward more data, more APIs** -- FHIR Plan-Net, Patient Access APIs, 90-day directory verification

---

## Business Model

**B2B2C via insurance company partnerships.**

Hasper AI (YHack sponsor) operates in the insurance/healthcare AI space. The monetization path:

1. **Insurance companies as distribution partners:** Insurers are mandated to provide cost estimators but their tools are terrible. We build the consumer UX layer, they provide the data access and distribution.
2. **Value to insurers:** Better member satisfaction scores, reduced call center volume, improved HEDIS/quality metrics, compliance with transparency mandates.
3. **Why insurers would pay:** They already spend millions on clunky estimator tools built for compliance. A better consumer experience is a competitive advantage in plan selection.
4. **Long-term:** Self-insured employer distribution (these employers have direct incentive to reduce healthcare spend through smarter shopping).

This is NOT a pure B2C play. The consumer is the user; the insurer (or employer) is the customer.

---

## Hackathon Scope

### What We Build at YHack

A prototype that lets a user:

1. **Enter a care need in plain language** (e.g., "I need to see a new doctor for a checkup")
2. **Enter insurance carrier / plan basics** (dropdown of top local insurers)
3. **See nearby providers** with location, specialty, and distance
4. **View likely network status** with visible confidence and source
5. **Compare likely out-of-pocket ranges** across providers
6. **Inspect provenance and assumptions** behind each estimate
7. **Demo: Browser-assisted deductible retrieval** from one insurer portal
8. **Act: Tap to navigate** via Google Maps link with phone number

### Scope constraints

**ONE service category:** Primary care new patient visit (CPT 99203-99205 equivalent)
- Most data available in transparency files
- Largest provider pool for demos
- Relatable to every consumer

**ONE geography:** New Haven, CT (we are at Yale)

**Mock plan configurations:** 2-3 simplified plans (high-deductible, copay-based, HMO)

### What the hackathon version does NOT solve
- Real adjudicated claim prediction
- Full authorization workflows
- Appointment booking integrations
- All specialties / all plans / all service bundles
- Full CPT code display (licensing constraint)

### What it proves
**Transparency data can be turned into a much better consumer shopping experience -- and browser automation can bridge the personalization gap that makes every other estimator useless.**

---

## User Flow (Revised)

```
1. User enters: "I need to see a doctor for [reason]" (free text)
2. AI classifies intent into service category (or asks clarifying question)
3. System asks: "What insurance do you have?" (dropdown: Anthem BCBS CT, UHC, Aetna, Yale Health)
4. System asks: "Do you know your copay/deductible?" (optional)
   - OR: "Want us to help you check? We can take you to your insurer's portal." [browser assist]
5. System shows: Map of nearby providers with estimated OOP cost range per provider
6. Each estimate shows: [source] [confidence] [assumptions] [what would change it]
7. User taps provider: Google Maps opens with clinic address + phone number
```

---

## Trust / Provenance UX (Non-Negotiable)

- Every number has a visible source tag (hover or inline)
- Cost shown as range, not point estimate
- Clear "we assume / you told us / we verified" section
- "What could change this estimate" callout
- "We recommend calling to verify insurance coverage before booking" disclaimer
- Network status shown as confidence level, never as binary "in-network" badge
- Calculation shown step-by-step for any user who wants to see it

### How to Avoid Overclaiming

- Never say "your cost WILL be $X" -- say "your cost is LIKELY between $X-$Y"
- Never claim network status as certain -- say "listed as in-network as of [date] per [source]"
- Show the calculation transparently
- Clearly label mock data vs. real data in the demo

---

## Structural Concerns (Honest Assessment)

These are real risks we need to address, not hand-wave:

### 1. Network Data Reliability
55%+ of provider directories contain errors. Our network status feature depends on fundamentally unreliable data. **Mitigation:** Provenance-first approach explicitly labels confidence. Browser-verified status is more current than published data. We never show a binary "in-network" badge.

### 2. Estimate Range Width
Without deductible remaining, estimates can span $40-$200 for the same visit. Wide ranges may not change behavior. **Mitigation:** Browser-assisted deductible retrieval narrows the range. When we can't narrow it, we show scenario comparisons ("if deductible met: $40 / if not met: $200").

### 3. CPT Licensing
AMA licensing required for displaying CPT codes. **Mitigation:** Use HCPCS public codes, plain-language service descriptions, and Turquoise SSP package names at hackathon. Obtain license post-validation.

### 4. Consumer Trust Bootstrapping
New tool faces cold-start trust problem. **Mitigation:** Provenance IS the trust mechanism. Show sources, show math, show uncertainty. Users trust tools that are honest about what they don't know.

### 5. Insurer Estimator Improvement
Mandated insurer tools could improve. **Mitigation:** Our value is cross-insurer comparison + provenance + workflow simplicity. Insurer tools will never compare across insurers or providers outside their network.

### 6. Consumer Price Sensitivity Debate
Research disagrees on whether transparency reduces spending. **Our thesis:** Non-transparency created learned helplessness, not genuine indifference. When people unknowingly overpay, it looks like loyalty. Show market comparable rates and the pattern breaks.

---

## Data Architecture (Hackathon)

| Layer | Source | Access Method | Real vs Mock |
|---|---|---|---|
| Provider identity | NPPES NPI API | REST API | Real |
| Price benchmarks | CMS PPL API | REST API (key required) | Real |
| Service packages | Turquoise SSP API | REST API | Real |
| Facility prices | DoltHub hospital-price-transparency-v3 | SQL query | Real |
| Network status | Insurer directory (browser verified) | Playwright | Real (demo) |
| Deductible remaining | Insurer member portal | Playwright (user auth) | Real (demo) |
| Plan details | - | User input + mock configs | Mock |
| OOP calculation | Rules engine | Deterministic | Real logic, mock inputs |

---

## Technical Stack (Hackathon)

- **Frontend:** React (provenance-first UI with confidence indicators)
- **Backend:** Python (FastAPI or Flask)
- **Data:** API calls to NPPES, CMS PPL, Turquoise SSP; DoltHub for facility prices
- **Browser automation:** Playwright MCP for deductible retrieval + network verification
- **AI:** Claude API for intent classification + explanation generation
- **Maps:** Google Maps link generation for provider navigation
- **Deployment:** Render (existing yhack-server config)

---

## Success Criteria (Hackathon)

1. User can describe a care need and get matched to "primary care new patient visit"
2. System shows 3-5 nearby providers in New Haven with real data
3. Each provider shows an estimated OOP range with visible provenance
4. At least one estimate uses browser-retrieved deductible data
5. Network status shows confidence level with source attribution
6. User can tap to navigate to provider via Google Maps
7. Judges can inspect assumptions and sources behind any number
