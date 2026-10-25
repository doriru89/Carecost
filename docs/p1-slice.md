# P1 thin real slice

> Superseded by `docs/quote-engine.md` (stream C, wave 2): the run commands below (`app.quote.api:app`,
> `p1_slice.yaml`, `slice_data.py`) no longer exist; each problem tagged C has its resolution there.

The narrowest end-to-end path on real data: `shoulder_chronic_clicking_v1` x {BCBS MA HMO, cash} x 3 sites,
one route (`POST /api/quote`), one ugly receipt page. Its job is to hit the integration seams once, before
streams C / D / Chat / A3 start. Those seams are listed below.

## Run it locally

```bash
cd /Users/austin/carecost-wt/p1-slice/backend

# A. API on real local data (pyarrow is needed for the TiC parquet, so use the etl extra)
CARECOST_HOSPITAL_BUILD=/Users/austin/carecost-wt/a1-refresh/data/build/20261024-10d8a893 \
CARECOST_TIC_ROOT=/Users/austin/carecost-wt/a2-tic/data/intermediate/tic \
  uv run --frozen --extra etl uvicorn app.quote.api:app --host 127.0.0.1 --port 8100

# B. or the API on the committed extract (no env vars, no 1 GB data; same numbers)
uv run --frozen uvicorn app.quote.api:app --host 127.0.0.1 --port 8100

# the page (second terminal), then open http://127.0.0.1:5180/
python3 -m http.server 5180 --bind 127.0.0.1 -d ../frontend/p1-slice

# tests (the real-data load test runs only with the two env vars above set)
uv run --frozen --extra dev pytest -q -p no:cacheprovider tests/quote tests/contracts

# latency against the running server
uv run --frozen python -m app.quote.bench --url http://127.0.0.1:8100 -n 200

# regenerate the golden fixtures + the committed extract from real data
uv run --frozen --extra dev python -m app.quote.fixtures_gen \
  --hospital-build /Users/austin/carecost-wt/a1-refresh/data/build/20261024-10d8a893 \
  --tic-root /Users/austin/carecost-wt/a2-tic/data/intermediate/tic --as-of 2026-10-24
```

Raw data is never copied into git. The engine reads it from the paths in `CARECOST_HOSPITAL_BUILD` /
`CARECOST_TIC_ROOT`. Only the ~1,000 rows the two golden quotes look at are committed
(`contracts/fixtures/rate_row_extract.csv`, 1,021 rows, 0.48 MB).

## What is where

| File | What |
|---|---|
| `data/quote/p1_slice.yaml` | scope: care path, 3 site ids, payment -> TiC files, place-of-service rule, modifier 26 for imaging reads, facility-only therapy codes, per-15-minute codes, you-pay copy key |
| `backend/app/quote/slice_data.py` | startup load into in-memory dicts (hospital rows by file+code+payer, cash rows by file+code, TiC rows by file+TIN+code); real build or committed extract |
| `backend/app/quote/engine.py` | steps -> codes -> rows -> `QuoteResponse`, validated once by the contract |
| `backend/app/quote/api.py` | fresh FastAPI app factory, `POST /api/quote`, `GET /api/health`, GZip, CORS for :5180. `app.main` untouched |
| `backend/app/quote/fixtures_gen.py` | writes the golden fixtures + extract from real data, then replays the extract and requires identical output |
| `backend/app/quote/bench.py` | p50/p95 over N real HTTP requests |
| `frontend/p1-slice/index.html` | the receipt page |
| `backend/tests/quote/test_p1_slice.py` | end to end (engine and HTTP) on the extract, startup load, real-data load, freshness per request |

## Data picked

- **Hospital build `20261024-10d8a893`** (a1-refresh), not `20261024-1cb8089d`. Every file in it was downloaded
  from the publisher on 2026-10-24 (D24). In the older build 7 of 12 files were `fetch_method: import`, which
  means old local copies. Its `ok` is false only because Franciscan failed TLS; P1 does not quote Franciscan.
  Freshness fields read from `manifest.json`: `tufts_mrf` last_updated_on 2026-04-01, fetched 2026-10-24;
  `mtauburn_mrf` 2026-04-01 / 2026-10-24. Both are current (late after 2027-04-01; stale on our side after
  2026-11-24).
- **TiC:** `tic_bcbs_ma_hmo_blue_fi` and `_si`, both release 2026-10 (file `last_updated_on` 2026-10-01,
  fetched 2026-10-24). Late after 2026-11-15, stale on our side after 2026-11-24.

## The 3 sites (row counts for the path's 17 codes)

