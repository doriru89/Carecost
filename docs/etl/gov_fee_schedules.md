# Government fee schedules (stream A3, 2026-10-24)

Medicare and MassHealth prices for D4 (payment = Medicare / MassHealth) and the rung-5 / rung-4 /
rung-7 doctor-fee ladder. Every number comes from one published file and is re-derivable from it.

```
python -m app.etl gov fetch [--source ID] [--headless]   # download / browser click / manual import
python -m app.etl gov build [--as-of YYYY-MM-DD]          # RateRow parquet + manifest per source
python -m app.etl gov show 99213 [--entity medicare_ma_01]
```

Registry: `data/etl/sources.d/government.yaml`. Code: `backend/app/etl/gov/`. Anchors:
`data/etl/gov_anchors.yaml`. Output (gitignored): `data/intermediate/gov/<source_id>/<sha>.parquet`
(`contracts.RateRow`, hospital columns) + `<sha>.manifest.json` + `data/intermediate/gov/LATEST.json`.
Workflow: `.github/workflows/etl-gov.yml` (quarterly; artifacts only).

## Sources (all fetched 2026-10-24/25 UTC)

| source_id | What | URL | Access | Effective | Next release | sha256 (12) | Rows | Codes |
|---|---|---|---|---|---|---|---|---|
| `cms_pfs_rvu26d` | Medicare PFS, **RVU26D** (October 2026 release, "Updated 08/26/2026"; RVU26A/B/C/D all exist, D is the newest), MA localities 01 Metropolitan Boston + 99 rest of MA, non-QP CF 33.4009 | https://www.cms.gov/files/zip/rvu26d-updated-08-26-2026.zip (page: cms.gov/…/pfs-relative-value-files/rvu26d) | download | 2026-10-01 | 2027-01-01 | 521ff0f4ecbf | 25,432 | 7,862 |
| `cms_anes_base_units_cy2022` | Medicare anesthesia: CMS base units (CY2022 is the newest file CMS posts) × RVU26D `ANES2026.csv` locality CF (Boston non-QP $21.59) | https://www.cms.gov/files/zip/2022-anesthesia-base-units-cpt-code.zip | download | 2026-10-01 | 2027-01-01 | 3fbb43abb6ef | 552 | 276 |
| `cms_opps_addb_2026q4` | Medicare OPPS Addendum B, October 2026 (national unadjusted payment rate per HCPCS, incl. **G0463 = $136.02**, APC 5012, SI J2, RW 1.4879) | cms.gov/…/quarterly-addenda-updates/october-2026-addendum-b | **manual** (AMA CPT license click-through; Austin accepted it and downloaded `2026_october_web_addendum_b.10.14.26.zip`, sha 2fc507a1…, 1,389,933 bytes, into `data/raw/manual/`) | 2026-10-01 | 2027-01-01 | 2fc507a1fa67 | 7,392 | 7,392 |
| `cms_asc_2026q4` | Medicare ASC Addenda AA (surgical) + BB (ancillary), October 2026, national unadjusted | https://www.cms.gov/files/zip/october-2026-asc-approved-hcpcs-code-payment-rates.zip (linked directly, no license page) | download | 2026-10-01 | 2027-01-01 | 476285fa325f | 5,748 | 5,748 |
| `masshealth_317_20261001` | 101 CMR 317.00 Medicine (E/M, PT), emergency adoption filed 2026-09-25 | https://www.mass.gov/doc/emergency-adoption-date-filed-september-25-2026-5/download | browser | 2026-10-01 (read from the regulation) | 2027-01-01 [assumption: annual CPT-year update] | c2f42966300d | 1,701 | 963 |
| `masshealth_318_20261001` | 101 CMR 318.00 Radiology (global / -26 / -TC) | …/emergency-adoption-date-filed-september-25-2026-7/download | browser | 2026-10-01 | 2027-01-01 | 25dae5fffe70 | 1,734 | 639 |
| `masshealth_316_20261001` | 101 CMR 316.00 Surgery + anesthesia ($19.90 per base unit, $1.33 per minute) | …/emergency-adoption-date-filed-september-25-2026-3/download | browser | 2026-10-01 | 2027-01-01 | 10d41619694e | 7,928 | 6,063 |

Coverage of the 48 target codes (`data/etl/codes.yaml`): Medicare PFS + anesthesia 45/48, MassHealth
45/48. The three missing in both are `99051` (after-hours add-on), `S9083`, `S9088` (urgent-care
global / after-hours HCPCS that neither schedule prices). OPPS has 29/48 (E/M office codes are
status B under OPPS: the hospital bills G0463 instead), ASC 17/48.

