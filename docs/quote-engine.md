# Quote engine (streams C and C2, wave 2)

The P1 slice grown into the real engine: every care path in `data/care_paths/paths/` x every payment in
the contract (each TiC payer and network A2 loaded, cash, Medicare, MassHealth) x every quotable site in
the registry. The backend is one small FastAPI app (`app.server`) with no database and no login (D19).

## Run

```bash
cd backend

# 1. tests (no database; the quote tests read the committed extract)
uv run --frozen --extra dev pytest -q -p no:cacheprovider

# 2. the app on the committed extract (7,791 real rows, no env vars)
uv run --frozen uvicorn app.server:app --host 127.0.0.1 --port 8100

# 3. a real pack (hospital build + TiC + fee schedules; CARECOST_DATA_DIR = the data root), then the app on it
uv run --frozen --extra etl python -m app.quote.pack \
  --hospital-build "$CARECOST_DATA_DIR"/build/20261024-336340ed \
  --tic-root "$CARECOST_DATA_DIR"/intermediate/tic \
  --gov-root "$CARECOST_DATA_DIR"/intermediate/gov \
  --out ../data/build/quote_pack.sqlite
CARECOST_QUOTE_PACK=../data/build/quote_pack.sqlite \
  uv run --frozen uvicorn app.server:app --host 127.0.0.1 --port 8100

# 4. latency against the running server
uv run --frozen python -m app.quote.bench --url http://127.0.0.1:8100 -n 200

# 5. regenerate the golden fixtures + extract from a real pack (step 3)
uv run --frozen python -m app.quote.fixtures_gen --pack ../data/build/quote_pack.sqlite --as-of 2026-10-25
```

Tests need `openpyxl` for A3's `tests/sites/test_sites_sources.py`, which is not declared in
`pyproject.toml` yet; until it is, run `uv run --frozen --extra dev --with openpyxl pytest -q -p no:cacheprovider`.

Env vars: `CARECOST_QUOTE_PACK` (runtime pack; default = the committed extract), `CARECOST_SITES_PATH`
(site registry; default A3's `data/sites/sites.yaml`, 208 sites; `contracts/fixtures/sites.json` is
the 6-site test registry),
`CARECOST_CORS_ORIGINS`. Docker: `docker build -t carecost-api .` bakes `data/`, `content/`, `contracts/`
and `data/build/quote_pack.sqlite` (built from the extract when absent). CMD is uvicorn only.

## Routes (`app.server`)

| Route | What |
|---|---|
| `POST /api/quote` | `QuoteRequest` -> `QuoteResponse` (validated once, no `response_model`) |
| `GET /api/catalog` | D3 skip-AI browse: every care path and service (built from the care paths) |
| `GET /api/catalog/paths`, `GET /api/catalog/paths/{id}/services` | the two picker steps; quote the chosen service with `service_codes` |
| `GET /api/our-data` | every loaded source with both freshness sides (D18) |
| `GET /api/health` | rows per source, build id, sites, care paths |
| `app.chat.api.router` | mounted at `/api` (the Chat stream fills it) |

## Files

| File | What |
|---|---|
| `backend/app/quote/store.py` | the runtime format: one SQLite pack (stdlib), loaded once into in-memory dicts; strings dictionary-encoded; extract <-> pack |
| `backend/app/quote/pack.py` | writes the pack from the hospital build, TiC intermediates and fee-schedule rows (pyarrow, ETL side) |
| `backend/app/quote/registry.py` | sites (env path, `Site` contract), payment -> TiC networks, visit-code map, rules |
| `backend/app/quote/engine.py` | steps -> codes -> rows -> lines -> `QuoteResponse` |
| `backend/app/quote/catalog.py` | `Catalog` from the care paths |
| `data/quote/engine.yaml` | every pricing rule we chose (place of service, PC/TC, D20 threshold, ladder limits, you-pay) |
| `backend/app/server.py` | the one app factory |

## How a line is priced

Hospital outpatient / ASC sites bill a facility line plus a doctor line (imaging and pathology: the
reading, modifier 26; therapy: facility only; anesthesia: doctor only). Office sites bill one global line.