| Site | Type | Why | Rows |
|---|---|---|---|
| Tufts Medical Center | large academic hospital | MGH and Brigham publish almost no BCBS commercial rows for these codes (MGH: only 20610-50 / 20611-50; Brigham the same plus Medicare Advantage), so they would be mostly gaps. Tufts has them | `tufts_mrf`: 3,923 rows, 29 BCBS HMO dollar rows, cash on every row. TiC TIN 043400617: 170 rows per HMO Blue file (97 professional with a dollar amount) |
| Mount Auburn Hospital | community hospital | BCBS HMO and cash in its file, and its doctor groups are in TiC | `mtauburn_mrf`: 77 rows, 14 BCBS HMO dollar rows, 14 cash rows. TiC TINs at 330 Mount Auburn St: 043026897 (99), 820671467 (68), 222768204 (129) per file |
| AFC Urgent Care Watertown | non-hospital urgent care | the only kind of site with real prices that is not a hospital is one in TiC; its TIN is its own | TiC TIN 460903626: 9 rows per file (99203, 99204, 99213, 73030, 20610, 20611, 76881) |

TINs were added to `contracts/fixtures/sites.json`, each with its `tins_source`. Tufts was added as a site.

## What the page shows

For each site, ordered by I7 (completeness band, then price): name, address, billing type, price source; the
**total on top** (a range when a line is a range), `complete` / `missing`, the you-pay copy key and MyBlue link.
Then one row per receipt line: plain name, small technical name + code, **why**, **tier** (left border:
solid / lighter / dashed / warning) and `tier_basis`, the **amount or the Gap** (kind, glossary key, what,
ask, searched file), the **source chip** (source kind + publisher, hover shows file and row_ref), the row_ref,
the list price (never summed), the doctor-fee copy key, and whether it is in the total and why not. Then the
range bar of other insurers for the same X-ray, then **Sources & dates**, each labelled
*Current* / *Late to refresh* (publisher) / *Stale on our side* (us). The not-a-diagnosis key
`copy.not_a_diagnosis` is shown at the top with a placeholder sentence; the copy file belongs to stream D.

## Latency

`python -m app.quote.bench -n 200` against uvicorn (1 worker, real data, loopback, gzip on, keep-alive), each
timed from send to the full body read, after 10 warm-up requests, on Austin's Mac on 2026-10-24:

| Request | p50 | p95 | max | body gzip / raw |
|---|---|---|---|---|
| BCBS HMO (3 sites, 44 lines) | 2.7 ms | 2.9 ms | 3.2 ms | 6.8 KB / 74 KB |
| cash (2 sites) | 1.6 ms | 1.7 ms | 6.0 ms | 4.1 KB / 47 KB |
| 200 BCBS requests over 8 threads, new connection each | 19.6 ms | 25.9 ms | | 394 quotes/s |

Startup: loading 4,950 rate rows from the build and TiC parquet plus building the engine takes 0.43 s; the
committed extract loads in 6 ms.

## Integration problems hit (each with its fix or owner)

1. **TiC `row_ref` is not unique.** One TiC price row applies to every provider group listed with it, so
   `tic_...:123c081435e7:9381` is both AFC's and Mount Auburn Professional Services' $63.58. A hospital line
   with two target codes also gives two rows with one `row_ref`. My first loader keyed rows by `row_ref` and
   silently dropped 97 of Mount Auburn Professional Services' 99 rows. **Fixed in P1:** rows are keyed by
   `source_id:row_id`, and the fixture-number test finds a cited row by `row_ref` + code + modifier + amount.
   **For C / contract:** `Provenance.row_ref` cannot tell which group a TiC number belongs to. Add the group
   (`tic_provider_group_id` or the TIN) to the ref, or a `row_id`.
2. **A Money range has one Provenance.** Doctor fees are ranges across groups and contracts (rung 2), and some
   hospital lines list several rates for one plan (Tufts 97110 HMO: $224.32 to $285.23). `prov` cites the low
   row and the high end is cited nowhere. For the same reason the self-insured HMO Blue file is read but never
   appears in `sources`: it can only ever supply an uncited high end. `sources must be exactly the ones used`
   cannot see it. P1 keeps the range honest with a test (high == the highest row the same lookup finds).
   **For C / contract:** `prov_high`, or a list of row refs on a range.
3. **The person's network is unknown.** `QuoteRequest.network` is null, and BCBS publishes HMO Blue as two files
   (fully insured / self insured). P1 reads both into one range. For the 3 sites' TINs and these codes, the two
   files are identical (0 differing rows), so today the range is not wider for it. **For C:** a payer/product ->
   network registry (it is in `p1_slice.yaml` for now), and a rule for when the files differ.