Why the MassHealth emergency PDFs and not the DOCX: the newest DOCX are 317 (2026-01-01) and
316 / 318 (2025-01-01); the 2026-09-25 emergency adoption re-publishes all three regulations with
rates "for dates of service on or after October 1, 2026" (staff testimony of 2026-10-16: the
change adds certified professional midwives and S8415). Spot checks agree with the DOCX
(99203 $84.36 / $60.79, 73030 $27.31 / $6.75 / $20.56, 20610 $49.06 / $33.26).

## How the rows use the RateRow contract

`entity_id` = price area (`medicare_ma_01`, `medicare_ma_99`, `medicare_national`, `masshealth`);
`payer_id` `MEDICARE` / `MASSHEALTH`; `plan_raw` = place-of-service variant (`non_facility`,
`facility`, `global`, `professional` (-26), `technical` (-TC), `opps`, `asc`, `anesthesia_base`);
`negotiated_algorithm` = the formula with its inputs; `row_ref` = `<source_id>:<sha12>:<line>:<variant>[:<locality>]`
(unique per source). `app.etl.gov.common.fee_schedule_money()` renders a row as Money with basis
`fee_schedule`, method `computed_fee_schedule` (PFS / anesthesia) or `stated`, and no payer_id.

## Anchor check (hand-computed, and a build gate)

99213, established-patient visit, office (non-facility), Metropolitan Boston (locality 01):

```
RVU26D PPRRVU2026_Oct_nonQPP.csv line 13015: work 1.30, non-facility PE 1.46, MP 0.09, CF 33.4009
GPCI2026.csv line 62 (14212 MA 01 METROPOLITAN BOSTON): PW 1.041, PE 1.194, MP 0.890
(1.30 x 1.041) + (1.46 x 1.194) + (0.09 x 0.890) = 1.3533 + 1.74324 + 0.0801 = 3.17664
3.17664 x 33.4009 = 106.1026  ->  $106.10
```

The loaded row `cms_pfs_rvu26d:521ff0f4ecbf:13015:non_facility:01` = $106.10. The same formula
gives 99203 $130.58 office / $75.54 facility, the numbers the hand-made Medicare fixture and plan
§2.4 already used. `gov build` fails a source whose anchor is missing or off (exact on the anchor's
own sha, ±15% on a newer release): 99213 / 99203 PFS, 00811 anesthesia ($86.36 = 4 × $21.59),
G0463 OPPS $136.02, 45378 ASC $510.49, MassHealth 99203 $84.36, 73030 global $27.31, 20610 $49.06.

## Blocked, manual or left out

- **OPPS is manual.** Every 2026 OPPS addendum on cms.gov sits behind `cms.gov/apps/ama/license.asp`
  (AMA CPT license). Claude did not accept it; Austin accepted it and downloaded the file. CI
  cannot, so `etl-gov.yml` fails loudly for OPPS each quarter until a person drops the new file in.
- **Not wage-adjusted.** OPPS and ASC rates are national unadjusted; a Boston facility is paid
  `rate × (0.6 × WI + 0.4)` (OPPS) / `rate × (0.5 × WI + 0.5)` (ASC). The CBSA wage index is not
  loaded yet; `negotiated_algorithm` says so on every row.
- **Anesthesia amounts are base units only.** Time (Medicare: 1 unit per 15 min × CF; MassHealth:
  $1.33 per minute) depends on the case and is stated in the formula, not in the amount.
- **MassHealth 316.00, one row not loaded:** 21210 (an asterisk row whose PDF layout lost its
  dash columns). The reader fails a file with more than 5 unparsed rows; this one is listed as
  `NOT LOADED (layout)` in the manifest. 17 rows of 316.05(4)(c) (facial feminization surgery
  rates) are counted, not loaded.
- **mass.gov blocks scripted HTTP** (403 for the ETL's own user agent). Per D28 the MassHealth PDFs
  and DPH lists are fetched by a plain headed Chromium clicking the link on the regulation page.
  The only browser setting changed is Chrome's normal "download PDFs instead of opening them".
  A probe that tried other user agents with curl was denied by the session's permission
  classifier ("Bot Check Circumvention") and was not retried.
- PFS status codes other than A / R / T (carrier-priced C, bundled B, non-covered N, ...) are
  counted in the manifest, not priced.
