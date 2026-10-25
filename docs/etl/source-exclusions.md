# Source exclusions and TiC row flags (A6, wave 2 round C4)

O's outlier audit (`docs/etl/outlier-audit.md`) traced each outlier to its source row. The fixes
that belong to the ETL are applied here, at the source, so the pack never sees those rows as
prices. Nothing is deleted: an excluded row stays in `rate_row` with `excluded = true` and an
`exclude_reason`, and can still be cited.

## Exclusions (`excluded = true`, never in the pack)

| `exclude_reason` | Rule | Where | O's example |
|---|---|---|---|
| `not_dollars` | a stated payer dollar under 1% of the row's own gross (`gross_rule = same_row`) | hospital normalize (`app.etl.normalize.source_exclusion`) | CHA line 187058: $5.04 on a $3,510.55 colonoscopy |
| `chargemaster_as_rate` | amount == the row's gross **and** the file's text says "No contract line matched" | hospital normalize | Tufts line 1210827: MEDICARE $608.00 = gross |
| `per_diem_or_case_rate` | methodology per diem / case rate, or the description, plan or TiC item text says per diem, half day or case rate; TiC `negotiated_type: per diem` | hospital normalize, `app.etl.tic.normalize` | Children's "HC PER DIEM PAIN TREATMENT" on 99215 |

The counts per source are in each normalized file's `*.stats.json` (`excluded`) and in each TiC
run's `run.json` (`normalize.excluded`).

## TiC flags (`flags.parquet`, the row stays a price)