4. **No site <-> TiC join in the registry.** TiC rows carry census ids (`tic_site_ids` = `GB0166`...), while
   `sites.json` uses its own ids and had empty `tins`. Tufts is in no census row at all (`tic_site_ids` empty). P1
   joins by TIN, as the contract says. The TINs come from the census `clinician_billing_tins_bcbs` (Mount
   Auburn), the census org-NPI match (AFC) and the EIN in the hospital's own price-file name (Tufts).
   **For A3:** sites.yaml must carry `tins` (or the census id) for every quoted site.
5. **Which doctor group is "this site's" is a guess.** At 330 Mount Auburn St, the census lists three groups
   (Mt Auburn Professional Services, Boston Orthopaedic and Spine, HMFP at BIDMC). P1 takes the range across
   all three. **For C:** D6 per-doctor needs a doctor pick; until then the range is right but wide ($80.02 to
   $134.37 for the new-patient visit).
6. **Imaging reads are not found for the right group.** Every X-ray / MRI / ultrasound reading (modifier 26,
   place of service 22) is `not_published` at both hospitals. The groups P1 searched publish -26 only at place
   of service 11, and the radiologists who read hospital images bill under a radiology group TIN that no
   registry links to the site. "Not published" is true for what we searched, but the real gap is our link,
   which is closer to `not_loaded`. **For A3:** add hospital radiology group TINs; **for C:** decide whether a
   POS-11 -26 rate applies at a hospital.
7. **Cash price lives on payer rows in tall CSVs.** Tufts repeats its cash price on every payer row (3,923 rows
   with `discounted_cash`, none `chargemaster`). The fixture test assumed cash = chargemaster rows. **Fixed:**
   the cash index takes any row with `discounted_cash`, deduplicated by (modifier, component, setting, cash,
   gross); the test's cash lookup changed the same way (test change 3).
8. **A cash price is not a payer's.** `RateRow.provenance()` puts the payer id on every payer-row number,
   including the cash price and the gross charge read from that row. P1 sets `payer_id` only for negotiated
   numbers. **For C:** do the same in `RateRow.provenance()` / `to_cell()` (they ignore `discounted_cash` on
   payer rows).
9. **A site whose own price source is not loaded cannot be shown.** AFC under cash: its posted self-pay page is
   not read yet (A3 reader), and `SiteSummary.price_source_id` must name a source with freshness. P1 lists AFC in
   `sites_without_service`, which strictly means "offers none of it". **For C / contract:** allow a site with an
   unloaded price source (a `not_loaded` source entry, or `price_source_id: null`), then every line is
   `not_loaded`.
10. **MRF and TiC disagree on hospital facility fees, and P1 uses only the MRF.** Tufts' file has no BCBS row for
    99203, so the facility part of the new-patient visit is `not_published`, while BCBS's TiC lists Tufts
    facility rates for 99203 ($107.41 to $315.61 across its campus NPIs). **For C:** read TiC facility rows as a
    second source, and use the D20 conflict rule when both exist (none of this was built in P1, so no real
    `conflict` cell exists yet).
11. **Runtime needs pyarrow for TiC.** `pyarrow` is only in the `etl` / `dev` extras; the FastAPI runtime cannot read
    the TiC parquet. Hospital rows come from `rate_row.sqlite` (stdlib). **For C (D1 / P7):** ship one runtime
    format per release (SQLite or JSON for both), or add pyarrow to the image.
12. **No site registry yet.** The API reads `contracts/fixtures/sites.json` (a fixture) as its site list.
    **For A3:** `data/sites/sites.yaml`; C points `SITES_PATH` at it.
13. **`QuoteResponse` has no copy keys.** `copy.not_a_diagnosis` / `copy.when_to_see_a_doctor` exist only in the
    chat contract, but a quote reached from a care path should carry them too (D33). The page shows the key
    statically. **For C / D:** a `copy_keys` field on `QuoteResponse` when `care_path` is set; D writes the copy
    file.
14. **No offered-services list.** Real data cannot say "not offered here". An absence is only "not published"
    (AFC has no TiC rate for MRI). **For A3:** an offered-services field on `Site`; until then `not_offered` +
    `elsewhere` never occurs in real quotes.
15. **The referral step is priced at the specialist site.** The HMO referral visit (99213) happens at a primary
    care office, not at Tufts or AFC, but the path has no "where" for a step. AFC shows `not_published` for it
    (its TIN has 99213 only with modifiers 56 / 78). **For C / clinical:** price layer-0 steps separately, or
    mark them as "at your primary care office".
