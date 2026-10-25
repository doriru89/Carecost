# Outlier audit (stream O, wave 2 round C3)

Austin's launch goal: no price 3x off its peers without a known cause ("没有不确定原因的3倍"). This
audit measures every line against its X2 peers, traces each outlier to the source row, gives it a
mechanical cause, simulates the fixes at the source, and backtests the two X2 peer modes. It
changes no engine or ETL code.

## Re-run

```bash
cd backend
uv run --frozen --extra etl python -m app.audit \
  --pack <quote_pack.sqlite> [--out ../data/audit] [--sites <sites.yaml>] \
  [--raw-root .../a3-gov-sites/data/raw/store] \
  [--staging-root .../a3-gov-sites/data/intermediate/staging] \
  [--tic-root .../a2-tic/data/intermediate/tic]
uv run --frozen --extra dev pytest -q -p no:cacheprovider tests/audit   # 13 tests
```

About 60 s on the full pack. Outputs:

* `data/audit/outliers.csv`: one row per outlier line, most extreme first. It gives the line, its peers, the
  extreme row's source pointer and quoted source text, the cause, the proposed fix, and whether the
  line is still an outlier after the simulated fixes.
* `data/audit/summary.json`: the denominators, cause counts, the fix simulation step by step, and the
  backtest (before and after the fixes).

Code: `backend/app/audit/` (`peers.py` lines and peer medians, `causes.py` cause rules,
`fixes.py` fix simulation, `backtest.py`, `trace.py`, `__main__.py`).

## What is measured

Run of 2026-10-25: the full pack `after.sqlite` (build `20261024-336340ed`, TiC `tic-2026-10`,
1,195,451 rows) and the 208-site `data/sites/sites.yaml`. Loaded with the registry's TIN filter,
the same way the server loads it: 1,047,791 rows.

* **Line**: (site kind, billing group, code, modifier, component, payer, plan product, network).
  * The site kind follows X2: urgent_care, office, hospital_outpatient or asc.
  * The billing group is the TiC billing TIN. For a hospital file it is `mrf:<source>`. A TiC
    facility row at a hospital site joins that hospital's group.
  * The network is one TiC file. Hospital-file rows have the network `hospital_file`.
  * The rows a line holds follow the engine's own selection (`_site_lines`, `_facility_cell3`,
    `_doctor_cell`, `_tic_rows`):
    * A two-part site gets a facility line and a doctor or reading line. The reading line uses
      modifier 26 and reads any place of service (POS).
    * An office site gets one global line, filtered on its billing type's POS list.
    * Self-pay means the hospital file's discounted cash. Medicare and MassHealth mean the
      hospital file's own rows for that payer, minus `masshealth_plan_exclude`.
* **Peer median**: the median, over the *other* billing groups of the same peer key (everything in
  the line except the group), of each group's median price. A line is **measured** when it has at
  least 5 other groups. It is an **outlier** when its highest row is above 3x the peer median or
  its lowest row is below 1/3x (P8). Using the extreme rows rather than the line's median means a
  number the app can show (the range ends) is what gets checked.
* **Where this is narrower than X2**: X2 says "payer and plan product (network)". I read that at the
  network level, one TiC file per line. The engine's default request (no network named) instead
  pools every file of the payer and product into one range. At that product level there are
  8,302 outliers in 101,874 measured lines (8.1%). The extra spread comes from pooling networks
  that pay very differently. MGB's ASO employee file has no product, so it is read for every MGB
  product. MGB Select HMO pays about 1/3 of Value HMO. See "needs from other streams" below.

## Result

