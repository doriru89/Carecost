# Data Source Inspection Findings

**Date**: 2026-05-02
**Target CPT**: 45378 (Diagnostic Colonoscopy)
**Script**: `data/analysis/inspect_all_sources.py`

## Source Vintage Summary

| Source | Vintage | Last Updated | Format | Size |
|--------|---------|-------------|--------|------|
| CMS PFS RVU | CY2026 | 2025-12-22 | CSV (skip 9 header rows) | 2.5 MB |
| BCBS MA TiC | CY2026 | 2026-05-01 | JSON.GZ (CMS v2.0.0) | 107 MB |
| UHC TiC | CY2026 | 2026-05-01 | JSON.GZ (CMS v2.0.0) | 133 MB |
| Aetna TiC | CY2026 | 2026-04-05 | JSON.GZ (CMS v2.0.0) | ~1,472 MB |
| MassCompareCare | CY2022 | 2026-05-02 (scraped) | JSON (scraped) | 3.5 KB |
| NPPES | Current | 2026-05-02 | JSON (API) | 327 KB |
| CHIA MA APCD | SFY2015 | 2018-07-20 | XLSX | ~stale |

## TiC Format Compatibility

All 3 insurers use CMS TiC v2.0.0 schema. Existing `insurer_rate_parser.py` is compatible.

| Feature | BCBS MA | UHC | Aetna |
|---------|---------|-----|-------|
| version | 2.0.0 | 2.0.0 | 2.0.0 |
| entity_type | Health Insurance Issuer | Insurer | Third Party Administrator |
| negotiated_types | fee schedule | negotiated | (not fully sampled) |
| billing_classes | institutional | institutional, professional | (not fully sampled) |
| has_network_name | Yes | Yes | Yes |
| has_tin/business_name | No | Yes | Yes |
| provider_references structure | provider_group_id + provider_groups[].npi[] | Same | Same |
| File organization | Per plan type | Per state (Insurance Co) or national (Services) | Per rate schedule (pl-XXX) |

**Key Differences:**
- BCBS only reports `fee schedule` type; UHC reports `negotiated` — schema must accept both
- UHC has both `institutional` and `professional` billing classes; BCBS only `institutional`
- Aetna/UHC add `business_name` in `tin` object — useful metadata but not schema-breaking

## CMS RVU — CPT 45378 Detail

Two records (global + modifier 53):
- **Global (no modifier)**: Work=3.18(?), FacPE=1.34, MP=0.41, FacTotal=4.93, CF=$33.4009
- **Modifier 53 (reduced)**: Work=1.59(?), FacPE=0.67, MP=0.21, FacTotal=2.47

Note: CSV header mapping needs verification — column names in file differ from handoff documentation.

## MassCompareCare — CPT 45378

- Bundled scope: facility + physician + anesthesia (no pathology)
- 20 providers returned, only 1 matched our 12 hospitals (Mount Auburn, $1,681)
- 13 payers available for per-payer filtering
- Price range: $734 (Lowell General) to $3,506+ (highest)

## CHIA Layout Analysis

CHIA's Excel has 703 columns (wider than expected). Key columns for state source design:

**Maps to existing schema:**
- ProviderNPI → providers.npi / hospital_all_npis()
- payer_display → payers.canonical_name  
- ServiceCode → hospital_procedures.cpt
- ProviderTaxonomyType → providers.taxonomy

**New fields for future state APCD integration:**
- ServiceType_Level1..Level4 → service category taxonomy (4 levels)
- NumberServices → utilization count
- NumberProvs_forPayerAndService → provider count per service
- ProviderTaxonomyGroup/Detail → taxonomy hierarchy

These are **informational for DataSource table design**, not for Phase 3 migration.

## Schema Recommendations

1. **Temporal columns**: `rate_year` + `effective_date` on HospitalPayerRate, `data_vintage` on HospitalBenchmark
2. **Provenance**: `source_file` on all rate tables, DataSource reference table with display_name
3. **RVU decomposition**: CptRvuComponent table with per-component RVUs + conversion factor
4. **Hospital dimension**: `facility_type` + `is_curated` on Hospital
5. **API contract**: ProvenanceResponse nested in every price endpoint response
6. **Future extensibility**: DataSource table designed to accommodate CHIA/SPARCS when fresh data available
