# CareCost Backlog

> Megaplan (`AIOS/WORK/PROJECTS/carecost-release-megaplan.md`) is SSOT for phase-assigned work.
> This file captures items that need research, scoping, or don't fit a phase yet.

## Research Needed (before coding)

### Per-Hospital Cost Component Breakdown (megaplan 60.14-60.16)
**Priority:** High — core product differentiator
**Status:** Placeholder in megaplan. Needs `/deep-research` before implementation.
**Problem:** FAIR Health gives one "recommended" benchmark for all hospitals in a metro. Reality: MGH facility fee ≠ BMC facility fee. Users need actual per-hospital component costs.
**Data gap:** MRF total rates exist, but component breakdown (facility vs physician vs anesthesia) requires parsing billing modifiers or sourcing from claims data.
**Design:** Build once with fallback — actual per-hospital components when available, FAIR Health as labeled reference when not. One function, one display, two data tiers.
**Research prompt:** saved below in Research Prompts section.

### Normalization Boundary Prevention Tooling
**Priority:** Medium — prevent the payer_id mismatch class of bugs
**Status:** Austin wants AIOS-level prevention. Evaluate: `/ssot-project-audit` data flow tracing lens enhancement or new errata-driven coding-time check.

## Data Exploration (needs actual MRF data review)
- [ ] Hospital MRF schema audit: classify each hospital's actual data layout (itemized vs bundle vs gross-only, payer coverage, component breakdown)
- [ ] Bundle price decomposition: use FAIR Health component ratios as priors to estimate physician/facility/anesthesia splits from bundled prices
- [ ] Office visit estimation: same CPT name may have different prices across settings; estimate standard office visit charge from hospital's E&M pattern
- [ ] Shared-charge allocation: when MRF reports facility-only, estimate total from facility + typical professional component

## Infrastructure
- [ ] DuckDB evaluation: when data exceeds 100K rows (multi-geography expansion), benchmark DuckDB ETL intermediate vs PostgreSQL. DuckDB has 10x advantage on columnar analytical queries.
- [ ] AI-assisted data quality review: post-extraction LLM pass to flag suspicious patterns (price 10x median, gross < negotiated inversion, identical rates across payers)
- [ ] ETL agent skill (/refresh-data): AI orchestrator on top of deterministic pipeline, checks staleness, runs extraction, validates, reports
- [ ] TypeScript strict mode: `strict: true` + `noImplicitAny: true` in tsconfig. Prevents silent `undefined` on deleted properties.

## Product
- [ ] Compliance scoring refinement: expand from 4-tier to detailed rubric (CMS-required fields checklist, timeliness, format correctness)
- [ ] Per-CPT NULL reason display: frontend shows "bundled price only" vs "not disclosed" vs "contact hospital" based on null_reason + price_granularity
- [ ] PAYER_LABELS elimination (megaplan 20.21): backend returns `display_name` in `payer_rates[]`
- [ ] Rename `hospitalRatesCsv.ts` → `planConfig.ts` + update 6 importers
- [ ] Strengthen `test_hospitals_excludes_seed_era_rows` with explicit seed+ETL row fixture

## Quick Reference: Phase 30 Remaining (15 items)
See megaplan Phase 30 table. Key: HospitalRate table drop, seed CSV replacement, plan_payment_table.json retirement.

---

## Research Prompts

### Per-Hospital Cost Component Breakdown

Use this prompt with `/deep-research` in a new session:

```
Research how US hospital Machine-Readable Files (MRFs) encode procedure 
cost components, and what data sources exist for per-hospital cost 
breakdowns of medical procedures.

Context: CareCost is a healthcare price transparency app. We show users 
that a colonoscopy generates 4 separate bills (facility, physician, 
anesthesia, pathology). Currently we use FAIR Health 80th percentile 
benchmarks which are geographic constants — the same number for all 
hospitals in a metro area. We want per-hospital actual costs.

Research questions:
1. How do hospital MRFs distinguish facility fees vs professional fees 
   vs anesthesia? What billing modifiers or place-of-service codes 
   are used? (CMS v3.0 format specifically)
2. What percentage of hospitals publish component-level pricing in their 
   MRFs vs bundled totals only? Is there data on this?
3. Beyond MRFs, what other public data sources provide per-hospital 
   component breakdowns? (CMS cost reports, HCRIS, state APCD databases, 
   Turquoise Health, claims aggregators)
4. How does FAIR Health calculate their 80th percentile benchmarks — 
   is it claims-based? How often updated? What geography granularity 
   (ZIP, MSA, state)?
5. Are there existing open-source tools or APIs that decompose a bundled 
   procedure price into components? (e.g., Medicare fee schedule ratios 
   as splitting factors)
6. For our 12 Boston hospitals (MGH, BWH, BMC, BIDMC, etc.) — what is 
   the actual variation in facility fees for CPT 45378 (colonoscopy)? 
   Can we extract this from their published MRFs?

Output: Evidence-grounded findings with source quality ratings. Focus on 
what data is actually available today, not theoretical possibilities.
```