| | count |
|---|---|
| lines built | 221,735 |
| lines measured (>= 5 other groups) | **212,544** (office 145,307, hospital_outpatient 45,803, urgent_care 21,434; asc 0: only 6 ASCs, never 5 peer groups) |
| outlier lines | **11,125 (5.23%)**. Office: 2,342 high, 3,800 low. Hospital outpatient: 1,608 high, 1,464 low. Urgent care: 817 high, 1,094 low |
| distinct source rows outside the band | 13,936 |
| outliers traced to a source row | 11,125 of 11,125. Hospital rows: 543, all opened in the raw file (325 CSV line + 218 JSON path), and every quote contains the exact amount. TiC rows: 10,582, quoted from A2's staged copy of the raw `negotiated_prices` object (the raw `.json.gz` is not on disk, see Limits), and every staged `negotiated_rate` equals the pack amount |
| outliers left after fixes F1 to F5 | **2,954 of 203,619 measured (1.45%)** |
| unexplained | **201** (172 of them are still outliers after the fixes) |

## Causes

The rules are in `backend/app/audit/causes.py`. Each one is a test you can re-run on the row. The
first rule that matches names the cause. The example quotes are verbatim from the raw file (for
hospitals) or from A2's staged raw object (for TiC).

| Cause | Outliers | Test | Example (source) | Fix at the source | Owner |
|---|---:|---|---|---|---|
| parse / unit error: `not_dollars` | 3 | The hospital "dollar" is under 1% of the row's own gross charge | CHA `2efdf1cef584…csv` line 187058: `HC Diagnostic Colonoscopy Flexible,CASE-45378,…,3510.55,3510.55,FALLON [50006],CHA HB FALLON CAREPLUS,5.04,…,fee schedule,4.44,1139.7`. A $5.04 facility fee for a $3,510.55 colonoscopy, also on the Medicare row | normalize: stated dollar < 1% of gross: excluded, reason `not_dollars` | A5 |
| placeholder / `chargemaster_as_rate` | 15 | The hospital payer amount equals the row's gross to the cent | Tufts `d16771049bc4….zip` line 1210827: `HC US Compl Joint R-T W/Img,…,608.00,425.60,MEDICARE [400001],XR HB MEDICARE TMC,608.00,…,other,112.51,912.00,No contract line matched` | normalize: amount == gross, especially with "No contract line matched": excluded (F1) | A5 |
| percent-of-charges read as dollars | 0 | amount == stated % | none in this pack | (rule kept for the next pack) | A5 |
| per-diem or case rate | 184 | The raw description, plan or methodology says per diem / half day / case rate | Children's `d989bdd477aa….json` `standard_charge_information[3666].standard_charges[0].payers_information[9]`: `"description":"HC PER DIEM PAIN TREATMENT","code_information":[…{"code":"99215","type":"CPT"}]`, $2,527.45 vs peer median $33.07 (76x). BMC South, CHA, BMC Brighton, BMC: CSV rows with methodology `case rate` | normalize: an item whose description or methodology is per diem, half day or case rate is not a CPT line price | A5 |
| wrong plan (Medicaid / CMSP as commercial) | 0 | The plan text names a non-commercial or non-contracted plan | none left in this pack: the engine's lob filter and `masshealth_plan_exclude` already drop them (F2 removes 0) | (rule kept) | A5 |
| facility vs professional mix-up | 48 | The value sits inside 1/3x to 3x of the *other* component's peers, and the two medians are more than 3x apart | Tufts Direct `04e60eab0640…zip` `in_network[515]` 45378 `negotiated_rates[30].negotiated_prices[0]`: `{"negotiated_type":"negotiated","negotiated_rate":"81.06",…,"billing_class":"institutional"}`, provider "BOSTON SPECIALISTS - SOUTH SHO" (one NPI). A doctors' group's "institutional" rate priced as a hospital facility fee (facility peers $4,136, professional peers $141) | A2: an institutional row of a single-NPI / physician TIN is not a facility fee. C3: check both component medians before a facility line uses a TiC row | A2+C3 |
| anesthesia per-unit rate | 180 | 008xx and the same amount on another 008xx code with different CMS base units (00811 = 4, 00812 = 3, 00813 = 5; CY2022 base units file rows 102 to 104) | MGB `INN_COMMERCIAL_HMO_2026-09-27.json.gz` `in_network[572]` 00811 `negotiated_rates[53]`: `"negotiated_rate":"20.9800"`, the same on 00812 and 00813, "SYNERGY SURGICALISTS, LLC" | A2: tag 008xx rates equal across codes as a per-unit conversion factor (all 750 MGB and 21 Fallon network x group x kind sets with two or more 008xx codes are). C3: price as rate x base units, and only for anesthesia groups. The low ones are dermatology, health-center and surgicalist TINs at a $20-$30 default | A2+C3 |
| POS: facility rate at an office | 1,191 | Office site, and every outlying TiC row omits POS 11 | MGB Select HMO `in_network[11071]` 99211 `negotiated_rates[164].negotiated_prices[4]`: `"negotiated_rate":"190.8400",…,"service_code":["20"]` (BIDMC). An urgent-care-only rate read at an office. MGB also lists its lower rate under "every POS except 11", 20 included | engine.yaml `place_of_service`: office sites read POS 11 only (F3a) | C3 |
| POS: office rate at an urgent care | 233 | Urgent care, every outlying row omits POS 20, and the group has a POS-20 row for the line | Tufts Direct `in_network[62]` 99203: `"negotiated_rate":"14.00","service_code":["11"]` "DRX UC Watertown PC" | urgent care reads the POS 20 rate when the group lists one (F3b) | C3 |
| POS: office rate at a hospital | 0 | | the engine already prefers non-office rows | | |
| flat rate | 767 | The group has this exact amount on >= 2 other codes of the family | CHA `…csv` line 313006: `Office/Outpatient Established High Mdm 40 Min,PX-99215,…,CIGNA [50005],CHA HB CIGNA HEALTHCARE CARELINK,9.79,,Fee schedule rate ($9.79).`, the same $9.79 on 99212 to 99215. HPHC: 624 (one rate for 11300 to 11313 or 99212 to 99215 at BWH, NWH, MGH ambulatory TINs) | genuine (one contract rate for several levels): the line shows "one rate for several visit levels", compared as is | C3 note |
| peers are flat rates | 140 | More than 50% of the peer groups are flat across the family | MGB Select HMO 99211 at urgent care: $7.10 (`in_network[11071]` `negotiated_rates[173].negotiated_prices[1]`) vs a peer median of $150.00, the flat urgent-care visit rate of 52% of the peer groups | peer median: count a flat-rate group once per family, or leave it out of per-code medians | C3 |
| several prices, same NPIs and POS (`ambiguous_multi_rate`) | 436 | An in-band row of the same group has the same NPI set and POS list | Aetna PPO 11102 "Metrowest Physician Services", provider group 1833689 (23 NPIs) in `negotiated_rates[146]` at $254.73 and `[147]` at $123.69, same POS list. Tufts Direct CHA 45380 institutional at $328.38 and $2,303.33 | A2 flags same-NPI same-POS duplicates (`ambiguous_multi_rate` already exists in RateRow). C3 shows both, not summed | A2+C3 |
| one TIN, several rate groups (`rate_group_within_tin`) | 5,574 | The group's other rows for the line are inside the band | HPHC Focus `in_network[12207]` 99202, TIN 042312909 "Brigham & Womens Hospital": `negotiated_rates[79]` $45.04 (3 provider refs), `[345]` $76.56, `[878]` $287.72 (283 NPIs). The $45 is a small NPI subset | D6: price the TIN at its largest NPI rate group and list the others by doctor (F5) | C3 |
| children-only site contract | 1,442 | contract_level, and every site of the line is `children_only` | BCBS BHP `in_network[6993]` 20610: `"negotiated_rate":"471.14","service_code":["11"]` "THE CHILDRENS HOSPITAL CORP": 3.45x its peers over 39 other codes | X2 peers: a children-only site is its own kind (F4) | C3 |
| contract level (genuine variation) | 711 | The group is at >= 2x (or <= 0.5x) its peers, median over >= 5 other codes, same network and kind | Dana-Farber `ae1fb1fa761f….json` `standard_charge_information[8429].standard_charges[0].payers_information[1]`: `{"payer_name":"Mgbhp","plan_name":"Commercial & Qualified Hmo","methodology":"fee schedule","standard_charge_dollar":13.05}` (76881; 0.17x over 5 other codes). UHC's "Unknown"-named TINs, NWH under HPHC | none: a real contract. Shown with the evidence | - |
| unexplained | 201 | none of the above | e.g. Tufts Direct BMC 73221 institutional $4,954.53 vs $459.28. BID-Milton UHC 88305 "Tissue exam by pathologist" `"standard_charge_dollar":14.8` vs $156.46 | manual review (by source: childrens_mrf 46, MGB Select 20, nebh_mrf 16, cha_mrf 15, UHC files 44, bid_milton 11, bmc 10, bmc_brighton 8; by line: 123 hospital facility, 38 hospital professional, 28 office, 12 urgent care) | O / Austin |

