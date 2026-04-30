# CareCost Backlog

## Data Exploration (needs actual MRF data review)
- [ ] Hospital MRF schema audit: classify each hospital's actual data layout (itemized vs bundle vs gross-only, payer coverage, component breakdown)
- [ ] Bundle price decomposition: use FAIR Health component ratios as priors to estimate physician/facility/anesthesia splits from bundled prices
- [ ] Office visit estimation: same CPT name may have different prices across settings; estimate standard office visit charge from hospital's E&M pattern
- [ ] Shared-charge allocation: when MRF reports facility-only, estimate total from facility + typical professional component

## Infrastructure
- [ ] DuckDB evaluation: when data exceeds 100K rows (multi-geography expansion), benchmark DuckDB ETL intermediate vs PostgreSQL. DuckDB has 10x advantage on columnar analytical queries.
- [ ] AI-assisted data quality review: post-extraction LLM pass to flag suspicious patterns (price 10x median, gross < negotiated inversion, identical rates across payers)
- [ ] ETL agent skill (/refresh-data): AI orchestrator on top of deterministic pipeline, checks staleness, runs extraction, validates, reports

## Product
- [ ] Compliance scoring refinement: expand from 4-tier to detailed rubric (CMS-required fields checklist, timeliness, format correctness)
- [ ] Per-CPT NULL reason display: frontend shows "bundled price only" vs "not disclosed" vs "contact hospital" based on null_reason + price_granularity