Facility side: the hospital's own file (stated dollar, else %-derived dollar; both and far apart =
`conflict`), then the insurer's TiC facility rows for the hospital's TIN (D20 cross-check, P1 #10);
Medicare / MassHealth: the fee schedule (OPPS / ASC / MassHealth, `not_loaded` until A3) and the
hospital file's own Medicare / MassHealth row. A hospital clinic visit also looks up G0463; G0463 is not
in the ETL code list, so it is `not_loaded` when nothing else is found (P9).

Doctor side (plan §2.4, D5, D6): rung 2 the group's TiC rate at the site's TINs (by NPI when every priced
group's NPIs are known, at most 20, and prices differ); rung 3 the hospital file's professional row;
rung 6 Medicare x the group's own median multiple over >= 5 codes (an estimate: in the total,
`includes_estimate`); rung 7 Medicare as a reference (not summed); then `percent_only` / `not_published`.
Medicare: rung 5. MassHealth: rung 4, else rung 7. Cash: `no_source` for doctor fees; an office site's
own posted self-pay page (`posted_<site id>`, `clinic_posted`) or `not_loaded` when we have none.

Imaging reads (Austin 2026-10-24, P1 #6): a modifier-26 line uses the group's TiC rate at any place of
service. CMS: "For the professional component (PC) of diagnostic tests, the facility and nonfacility
payment rates are the same – irrespective of the POS code on the claim." (Medicare Claims Processing
Manual, Pub. 100-04, ch. 12, §20.4.2, https://www.cms.gov/Regulations-and-Guidance/Guidance/Manuals/downloads/clm104c12.pdf).
The 2026 RVU file agrees: 73030-26 has PE RVU 0.08 in both columns. Mount Auburn's groups under BCBS HMO
Blue FI now give 73030-26 $12.04-$17.33, 76881-26 $82.07, 73221-26 $120.81 (HMFP only).

## P1 problems tagged C: resolution

| # | Problem | Resolution |
|---|---|---|
| 1 | TiC `row_ref` not unique | `Provenance.row_id` (RateRow.row_id), required on insurer_tic numbers |
| 2 | a range has one Provenance | `Money.prov_high`, required exactly when low < high, same kind and payer; its source must be in `sources` (so the self-insured HMO Blue file is now cited) |
| 3 | network unknown | `Registry.networks_for(payer, product, network)` from `tic_networks.yaml`; no network = every file of the product into one range, both ends cited; a named network narrows it |
| 5 | which group is the site's | the range across the site's TINs; D6 by-NPI when known and different |
| 8 | cash price wears a payer id | `RateRow.provenance(basis)` and the store's `prov()` set `payer_id` only for negotiated rates |
| 9 | site with an unloaded price source | `SiteSummary.price_source_id: null`; its lines are `not_loaded` |
| 10 | TiC facility rows unused | read for hospital TINs, D20 conflict rule against the hospital file |
| 11 | runtime needed pyarrow | one SQLite pack read with stdlib `sqlite3`; a test asserts `import app.server` loads no pyarrow |
| 13 | no copy keys on a quote | `QuoteResponse.copy_keys` = both D33 keys exactly when `care_path` is set |
| 15 | referral priced at the specialist site | `ReceiptLine.at = your_primary_care`: priced over the registry's primary care offices (none yet: `not_loaded`); Medicare = PFS office rate |
| 19 | fixture test used the base tier | the engine and the test both apply `tier_modifiers` for the request's answers |
| 6 | imaging reads not found | Austin's ruling above |

## Numbers (Austin's Mac, 2026-10-24)

* Pack from real data: 1,531,519 rows (24,605 hospital before the modifier filter, 2.37 M TiC rows ->
  1.53 M kept with modifiers none / 26 / TC), 50 sources, 23,408 small TiC groups with NPIs, 172 MB, 19 s.
* Startup with the fixture registry (6 sites, its TINs): 97,807 rows, 0.72 s, max RSS 142 MB. With every
  TiC row (tins filter off, what a registry linking every Boston TIN would load): 1,531,519 rows, 5.9 s,
  max RSS 1,117 MB. Method: `resource.getrusage(...).ru_maxrss` after `load_pack` + `Engine(...)`.
* Latency (`python -m app.quote.bench -n 200`, uvicorn 1 worker, real pack, gzip, keep-alive, 10 warm-up):
  BCBS HMO shoulder (6 sites) p50 6.4 ms, p95 7.0 ms, 22 KB gzip / 270 KB raw; cash p50 4.7 ms, p95 5.4 ms;
  8 threads, new connection each: 163 quotes/s, p50 49.6 ms, p95 63.1 ms.

## Known limits

* Rung 6 can estimate a code the site may not offer (AFC physical therapy): there is no offered-services
  list yet (P1 #14, A3).
* Response size and full-TiC memory: addressed in C2 (below).

## C2: A3's fee schedules and the 208-site registry

| Brief item | What the engine does now |
|---|---|
| Pack inputs | `--gov-root` reads A3's `LATEST.json` (one RateRow parquet and manifest per source, freshness from the manifest). Row counts in the pack per source kind: hospital_mrf 16,053, insurer_tic 1,178,898 (aggregated from 1,518,081 kept rows of 2,374,165 read), medicare_pfs 296 (RVU26D + anesthesia), medicare_opps 45, medicare_asc 26, masshealth_fs 133 (only the codes a quote can look up). |
| Sites | default `data/sites/sites.yaml`. TiC is joined by `tins` + `tin_npis` + `type_2_npis`, and by `census_id` <-> `tic_site_ids` (the pack's `census_tins`: 97 extra TINs on 54 sites, and a linked TIN's rows count only when they name the site). `children_only` sites are quoted only when `site_ids` names them. `offered` is positive evidence only: no evidence = `availability: "unknown"`, never `not_offered`. |
| Fee schedules | `RateRow.place_of_service` (`non_facility` / `facility` / None) replaces reading `plan_raw` (older A3 parquet: derived from `plan_raw` on load). A fee-schedule number is basis `fee_schedule`, no payer (`Money` rejects one with a payer), method `computed_fee_schedule` for the PFS and `stated` for OPPS / ASC / MassHealth (A3's split). The PFS locality follows the site's county (26LOCCO.csv line 84: 01 = Middlesex, Norfolk, Suffolk; Brockton, Lynn and Saugus are 99). Medicare facility fee: the hospital file's own Medicare row, else OPPS (hospital) or ASC (surgery center), national unadjusted, with `price_notes: ["price.national_unadjusted"]`; a clinic visit looks up G0463 ($136.02) and the line lists it. MassHealth: 316 / 317 / 318 price the doctor's side (rung 4); the hospital outpatient payment (APAD) is not loaded. |
| MassHealth plans | hospital rows whose plan names MassHealth Limited / CMSP, out-of-state Medicaid or dental are never used for `masshealth` (`engine.yaml masshealth_plan_exclude`). Tufts' only MassHealth 73221 row is `HB XR MEDICAID LIMITED CMSP 100%` at the $1,631 gross, so Tufts' MassHealth facility fee is now `not_loaded`. |
| Radiology reads | a -26 line at a hospital uses `radiology_groups.yaml`'s TINs first, the site's own groups when they have no row. Mount Auburn's Schatzki Associates (042482067) and NEB Radiology (043034933) have no row in any loaded TiC file, so Mount Auburn still reads $12.04-$17.33 / $82.07 / $120.81 from its own groups. |
| Data-quality notices | `SiteSummary.data_notices` (BIDMC: content changed, date unchanged) on every site priced by the named file. |
| Scale | `QuoteRequest.near`, `max_sites` (default 12, max 50), `site_ids`. With `near`: the closest `max_sites`. Without: every eligible site is priced and the best `max_sites` (I7) come back, ranked again inside that set. |
| Catalog | a service listed under a path (`/api/catalog/paths/{id}/services`) uses that path's step names; the global list uses the code's neutral description when paths name it differently. |
| `missing` (I7) | certain / likely, non-AI lines with no number that counts (a gap, a conflict, a repeating unit, a rung-7/8 reference) + steps another site lists. |

Numbers (Austin's Mac, 2026-10-25, full real data, registry of 208 sites):

* Pack: 1,195,451 rows, 62 sources, 136 MB (was 1,534,134 rows, 172 MB); 970,356 packed TiC rows carry NPIs for D6.
* Startup max RSS (`resource.getrusage` after `load_pack` + `Engine`): 208-site registry 611 MB, 1,047,791 rows
  (before: 882 MB, 1,240,695 rows); every TiC row 689 MB (before 1,122 MB). Server process RSS after startup: 605 MB.
* `python -m app.quote.bench -n 200` (uvicorn, 1 worker, gzip, keep-alive): BCBS HMO shoulder, 12 sites near
  Harvard Square, p50 8.7 ms, p95 9.0 ms, 323,267 B raw / 20,987 B gzip; cash p50 5.2 ms, p95 5.7 ms,
  257,431 B / 14,870 B; BCBS without `near` (every site priced) p50 38.1 ms, p95 38.9 ms; 8 threads,
  new connection each: 115 quotes/s, p50 63.7 ms, p95 141.4 ms.

## C3: the engine fixed at the source (wave-2 review R1-R12, Austin's rulings P1-P9)

| Rule | Where | What |
|---|---|---|
| Offer evidence (R1, P6) | `engine.offers_code`, `_item_avail` | A step is offered only by the site's own hospital file, its (or its chain's) posted price, a `sites.yaml offered` entry, or agreed / austin_reviewed site facts (`app/quote/facts.py`, X1). A TiC row is never evidence: `availability: unknown`, `availability_reason: insurer_lists_rate`. Generic `imaging` covers X-rays only. |
| Summed (R2) | `_finish` | `in_total` needs `availability == offered` and not a whole-line unusual price. |
| Admission (R8) | `_admits` | Entry visit (layer 1) or core procedure (layer-2 certain/likely procedure) by evidence, else `admission_step_kinds` by kind. |
| TIN roles (R3) | `app/quote/tin_roles.py`, `data/quote/tin_roles.yaml` | An ASC's own TIN prices the facility line only; a hospital TIN follows the row's billing class. |
| Peer estimate (R4, P5, X2) | `_peers`, `_estimate` | Same code, modifier, component, payer, **network file**, kind (urgent care by site type, else by effective billing type), children-only apart; one value per billing group; p25-p75 of >= 5 groups per network, spanning networks when none is named; both ends cited (`estimate_peer_range`). Mode `same_system_then_kind` (O backtest). Rung 6 = this estimate; the Medicare multiple is deleted. |
| Unusual (R17, P8) | `_gate` | Each row against its own network's peer median: outside 1/3x-3x is set aside; all rows outside = `unusual.whole_line`, not summed. Exception (Austin 2026-10-25): the group is >= 2x / <= 0.5x its peers on >= 5 other codes (`data/quote/contract_levels.yaml`, `python -m app.quote.contract_levels`): summed, `price.group_consistently_higher/lower`. |
| Steps, missing, ranking (R5, P1, P3, P4) | `_steps`, `_step_pool`, `_totals` | `SiteQuote.steps` per step (map); a step not offered shows the p25-p75 at sites that do (`figure: elsewhere`); `missing` per step over every admitted site; `comparable` = own medians + estimates and elsewhere steps at the peer median. With `near` or `site_ids`: rank (missing, comparable, distance). |
| No location (R6, P7) | `quote` | Every admitted site, `ordering: kind_then_distance` from Boston City Hall, receipts for the first `full_receipts`. |
| Chains (R12) | `chains:` | AFC's posted page prices every AFC (`chain_price_from`); `chain_spreads` lists > 1.5x within a chain. |
| Unknown billing (R7, P9) | `effective_billing` | Priced as a hospital clinic; `might_add` for possible steps. |
| Anesthesia | `_anesthesia_units`, `_anesthesia_time` | A per-unit 008xx rate (same amount on codes with different base units) x base units, anesthesia groups only; "with typical time" from A5's `data/etl/physician_time.yaml`. |
| Office POS (O F3a) | `_pos` | Offices read POS 11 rows only. |
| Crashes / fallbacks (R10, R11) | `store.valid_npi`, `load_from_env`, `Dockerfile`, `/api/health` | Placeholder NPIs dropped at pack and load; no extract fallback; `CARECOST_ALLOW_EXTRACT=1` for tests/dev; health reports build, rows by source/kind, stale / late sources and the ETL's refresh failures (carried in the pack). |

Numbers (A5 pack `a5.sqlite`, 1,812,636 rows; in-process, Austin's Mac): BCBS HMO shoulder with no
location: 133 sites, 12 receipts, 963,417 B raw / 60,408 B gzip, p50 63 ms, p95 175 ms (HTTP via
TestClient: p50 69 ms, p95 95 ms). Near Harvard Square (12 sites): 584,133 B / 45,244 B, p50 17 ms.

## C4b: what a person reads first (Austin 2026-10-25), aggregation fixes

**Headline range** (`SiteQuote.headline_range`). Austin: the range covers the **certain and likely**
steps only. Low = the sum of their lows, high = the sum of their highs; each step's figure is this
site's own price (or estimate), or the step's elsewhere range where this site has no evidence it
does it. `includes` names the steps counted on top of the first visit ("includes: urine test").
Possible steps are never in it: `may_also_order` lists each with its own figure and plain purpose.
Three subtotals for the breakdown: `visit_only` (the first visit, every bill), `with_likely` (= the
headline), `with_possible` (+ possible steps; of one care-path `exclusive_group`, e.g. belly
ultrasound / belly CT, only the dearest counts, the other is in `alternatives`). The contract checks
every subtotal equals the visit plus its steps' figures. Self-pay at a hospital clinic with no
public doctor fee: `from_only` + `headline.doctor_bills_separately` ("from $203").

**Entry options** (`CarePath.entry_options`, `QuoteResponse.options`, `SiteQuote.option_id`). A
path may say where to go first: rash A = urgent care / primary care (`visit`), B = skin doctor
(`skin_doctor_visit`); stomach A = urgent care, B = GI listed with `priced: false`. A site gets
the first option whose kind, site type or service area it matches; the other options' first visits
are not steps there (AFC no longer shows its $135.61 visit twice). Peers and elsewhere ranges still
come from the whole path pool. Per option: subtotal spans (min low .. max high over its sites) and
`cheapest_site_id` (lowest headline low, ties nearest). Ordering `option_then_distance` (default)
or `option_then_price` (`order_by: price`); with `near`, `max_sites` per option; without, the first
`full_receipts` of each option carry receipts.

**Aggregation**: (a) CMS PC/TC indicator (`data/quote/pctc.yaml`, `python -m app.quote.pctc
--rvu-zip <RVU26D zip>`): 3/4/7/9 = no doctor line at a hospital (clinical labs); (b) above; (c)
notice `hmo_referral_for_specialist` when Q14 may need a referral and a specialist option has sites;
(d) no rung 7 / Medicare number for a non-Medicare payment (a gap stays a gap, the peer estimate may
fill it); (e) `availability_reason: price_file_lists_rate` for non-insurance payments.

**A6 TiC flags** (`flags.parquet` -> pack table `row_flags`, `RateStore.flags`, extract column
`flags`): `institutional_on_physician_npi` rows never price a line; `anesthesia_per_unit` goes to the
per-unit rule even without a twin; `same_npi_pos_multi_rate` keeps the range with
`price.several_rates_same_doctors`. **Flat visit rate**: a non-visit TiC row whose group has the
same amount on a visit code in the same file is the visit's amount: the line keeps it, is never
gated or summed (`price.flat_visit_rate`, excluded `flat_visit_rate`), its step adds $0.

**ER reference** (`QuoteResponse.er_reference`, never ranked): the 3 nearest hospitals' ED levels
3-5 (99283-99285), facility + doctor, under the payment; `not_loaded` until the pack has the codes.

New copy keys for the frontend (all `review: true`): `headline.doctor_bills_separately`,
`price.flat_visit_rate`, `price.several_rates_same_doctors`, `total.excluded.flat_visit_rate`,
`notice.hmo_referral_for_specialist`, `er.visit_alone_costs_more`, and the availability wording for
`price_file_lists_rate`.