## Fix simulation

Each fix is applied on top of the ones before it, and the outliers are recounted with the peers
recomputed (`fixes.py`). "Backtest" is the pooled same-kind share more than 2x off.

| Step | Rule (owner) | Measured | Outliers | Removed | Backtest >2x off |
|---|---|---:|---:|---:|---:|
| base | as packed | 212,544 | 11,125 | | 8.28% |
| F1 | drop placeholders (<= $1, >= $99,999) and chargemaster-as-rate (A5/A2) | 212,310 | 11,089 | 36 | 8.24% |
| F2 | hospital plan hygiene (A5) | 212,310 | 11,089 | 0 | 8.24% |
| F3a | office sites price at POS 11 only (C3 engine.yaml) | 212,310 | 9,767 | 1,322 | 8.22% |
| F3b | urgent care prices at POS 20 when the group lists it (C3) | 211,063 | 8,292 | 1,475 | 7.83% |
| F4 | children-only sites are their own peer kind (C3) | 203,619 | 6,196 | 2,096 | 6.41% |
| F5 | one TIN with several rate groups: price at the largest NPI group (C3, D6) | 203,619 | **2,954** | 3,242 | 8.93% |

What these numbers mean:

* F4 removes some outliers by leaving them unmeasured. 7,444 children-only lines have fewer than
  5 pediatric peers, so they become a Gap, not a number.
