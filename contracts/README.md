# contracts/

Generated JSON Schemas: the seams between the wave-2 streams. Never edit a `*.schema.json` by hand.
Change the pydantic model, regenerate, and commit both. Drift tests fail CI when a committed file is stale.

## Schemas

| Schema | Model (source of truth) | What it is | Produced by | Consumed by |
|---|---|---|---|---|
| `source_kind`, `provenance`, `money`, `gap`, `cell`, `rate_row` | `backend/app/etl/contracts.py` | Where a number came from; Money or a typed Gap; one negotiated-rate fact | ETL (A0/A1, A2 TiC, A3 gov) | quote engine (C), every API schema below |
| `care_path` | `backend/app/care_paths/models.py` | Clinical content: steps, tiers, citations, codes | care paths (B) | quote engine (C), chat (E), catalog |
| `quote_api` | `backend/app/quote/contracts.py` | `QuoteRequest` (payment + care path id *or* manual codes + optional site filter) and `QuoteResponse` (per site: summary + gradient receipt + totals + other-payer range) | quote engine (C) | frontend (D) |
| `chat_api` | `backend/app/chat/contracts.py` | `ChatRequest` (text, payment, unverified email, opaque conversation id, chip answers) and `ChatResponse` (reply union: `red_flag` / `clarify` / `care_paths` / `text` / `ai_paused`, plus budget status) | chat backend (E) | frontend (D) |
| `catalog` | `backend/app/quote/contracts.py` (`Catalog`) | Skip-AI manual picker (D3): services with plain + technical name, codes, care paths | quote engine (C), built from care paths | frontend (D) |
| `site` | `backend/app/sites/contracts.py` | `data/sites/sites.yaml`: coordinates, billing type, booking links (On My Way / Solv / Clockwise / MyChart / Patient Gateway, links only), hours + source, posted cash prices with checked date + URL | gov data + sites (A3) | quote engine (C) |

`quote_api` and `chat_api` hold two roots each (request and response) under `$defs`. The file's top-level
`anyOf` accepts either.

## Rules the contracts enforce (model validators, so the engine cannot break them)

- A price cell is a `Cell` (Money or one of five Gap kinds). Tier `not_in_public_data` holds exactly the
  "no number" Gaps (`not_published`, `not_loaded`, `no_source`). `percent_only` and `conflict` stay in their
  likelihood tier.
- Display tiers (D8 gradient): `certain`, `likely`, `possible`, `not_in_public_data`. A care-path `rare` step
  displays as `possible`.
- `in_total` only for certain/likely, offered, one-off Money lines that are not AI-suggested. Doctor-fee
  rungs 7–8 are reference only. `totals.likely` is exactly the sum of those lines. Every other line is listed
  in `totals.excluded` with a reason. `totals.complete` is false when a certain/likely line is missing.
- Doctor fee: rung 1–8 plus a fixed `fee.*` copy key. Rung 6 carries its multiple, and its Money is
  `estimate_medicare_multiple`. Self-pay has no rung (`fee.self_pay_no_source`). `by_npi` (D6) needs ≥ 2
  different prices; otherwise the line shows a range.
- Freshness has two sides that are never merged (`Freshness` in `backend/app/sites/contracts.py`):
  - (a) Publisher side, `late_to_refresh`: the hospital, insurer, agency or clinic is past its own deadline
    (`last_updated`, `expected_by`, `source_rule`). A hospital MRF is late after 365 days, TiC after 45 days,
    fee schedules at their next annual or quarterly release, and a clinic page 365 days after the date printed
    on it (never, if the page has no date). The data is still shown, labelled "late to refresh".
  - (b) Our side, `stale_on_our_side`: our last successful fetch or check (`fetched_at`) is past our own
    schedule (`our_refresh_due`, `our_rule`): hospitals, TiC and NPPES monthly, sites weekly, fee schedules
    per release. This is our fault and is never worded as the publisher's.
  - We never call a publisher late while we are stale ourselves (validator). Build values with
    `Freshness.compute(...)`, the one implementation of the cadences. `gates.yaml` `warn_after_days` stays an
    internal ETL warning only.
  - Both sides sit on every `SourceChip` (per data point, with `source_id`) and on each site
    (`price_freshness` of the site's own price source, plus the `any_source_late` /
    `any_source_stale_on_our_side` rollups). `DataVersion.sources_behind` lists every flagged source, and the
    notices `late_to_refresh_sources` / `stale_on_our_side_sources` appear exactly when one applies.
    `OurDataResponse` is the contract for a future `/our-data` page that lists every source with both sides.
- No personal data. The quote request has no location: distance is computed in the browser, and
  `ElsewhereOption` carries coordinates so the browser can pick the nearest. The only personal field anywhere
  is the unverified `email` in `ChatRequest` (D2).
- Payer, site and hospital ids are strings, validated against the registries in tests
  (`data/etl/payer_aliases.yaml`, `data/registries/hospitals.yaml`, `data/sites/sites.yaml`). They are never
  closed enums, so adding an insurer or a clinic needs no contract change.
- Chat: `red_flag` and `ai_paused` replies have `llm_called: false`. At most 2 chip questions per turn. Question
  ids come from `questions.yaml`, path ids from the care-path catalog, and dispositions are the 4 in
  `redflags.json`.

## Why plain JSON for chat, not streaming

Every reply is one structured object whose kind is decided by deterministic gates (budget, then red flags)
before any LLM call. The LLM's job is to fill a small validated shape: chip ids, path ids, one or two
sentences. A stream would put unvalidated text on screen before we know whether it is a red flag, a valid
path id or within budget, and that breaks the "nothing unvalidated reaches the user" rule. Plain JSON also
keeps the FastAPI endpoint, the per-IP cost accounting and the provider swap (Gemini free tier in dev, Lava in
prod) simple. The cost is latency. Replies are short (≈1–3 s), so the UI shows a typing indicator. If that
proves too slow, we can stream `TextReply.text` later as an additive change, because the union stays the same.