16. **Mount Auburn's "discounted cash" equals its gross charge** on every line ($527 X-ray, $2,741 MRI). The file
    says so; the receipt shows the cash price and an identical list price. Tufts' cash is 30% below gross.
    **For D:** show "no cash discount listed" when they match.
17. **Tufts' BCBS HMO rate for 99213 equals its gross charge** ($361.00, plan `HB XR BCBSMA HMO TMC`,
    `amount_method: stated`). It is a stated number, so P1 shows it; it is a data-quality flag for the ETL report
    (A1).
18. **Unmapped payer names flood the range bar.** Tufts has 47 distinct payer names for one X-ray; most are not in
    `payer_aliases.yaml`. P1's range bar shows mapped payers only (10 at Tufts) and includes Medicare Advantage
    and MassHealth rows of those payers. **For A1:** alias coverage; **for D:** which lines of business belong on
    the bar.
19. **Tier modifiers vs the fixture test.** The engine applies a path's `tier_modifiers` (and their
    `appropriateness` override for `tier_basis`). `test_quote_lines_match_the_care_path` compares a line with the
    step's base tier and rating, so a request with Q4/Q5/Q6 answers would fail it. The golden requests trigger
    no modifier. **For C:** compare against the modified step.
20. **Freshness is per request, so the engine cannot hold it.** The first engine stored per-request freshness
    on the shared engine object (a race under FastAPI's thread pool). **Fixed:** it is computed per request and
    passed through. `test_freshness_is_computed_per_request` shows the same image turning "stale on our side" on
    2026-12-01.
21. **The golden fixtures cannot show every contract shape any more.** Real data has no percent-only row, by-NPI
    price, not-offered line, late or stale source, or rung 7 for these sites on 2026-10-24. **Fixed:** listed in
    `test_fixtures.py::NOT_IN_REAL_DATA` (the test fails when real data starts covering one). The hand-made
    quotes moved to `backend/tests/contracts/handmade/`, where they stay the mutation base of the negative rule
    tests.

## Test changes (hand-made assumptions the real data contradicts)

1. `test_quote_rules.py`, `test_api_contracts.py`: the negative rule tests mutate the hand-made BCBS / cash
   quotes (now in `tests/contracts/handmade/`), because they need shapes real data lacks (rung 7, by_npi, an AI
   Money line, not_offered, a stale source, the `bcbs_ma_tic_hmo` / `cms_pfs_rvu26a` sources).
   `test_fixtures_are_valid_starting_points` and the I7 property test now run on both the hand-made and the real
   quotes.
2. `test_fixtures.py::test_fixtures_together_cover_the_whole_contract` split in three:
   `test_real_fixtures_cover_what_real_data_can` (real + Medicare cover everything except
   `NOT_IN_REAL_DATA`, exactly), the original union check including the hand-made quotes, and
   `test_real_fixtures_need_no_placeholders`.
3. `test_fixture_numbers_match_the_build`: a cash price is any row with `discounted_cash` (problem 7); a cash price
   or gross charge carries no payer id (problem 8); a Money may be a range, so low must be the cited row and
   high the highest row of the same lookup (problem 2); TiC numbers are checked too (TIN, place of service,
   network), including `not_published` claims against TiC; rows are found by `row_ref` + code + modifier +
   amount (problem 1).
4. `test_fixture_sources_are_registered`: only `cms_pfs_rvu26a` (Medicare) is still unregistered.
5. `test_hospital_files_use_the_365_day_rule`: checks Tufts' 2026-04-01 file instead of MGB's 2026-03-27 file
   (P1 does not quote MGB).
6. `tests/contracts/make_rate_row_extract.py` removed. `python -m app.quote.fixtures_gen` writes the extract,
   which still includes the rows the hand-made Medicare quote cites, so its numbers stay checked.

## Assumptions

- Place of service 22 for hospital doctor fees, 11 for office sites; modifier 26 for hospital imaging reads;
  therapy codes (97161-97163, 97110) have no separate doctor fee at a hospital.
- Only each step's primary code is priced (plus 97110 per 15 minutes). Alternatives (99204, 20611, 76882,
  97162/3) and add-ons (23350, 77002) are not.
- A hospital facility lookup uses BCBS rows whose product is HMO or blank, line of business commercial or
  unknown, no modifier, component facility or unknown.
- `you_pay` for BCBS HMO is `copay_or_deductible` (as in the hand-made fixture).
- J3301 (the AI-suggested drug) is not in `data/etl/codes.yaml`, so its line is `not_loaded`.