`RateRow` has no flags column (`backend/app/etl/contracts.py` is C3's), so each TiC run writes
`flags.parquet` (`row_id`, `flags`: '|'-joined) next to `rate_row.parquet`, and counts them in
`run.json` `flags`. `app.etl.tic.flags.load_flags(run_dir)` reads it. Rules are in
`backend/app/etl/tic/flags.py`:

| Flag | Rule |
|---|---|
| `anesthesia_per_unit` | an anesthesia code whose TIN lists the same amount on another anesthesia code with different CMS base units (the CMS base-units file in the store) |
| `institutional_on_physician_npi` | `billing_class: institutional` on a provider group that is a single NPI, which NPPES types as a person (NPI-1) or a physician-group organisation (NUCC 193 / 207 / 208). Lookup: `data/etl/tic_npi_types.yaml` from `python -m app.etl tic npi-types` |
| `same_npi_pos_multi_rate` | several amounts for one TIN, the same NPI set, code, modifiers, billing class, POS list and negotiated type (from different provider or rate groups). These rows also get `ambiguous_multi_rate = true` |

`tic normalize` and `tic extend` apply the flags after normalizing. `tic run` does not yet: run
`tic normalize` after it.

## Configuration changes

* `tic_networks.yaml`: `tic_mgb_hp_mgb_aso` gets product `PPO`. MGB's TOC lists 10 plans on that
  file (sponsor "ASO PHS"): 6 PPO, 2 Premium EPO, 2 Select. With product `""` it joined every MGB
  product.
* `codes.yaml`: `path_area_domains` for `gi_abdomen` (gi) and `skin_rash` (derm), with
  descriptions for the stomach-ache lab and imaging codes and 87220.
* Sites (`app.sites.build`): a census `multi` row takes its service areas from its own name first
  (dermatology / skin, orthopedic / sports medicine / spine, gastroenterology / endoscopy), and
  only then from the CMS clinician counts at the address. `curated.yaml` makes
  `new_england_baptist_surgery_center_llc_dedham` orthopedic (nebh.org, 2023-06-28). A curated
  area change drops the census-category service it overrides (`endoscopy`).

## Not excluded, on purpose

* Epic-format files (Brigham, MGH, Faulkner, NWH, Tufts, BMC, CHA) write `Case rate ($225.91). The
  procedures on the claim are sorted highest to lowest by case rate and reimbursed ... 1 procedures
  at 100%` in `negotiated_algorithm` on rows whose methodology is `fee schedule` / `other`. That is
  a per-procedure price with a multiple-procedure reduction, not a bundle: 2,000 such rows stay
  prices (62 of them are outliers in O's audit, which reads the same text as "case rate").
* CHA rows where amount == gross with no "No contract line matched" text (3,360 rows) stay: the
  rule needs both tests.

## Measured (A6 run, 2026-10-25, A5's data root cloned)

Hospital normalize, rows excluded per source: bmc_brighton 320, bmc 580, bmc_south 325,
cha 461 per-diem/case-rate + 33 not_dollars, childrens 248, faulkner 21, newton_wellesley 30,
tufts 811 chargemaster_as_rate + 44 per-diem/case-rate (2,029 / 33 / 811 in all). TiC: 0 per-diem
prices on our codes. Flags and their counts per network: each run's `run.json` `flags`.

## A7 (wave 2 round C6, 2026-10-25): ED visit levels as reference codes

`codes.yaml` `reference:` holds 99281-99285 (emergency department visit, levels 1-5). They are in
`CodeList.codes`, so hospital normalize, the TiC filter (`tic extend`) and the pack carry them, but
they are in no domain: `Registry.code_areas` gives no area, no site admits them and nothing is
ranked on them. They are not care-path codes, so `codes check` is unchanged; `codes check --data`
passes after the re-extraction below. C4b reads them for the response-level ER reference.

Run (A6's data root cloned with `cp -c -R`, flags as A6):

```bash
cd backend
uv run --frozen --extra etl python -m app.etl --data-dir $D normalize --force
uv run --frozen --extra etl python -m app.etl --data-dir $D tic extend --network all
uv run --frozen --extra etl python -m app.etl --data-dir $D build --build-date 2026-10-25 \
  --baseline-manifest <previous build>/manifest.json
uv run --frozen --extra etl python -m app.quote.pack --hospital-build $D/build/20261025-336340ed \
  --tic-root $D/intermediate/tic --gov-root $D/intermediate/gov --out a7.sqlite
```

`tic extend`: 38 of 38 networks, +5 items each; 34 by HTTP Range, 4 UHC files streamed (the host
answers 200 to Range; sha256 checked). No new single-NPI institutional groups, so
`tic_npi_types.yaml` needed no NPPES call.

Measured in the pack (build `20261025-336340ed`, 2,068,299 rows; A6's was 1,963,462):

* hospital files, 1,517 ED rows (facility; CHA's have no revenue code, so component `unknown`):
  bid_milton 25, bid_needham 15, bidmc 35, bmc 270, bmc_brighton 212, bmc_south 212, brigham 50,
  cha 110, childrens 175, faulkner 26, mgh 48, mtauburn 40, nebh 20, newton_wellesley 9, tufts 270.
  Dana-Farber and Franciscan post none. By payer: TUFTS_HP 183, BCBS_MA 148, UHC 148, MGB_HP 95,
  WELLPOINT 82, AETNA 66, CIGNA 63, FALLON 56, HARVARD_PILGRIM 51, CCA 50, MEDICARE 43,
  MASSHEALTH 35, WELLSENSE 30, HUMANA 29, TRICARE 13, HNE 10, UHC_HPHC_ALLIANCE 6, unmapped
  payer 384, chargemaster (gross only) 25. Example: CHA 99284 "CHA HB BCBS PPO" $807.72, gross
  $2,200.00. CHA's raw file has 360 ED rows; 250 are excluded at the source (catch-all plans 125,
  dental 70, behavioral carve-out 20, out of state 20, per diem / case rate 10, workers' comp 5).
* TiC, 103,300 ED rows (100,962 professional, 2,338 facility) in all 38 networks: AETNA 33,497,
  HARVARD_PILGRIM 30,315, BCBS_MA 17,353, MGB_HP 16,115, UHC 3,675, TUFTS_HP 1,960, FALLON 385.
  37,006 of them list POS 23 (emergency room).
* gov fee schedules: Medicare PFS 10, OPPS 5, MassHealth 5.