## Fixtures (`contracts/fixtures/`)

Each file has `"_fixture": true` and `"_schema": "<root model>"`. `_fixture` is not a field in any model, so a
fixture fed to a validator is rejected and can never ship as data. `backend/tests/contracts/test_fixtures.py`
validates each one and checks every id against the registries. It also checks that together they cover every
tier, every Gap kind, a Money range, a per-NPI breakdown, an AI-suggested line, a not-offered line with
"cheapest elsewhere", and a late-to-refresh source both per line and per site.

| Fixture | Shows |
|---|---|
| `quote_request_*` / `quote_*_shoulder` | BCBS HMO, cash and Medicare quotes for chronic shoulder pain with clicking. Mount Auburn, Brigham, Franciscan and AFC Watertown use real rate_row numbers from build `20261024-1cb8089d`. |
| `quote_request_masshealth_manual` | Skip-AI manual pick (D3) with MassHealth |
| `chat_request_first_message`, `chat_red_flag`, `chat_clarify`, `chat_care_paths`, `chat_ai_paused` | Chat request and four reply kinds |
| `catalog` | Built from the 10 care paths in `data/care_paths/paths/` |
| `sites` | Three example `sites.yaml` entries (urgent care with posted prices, On My Way link, hospital outpatient) |

Values that do not exist in loaded data yet are placeholders: BCBS TiC (sha `000…`, group rates from
research-v3/pro-fees.md), posted-page shas, NPIs `0000000001`/`0000000002` (an NPI never starts with 0), and
hand-entered coordinates for the two Watertown clinics, and two freshness examples: the BCBS TiC check on 2026-10-20
(publisher late, we are current) and the AFC page check on 2026-10-10 (we are stale, the page states no date).

## Regenerate / check

```bash
cd backend
uv run python -m app.api_contracts            # quote_api, chat_api, catalog, site + frontend TS types
uv run python -m app.api_contracts --check    # exit 1 if anything is stale
uv run python -m app.etl.contracts            # source_kind, provenance, money, gap, cell, rate_row
uv run python -m app.care_paths.schema_export # care_path
```

From `frontend/`: `npm run contracts:generate`, `npm run contracts:check`, and `npm run typecheck:contracts`.
The last one type-checks `src/generated/contracts/*.ts` together with `src/contracts/exhaustive.ts`. Those
`satisfies Record<Union, …>` maps make a new Gap kind, tier, reply kind or disposition a compile error until
the UI handles it (plan §2.5).

The TypeScript types are generated by a small Python generator in `app/api_contracts.py`, so the frontend
needs no npm dependency for this.

## Sources registry split (`data/etl/sources.d/`)

`load_sources()` reads `data/etl/sources.yaml`, then every `data/etl/sources.d/*.yaml` in name order. Each
stream owns its own file (A2 → `tic.yaml`, A3 → `government.yaml`). A fragment holds
`{version, allowed_domains, sources}`. Its domains are added to the fetch allowlist. A duplicate `source_id`
anywhere fails the load.

`SourceSpec` (`backend/app/etl/config.py`) already covers every format wave 2 registers, so streams add YAML,
not code. `format` names the reader. `_FORMAT_RULES` fixes, per format, the allowed `kind`, `media`,
`container` and `access`:

| format | kind | media | container | access |
|---|---|---|---|---|
| `cms_v3_csv_tall` / `cms_v3_csv_wide` / `cms_v3_json` | `hospital_mrf` (needs `entity_id` + `npis`) | csv / json | zip, plain | download |
| `tic_table_of_contents` | `insurer_tic` (needs `payer_id`) | json | plain, gzip | download |
| `tic_in_network` | `insurer_tic` (needs `payer_id`) | json | gzip, plain | http_range, download |
| `nppes_monthly` | `provider_registry` | csv | zip (`members`: main, pl_pfile, othername_pfile, endpoint_pfile) | download |
| `dph_xlsx` | `facility_registry` | xlsx | plain | download |
| `fhir_provider_directory` | `provider_directory` (needs `payer_id`) | json | plain | paged_api (`filters`) |
| `cms_dataset_csv` / `cms_dataset_api` | `clinician_directory`, `billing_relationship`, `facility_registry`, `utilization`, `plan_benefits` | csv / json | plain, zip / plain | download / paged_api |
| `cms_pfs_rvu`, `cms_pfs_anes` | `medicare_pfs` | csv, xlsx | zip, plain | download |
| `cms_opps_addendum` | `medicare_opps` | csv, xlsx | zip, plain | download |
| `cms_asc_addendum` | `medicare_asc` | csv, xlsx | zip, plain | download |
| `masshealth_fee_schedule` | `masshealth_fs` | pdf, xlsx | plain | download |
| `html_price_page` | `clinic_posted` (needs `entity_id` = sites.yaml id) | html | plain | download |

There are two kind enums. `SourceKind` is price provenance, the kind a `Money` can carry. `ReferenceKind` is
for sources with no consumer price: registries, directories, billing relationships, utilization and plan
benefits. A reference row never becomes a `Money`.

The hospital rate_row pipeline (stage, normalize, build, report) reads only `SourcesFile.rate_row_sources`,
the MRF formats. It skips other formats with a `SKIP` line rather than failing, so a new TiC or government
source never breaks the hospital build. `fetch` also skips `http_range` / `paged_api` sources, because those
are read by their own stream's pipeline.
