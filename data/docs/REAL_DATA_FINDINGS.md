# Real MRF Data Findings — Phase 10 (2026-05-01)

## Key Discovery: Plan-Level Pricing is 3-6x Variable

Real hospital MRFs reveal **massive plan-level price variation within the same payer**:

| Payer at MGH | Plan | CPT 45378 Rate |
|---|---|---|
| UHC | Medicare Replacement | $1,061 |
| UHC | New Business Discount | $1,666 |
| UHC | PPO/POS | $3,173 |

**453 unique (payer, plan) combinations** for a single CPT across 11 hospitals.
**Coefficient of variation up to 59%** within the same payer.

This is NOT noise — plans reflect different contract terms, network tiers, and cost-sharing structures.

## Current Schema Gap

`HospitalPayerRate` unique constraint is `(hospital_id, cpt, payer_id, source_origin)` — **max one rate per payer**. But real data has 3-8 plans per payer per hospital. The constraint must include `plan_name`.

## Data Volume (GI specialty, 11 hospitals)

| Metric | Count |
|---|---|
| MRF records extracted | 10,244 |
| TiC records extracted | 90 |
| Unique procedures (hospital × CPT) | 183 |
| Payer rates (plan-level) | ~1,991 |
| Unique (payer, plan) combos for CPT 45378 | 453 |

## Format Changes Discovered

All 12 hospitals switched to **CMS v3.0 format** (version: 3.0.0):
- MGB (mgh, brigham, faulkner): standard_csv → cms_v3_csv
- BMC: xlsx → cms_v3_csv+zip
- CHA: plain CSV (not zipped)
- Children's: plain JSON (126MB, behind Incapsula WAF)
- BIDMC, Dana-Farber, Mt. Auburn: JSON with UTF-8 BOM
- Tufts, Franciscan: latin-1 encoding (non-breaking spaces)
- Franciscan: pediatric rehab, 0 GI procedures (expected)

## Implications for ETL Design

1. **Validator** must use `(hospital_id, cpt, payer_id, source_origin, plan_name)` as dedupe key
2. **DB schema** needs `plan_name` in unique constraint for `HospitalPayerRate`
3. **API** should return all plan-level rates, not one per payer
4. **Frontend** should match user's selected plan to the correct rate
5. **Seed migration** must handle plan-level data (currently coalesces to one rate)
