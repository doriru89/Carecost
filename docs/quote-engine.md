# Quote engine (stream C, wave 2)

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

# 3. a real pack, then the app on it
uv run --frozen --extra etl python -m app.quote.pack \
  --hospital-build /Users/austin/carecost-wt/a1-refresh/data/build/20261024-10d8a893 \
  --tic-root /Users/austin/carecost-wt/a2-tic/data/intermediate/tic \
  --gov-rows ../contracts/fixtures/gov_pfs_extract.csv \
  --gov-sources ../contracts/fixtures/gov_pfs_extract.sources.yaml \
  --out ../data/build/quote_pack.sqlite
CARECOST_QUOTE_PACK=../data/build/quote_pack.sqlite \
  uv run --frozen uvicorn app.server:app --host 127.0.0.1 --port 8100

# 4. latency against the running server
uv run --frozen python -m app.quote.bench --url http://127.0.0.1:8100 -n 200

# 5. regenerate the golden fixtures + extract from a real pack (step 3)
uv run --frozen python -m app.quote.fixtures_gen --pack ../data/build/quote_pack.sqlite --as-of 2026-10-24

# 6. the tiny Medicare PFS extract (until A3's PFS reader lands)
uv run --frozen python tests/quote/make_pfs_extract.py \
  --pfs /Users/austin/carecost/data/raw/government/cms_pfs/PPRRVU2026_Jan_nonQPP.csv \
  --gpci /Users/austin/carecost/data/raw/government/cms_pfs/GPCI2026.csv
```

Env vars: `CARECOST_QUOTE_PACK` (runtime pack; default = the committed extract), `CARECOST_SITES_PATH`
(site registry; default `contracts/fixtures/sites.json`; A3's `data/sites/sites.yaml` drops in),
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
* Response size grows with sites (270 KB raw for 6 sites); a 273-site registry needs a site filter or a
  summary-first response.
* Full-TiC memory (1.1 GB) is mostly per-row Python objects; if the registry links every TIN, aggregate
  TiC rows per (network, TIN, code, POS) at pack time.
