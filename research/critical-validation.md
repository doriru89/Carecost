# Critical Validation: Provenance-First Healthcare Shopping

**Date:** 2026-03-27
**Purpose:** Brutally honest assessment of the product thesis against consolidated research evidence.

---

## Verdict: Strong thesis with real risks. Build it, but with eyes open.

The core idea -- provenance-first healthcare cost estimation -- is genuinely differentiated and addresses a documented consumer pain point. The browser automation angle adds a unique technical wedge. But several structural risks need honest acknowledgment, not hand-waving.

---

## What the Research VALIDATES

### 1. Provenance-first is genuinely differentiated
**Evidence:** Both research sources independently confirm: "No existing healthcare tool implements a provenance chain for cost estimates." Not insurer tools (opaque single numbers), not cash-pay marketplaces (different problem), not data platforms (B2B, no consumer UX). The closest analogy is "delayed 15 min" on stock prices or confidence bands on weather forecasts. Healthcare needs this pattern and nobody has built it.

**Strength of evidence:** HIGH. Confirmed across competitor analysis, academic research, and regulatory documentation.

### 2. Consumer pain is severe, documented, and specific
**Evidence:**
- 70% of consumers do not price-shop for healthcare at all (Becker's)
- 42% find estimates confusing when they try (PMC/JMIR)
- 53% of mental health provider directories are inaccurate (Health Affairs)
- 83% of consumers who try to shop attempted to negotiate -- they WANT to engage (PMC/JMIR)
- Negative sentiment correlated with seeking value -- the system punishes shoppers

**Strength of evidence:** HIGH. Multiple independent sources, large sample sizes.

### 3. The "packaging + trust" thesis is correct
**Evidence:** Congressional Research Service (2025), Brookings, and academic studies all converge on the same conclusion: the bottleneck has shifted from data availability to usability. The data exists (100+ TB). The problem is that it's fragmented, messy, and not consumer-packaged. Specifically, insurer cost estimators exist (mandated since Jan 2024) but are "built for compliance, not for consumer decision-making."

**Strength of evidence:** HIGH. Regulatory, academic, and industry sources agree.

### 4. Deterministic-first is the correct architecture
**Evidence:** Research consistently shows AI is worse at cost calculation than rules engines. The math (deductible + coinsurance + OOP max) is simple and deterministic. The hard part is getting accurate inputs, not computing the output. Using AI only for intent classification and explanation is the right separation of concerns.

**Strength of evidence:** HIGH. No counter-evidence found.

### 5. Browser automation for deductible access is a real, underexplored opportunity
**Evidence:** Every existing tool either (a) asks users to self-report deductible remaining (inaccurate -- most don't know), (b) requires enterprise API integration (X12 270/271, payer Patient Access APIs -- slow, expensive, requires contracting), or (c) ignores accumulators entirely (producing wide, unhelpful ranges). Browser-assisted portal access is a middle path that works now with Playwright and doesn't require business relationships.

**Strength of evidence:** MEDIUM-HIGH. No competitor does this. Technical feasibility depends on insurer portal anti-automation defenses.

---

## What's WEAKER Than It Sounds

### 1. "Why now" is softer than the product doc claims

**The claim:** "This product is newly possible because transparency data has become much more available."

**The reality:** Hospital price transparency data has been mandated since January 2021. Payer TiC files since July 2022. Standardized hospital MRF templates since July 2024. That's 2-5 years of data availability.

**The uncomfortable question:** Turquoise Health ($40M Series C), Serif Health (300+ customers, YC-backed), and Ribbon Health ($43.5M Series B) have had years to build consumer-facing tools. They all chose B2B instead. Why?

**Possible explanations:**
- B2B monetizes faster and more predictably
- Consumer trust bootstrapping is genuinely hard
- The consumer UX problem requires product DNA, not data engineering DNA
- Regulatory/compliance burden for consumer tools is higher

**Assessment:** The "why now" should emphasize browser automation (genuinely new capability), FHIR/Plan-Net API adoption (growing), and high-deductible plan prevalence (55%+ of employer-insured workers), not just "data exists." The data has existed for years.

### 2. Without deductible remaining, estimates are too wide to be useful

**The math:** For a primary care visit with a $200 negotiated rate:
- If deductible met + 20% coinsurance: patient pays ~$40
- If deductible NOT met: patient pays ~$200
- That's a 5x range. A "$40-$200" estimate may not change behavior.

**Research supports this concern:** Studies show that transparency tools with wide ranges don't measurably reduce spending (RAND, AJMC). Consumers need actionable precision, not theoretical ranges.

**Mitigation:** This is exactly why the browser-assisted deductible retrieval is so important. It's not a nice-to-have -- it's the feature that makes the product actually useful. Without it, we're just another wide-range estimator.

**Assessment:** CRITICAL risk. The product lives or dies on whether browser automation can reliably retrieve deductible data. Make this the hackathon priority, not a stretch goal.

### 3. Network data is fundamentally unreliable

**The evidence:**
- CMS estimates 55%+ of provider directories contain at least one critical error
- 72% of inactive behavioral health providers should not have been listed
- Patients using inaccurate directories are 4x more likely to get surprise bills

**Implication:** A core promised feature ("check likely in-network status") depends on data that is wrong more than half the time. Even with provenance labeling, showing "likely in-network (medium confidence)" when the underlying data is this bad could erode trust rather than build it.

**Mitigation:** Browser-verified network status (querying the insurer's own directory search tool) is more current than published data. The 90-day verification mandate (effective July 2025) may gradually improve baseline accuracy. But the fundamental problem persists.

**Assessment:** MEDIUM-HIGH risk. Provenance labeling helps, but "likely in-network" with 55% error rate is still a bad user experience. Consider whether network status should be a primary feature or a secondary indicator.

### 4. The "70% don't shop" statistic cuts both ways

**The product doc's interpretation:** "Tools are bad, so people don't shop. Fix the tools, people will shop."

**Alternative interpretation:** Healthcare shopping is structurally different from flights/hotels:
- Patients have established relationships with providers
- Referral chains constrain choice
- Geographic access matters more than price for many services
- Care urgency reduces willingness to comparison-shop
- Employer-sponsored insurance insulates consumers from full costs
- Trust in provider recommendations outweighs price sensitivity

**The research is ambiguous:** Some studies show self-pay patients respond to pricing (Brookings). Others show no measurable decrease in insured patient spending (RAND, AJMC). The disagreement likely reflects that insured patients genuinely have less price sensitivity than self-pay patients.

**Our thesis (worth testing):** Non-transparency created learned helplessness, not genuine indifference. People paying $400 for a visit that costs $120 at the clinic down the street aren't loyal -- they're uninformed. Show market comparable rates and guided recommendations, and behavior changes.

**Assessment:** MEDIUM risk. This is a testable hypothesis, not a proven fact. The hackathon can validate whether consumers engage when shown comparable options with clear provenance.

### 5. Insurer estimators will improve

**Current state:** Since January 2024, every major insurer must provide an online cost estimator. These tools are currently bad -- clunky, opaque, no provenance, no cross-provider comparison.

**But:** They have the actual data. They know the exact negotiated rate, the exact deductible remaining, the exact coinsurance rate. If UnitedHealthcare hires a good product team and rebuilds their estimator, our data advantage narrows significantly.

**Our structural advantage:** Insurer tools will never:
- Compare across insurers (competitive data)
- Compare providers outside their network
- Show provenance (incentive to be opaque about methodology)
- Provide the "neutral trusted advisor" positioning

**Assessment:** LOW-MEDIUM risk. Insurer tools are improving but slowly, and they'll never be neutral. Our cross-insurer comparison and provenance-first positioning remain differentiated even if individual insurer tools get better.

---

## Structural Risks the Product Doc Must Address

### 1. Monetization clarity
**Risk:** B2C healthcare tools are notoriously hard to monetize. GoodRx needed massive scale. Turquoise/Serif chose B2B.

**Current answer:** B2B2C via insurer partnerships (Hasper AI sponsor angle). Insurers pay for better member experience, reduced call center volume, transparency compliance.

**Honest assessment:** This is a plausible but unvalidated business model. Key question: would an insurer actually pay for a tool that helps consumers shop across providers (potentially including cheaper competitors)? Insurers benefit from lower costs, but they also benefit from keeping members in their preferred provider tiers.

**Recommendation:** The hackathon pitch should present this as the monetization thesis, not the monetization proof. "We believe insurers will pay for this because [specific value props]. Our next step is to validate with Hasper AI."

### 2. Data freshness for the hackathon
**Risk:** Can we actually get real, current price data for New Haven, CT in the 36-hour hackathon window?

**Assessment:** Likely yes for benchmarks (CMS PPL is always available, NPPES is real-time). Less certain for facility-specific negotiated rates (DoltHub coverage varies by hospital). Network verification via browser depends on portal availability.

**Mitigation:** Have mock data ready as fallback for gaps. Clearly label real vs. mock in the demo. The provenance UX makes this honest -- "no real data available for this provider; showing regional benchmark" is itself a demonstration of the product's value.

### 3. Browser automation reliability
**Risk:** Insurer portals may have anti-automation defenses (CAPTCHAs, bot detection, rate limiting). Playwright may not work reliably against all portals.

**Assessment:** HIGH risk for production, MEDIUM for hackathon demo. For the demo, we need it to work against one insurer, once, on stage. We can pre-verify which insurer portal is most automation-friendly.

**Recommendation:** Test Anthem BCBS CT and UHC portals before the hackathon. Have a recorded fallback demo if live automation fails.

### 4. Regulatory positioning
**Risk:** "Decision support tool showing publicly available data" is correct framing, but healthcare regulation is complex. State insurance commissioner offices, HIPAA implications of browser-accessed data, AMA licensing for CPT display.

**Assessment:** LOW risk for hackathon. MEDIUM risk for production. At hackathon stage, this is a prototype. For production, need legal review.

**Recommendation:** Include standard disclaimers in the prototype. Do not claim to provide medical advice or insurance guidance.

### 5. The "compare" UX is harder than it looks
**Risk:** Comparing providers requires normalizing across:
- Different billing structures (facility fee + professional fee + ancillary)
- Different plan designs (copay vs. coinsurance vs. deductible-first)
- Different confidence levels (some providers have real negotiated rates, others only benchmarks)

**Assessment:** MEDIUM risk. For ONE service category (primary care new patient visit), the comparison is simpler because it's typically a single bill. For imaging or procedures with unbundled components, this gets dramatically harder.

**Recommendation:** This is why narrowing to ONE service category is critical. Primary care new patient visit is the simplest comparison case.

---

## Recommended Adjustments (Post-Validation)

### 1. Make browser-assisted deductible retrieval the hero feature
The estimate precision depends entirely on this. Don't treat it as a stretch goal -- it's the feature that makes the product actually useful versus another wide-range estimator.

### 2. Lead with provenance UX, not estimate accuracy
The estimate will have uncertainty. That's fine. The provenance display IS the product. "Here's exactly what we know, what we assumed, and what would change the number" is more valuable than a precise number most tools can't deliver anyway.

### 3. Frame as "pre-call preparation" not "shopping"
"Healthcare shopping" triggers resistance ("healthcare isn't a commodity"). "Before you call to book, here's what we found and what to ask about" is more honest and more useful.

### 4. One category, bulletproof
Primary care new patient visit. One geography. Real data. Perfect provenance. This is more impressive at a hackathon than three categories with gaps.

### 5. Test the consumer behavior hypothesis
The hackathon can't prove "people will shop if given better tools" -- but it can demonstrate engagement. If judges and audience members start saying "I wish I had this for my last doctor visit," that's validation.

### 6. Insurer partnership framing for pitch
"We build the consumer experience layer that insurers can't build themselves. They have the data but not the UX DNA. We have the UX but need their data access and distribution. Win-win."

---

## Final Assessment

| Dimension | Rating | Notes |
|---|---|---|
| Problem validity | STRONG | Documented, quantified, multiple sources |
| Differentiation (provenance) | STRONG | No one does this; genuine gap |
| Differentiation (browser automation) | STRONG but RISKY | Novel approach, uncertain reliability |
| Data availability | MEDIUM | Benchmarks: good. Personalized data: hard. |
| Monetization | PLAUSIBLE but UNVALIDATED | B2B2C via insurers is logical but untested |
| Technical feasibility (hackathon) | HIGH | APIs ready, Playwright available, scope narrow enough |
| Technical feasibility (production) | MEDIUM | Browser automation fragile, API integrations needed, CPT licensing |
| Consumer behavior change | UNCERTAIN | Testable hypothesis, not proven fact |
| Competitive moat | MEDIUM | Provenance + browser automation is novel but replicable |

**Bottom line:** Build it. The thesis is sound, the differentiation is real, and the hackathon scope is achievable. But be honest in the pitch about what's proven (the consumer pain, the data gap, the provenance opportunity) versus what's a bet (consumer behavior change, insurer willingness to pay, browser automation reliability at scale).