* F5 narrows each line to one rate group. That removes range-end outliers, but it moves the
  group's median, so the >2x share rises (6.41% to 8.93%).
* F5 needs the NPI count of a packed row. A packed row with more than 25 NPIs carries none, so
  those rows tie, and 676 `rate_group_within_tin` outliers survive F5.

The 2,954 that remain, by cause:

| Cause | Outliers left |
|---|---:|
| contract_level | 1,149 |
| rate_group_within_tin | 676 |
| ambiguous_multi_rate | 389 |
| flat_rate | 287 |
| unexplained | 172 |
| anesthesia_per_unit | 159 |
| peers_flat_rate | 106 |
| facility_professional_mixup | 15 |
| not_dollars | 1 |

Of these, 172 are unexplained. The rest have a cause and need the line to say so: P8 already holds
them out of the sum as "price looks unusual, being checked".

## Backtest: which X2 peer mode

The method: leave one billing group out, predict its price (the median of its rows) from the other
groups of the same peer key, and compare. A prediction needs >= 5 groups (P5).
`same_system_then_kind` uses groups that share a `system_id` when there are >= 3 of them, and
falls back to `same_kind` otherwise. MdAPE is the median absolute percentage error.

Base pack:

| Kind | Lines | Coverage | same_kind MdAPE / >2x off / inside p25-p75 | same_system_then_kind MdAPE / >2x off / inside p25-p75 |
|---|---:|---:|---|---|
| hospital_outpatient | 49,643 | 92.3% | 18.2% / 9.9% / 48.4% | **16.1% / 9.6%** / 46.7% |
| office | 145,369 | 100.0% | 15.1% / 7.5% / 56.7% | **12.7% / 5.8% / 58.2%** |
| urgent_care | 25,058 | 85.5% | 22.2% / 10.3% / 48.2% | 22.2% / 10.4% / 48.2% |
| asc | 1,665 | 0% | no peers | no peers |

