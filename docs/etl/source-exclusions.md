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