The two modes differ only on the lines where system peers exist:

| Kind | Lines with system peers | same_kind MdAPE / >2x off | same_system MdAPE / >2x off |
|---|---:|---|---|
| office | 51,867 | 19.8% / 11.0% | **10.2% / 6.4%** |
| hospital_outpatient | 20,360 | 19.1% / 7.8% | **14.8% / 6.9%** |
| urgent_care | 152 | 13.6% / 8.6% | 0.0% / 9.2% (too few to judge) |

After fixes F1 to F5, same_system still wins on office MdAPE (8.1% vs 16.4%) and hospital MdAPE
(14.2% vs 15.5%). The >2x shares are then about equal: office 7.8% vs 7.3%, hospital 10.3% vs
10.4%.

**Recommendation: C3 should default to `same_system_then_kind`.** It halves the error where a
system has peers, and it gives the same answer as `same_kind` everywhere else, because it falls
back to it. Its share more than 2x off is about the same (after the fixes, office 7.8% vs 7.3%).
This matches Austin's "估计价格也是要从一样的医院体系".

The cost: on hospital lines its p25-p75 band holds the true price less often (43.7% vs 47.6%),
because system peers are fewer and tighter. The band P5 shows should still come from at least 5
groups.

ASCs never reach 5 peer groups, so an ASC estimate is always a Gap until more ASCs are linked.

## Needs from other streams

* **C3 (engine)**:
  * F3a: `engine.yaml place_of_service`: split `office_visit` so office sites read `["11"]`, and
    urgent care reads `["20"]` first, then `["11"]` (F3b).
  * F4: children-only sites are their own peer kind.
  * F5 / D6: one TIN with several rate groups is priced at its largest NPI group, the rest by
    doctor.
  * Flat-rate groups count once per family in a peer median.
  * Default `same_system_then_kind`.
  * Compare per network, not per pooled product: product level has 8,302 outliers vs 11,125 at
    network level on half the lines.
  * Anesthesia: MGB and Fallon 008xx rates are per unit. Multiply by base units, and only for
    anesthesia groups.
* **A5 (hospital ETL)**:
  * `not_dollars`: a stated dollar under 1% of the row's gross.
  * `chargemaster_as_rate`: amount == gross. Tufts writes "No contract line matched".
  * Per-diem, half-day and case-rate items carry CPT codes (Children's "HC PER DIEM PAIN
    TREATMENT" -> 99215). Exclude them from CPT line prices.
* **A2 (TiC ETL)**:
  * `billing_class: institutional` rows on a single-NPI physician TIN.
  * Same-NPI same-POS duplicate prices (Aetna, HPHC, Tufts).
  * Per-unit anesthesia.
  * MGB ASO (`tic_mgb_hp_mgb_aso`) has no product, so it joins every MGB product.
  * Keep the raw `.json.gz`, or a byte-range excerpt per priced item, so a TiC quote can be
    re-checked against the raw file and not only A2's staged copy.

## A7 re-run (wave 2 round C6, 2026-10-25)

Three changes to `app/audit` (tests in `tests/audit/test_audit.py`):

* **Distinct contracts.** A payer copies one contract into each of its network files (HPHC: up
  to 15), and the audit's line is per network, so one contract was counted once per file. A
  contract is now payer + billing group + code + the outlying amount (`contract_key`).
  `summary.json` `distinct` (and `residual_after_fixes.distinct`) counts outliers and unexplained
  as rows and as contracts; `outliers.csv` gets `contract_key`, `contract_lines`,
  `first_of_contract` (filter on it to read each contract once).
* **Cause `flat_visit_rate`**, tested before `facility_professional_mixup`: the group has the
  outlying amount, for the same payer, network and kind, on a visit code (E/M 99202-99215 or
  S9083) and on a non-visit code (visit add-ons 99051 / S9088 count as neither), >= 3 codes in
  all, TiC rows only. Tufts Direct pays ConvenientMD $125 on 99203 / 99204 / 99213 / 99214 / 81003
  / 81025 (`tic_tufts_direct_nonsub_group:04e60eab0640:7629`, 81003 at 34.7x its peers): one
  amount per visit, not a $125 urinalysis. Hospital files are left out: a file is one group of
  thousands of items, and equal amounts there were chance or a percent of one chargemaster price
  (CHA Cigna, 58.3% of $195 on 99213 / 97161 / 97162).
* **Citation.** The anesthesia base units (00811 = 4, 00812 = 3, 00813 = 5) are from the CMS
  CY2022 base-units file (`cms_anes_base_units_cy2022`, rows 102-104), the newest CMS posts. RVU26D
  `ANES2026.csv` holds the 2026 conversion factors, not base units.

Runs (each with `--sites data/sites/sites.yaml` and its own data root):

| | outliers: rows / contracts | unexplained: rows / contracts | flat_visit_rate: rows / contracts | after fixes F1-F5: outliers / unexplained (rows) |
|---|---|---|---|---|
| A6 pack, A6 rules (A6's run) | 23,726 / 4,947 | 727 / 354 | - | 5,693 / 901 |
| A6 pack, A7 rules | 23,726 / 4,947 | 717 / 350 | 23 / 17 | 5,693 / 891 (2,018 / 305 contracts) |
| A7 pack, A7 rules | 24,344 / 5,046 | 729 / 362 | 28 / 22 | 5,780 / 897 (2,070 / 311 contracts) |
| A7 pack without 99281-99285 | 23,726 / 4,947 | 716 / 349 | 27 | |

* The dedupe is the big change in what a person has to read: 23,726 outlier rows are 4,947
  contracts, and 727 unexplained rows are 354.
* `flat_visit_rate` moves 10 rows out of unexplained on the A6 pack (727 to 717); the other 13 of
  its 23 rows were flat_rate (5), contract_level (5) or peers_flat_rate (3) before. All 28 on the A7 pack are in the three Tufts Direct files: ConvenientMD (6), Urgent Care
  Med Assoc (2) and Health Express (2) on 81003 / 81025, Boston Medical Center's $431.24 on
  visits, X-rays, ultrasound and PT (14), Winchester Hospital (4).
* The ED reference codes add 618 outlier rows (99 contracts), 13 of them unexplained. 433 are
  `rate_group_within_tin` and 100 `facility_professional_mixup`. The audit builds lines for every
  packed code at every site, so it also measures ED professional fees at office and urgent-care
  TINs (380 of the 618), which the app never shows: the ER reference is read per hospital.
* The A7 rules on the A6 pack change no line or peer, only causes: the outlier counts are equal.

## Limits

* **The TiC raw files are not on disk.** `a2-tic/data/raw/tic/*` holds only `*.fetch.json` and
  `*.headers`, and `*.json.gz` / `*.zip` are gone after staging. A TiC quote is A2's staged copy of
  the raw `negotiated_prices` object: `negotiated_rate` is kept as the raw JSON text, and every one
  matched the pack amount. It comes with the item's byte span in the inflated JSON and the file's
  sha256, so a re-download can be checked. I did not download anything: a download needs approval.
* The peer set is computed over the sites the registry links. A TIN that no site links is not a
  peer.
* The hospital radiology groups (`radiology_groups.yaml`) are not added to -26 lines (a few TINs).
* The causes are tests, not proofs. "contract_level" says only that the group is consistently far
  from its peers on >= 5 codes. "unexplained" rows need a person.
