# contracts/

Generated JSON Schemas: the seams between the wave-2 streams. Never edit a `*.schema.json` by hand.
Change the pydantic model, regenerate, and commit both. Drift tests fail CI when a committed file is stale.

## Schemas

| Schema | Model (source of truth) | What it is | Produced by | Consumed by |
|---|---|---|---|---|
| `source_kind`, `provenance`, `money`, `gap`, `cell`, `rate_row` | `backend/app/etl/contracts.py` | Where a number came from; Money or a typed Gap; one negotiated-rate fact | ETL (A0/A1, A2 TiC, A3 gov) | quote engine (C), every API schema below |
| `care_path` | `backend/app/care_paths/models.py` | Clinical content: steps, tiers, citations, codes | care paths (B) | quote engine (C), chat (E), catalog |
| `quote_api` | `backend/app/quote/contracts.py` | `QuoteRequest` (payment + care path id *or* manual codes + optional site filter) and `QuoteResponse` (per site: summary + gradient receipt + totals + other-payer range) | quote engine (C) | frontend (D) |
| `chat_api` | `backend/app/chat/contracts.py` | `ChatRequest` (text, the person's own earlier turns, payment, unverified email, opaque conversation id, chip answers, optional receipt-line focus) and `ChatResponse` (reply union: `red_flag` / `clarify` / `care_paths` / `text` / `llm_invalid` / `ai_paused`, plus budget status and the server's turn count) | chat backend (E) | frontend (D) |
| `catalog` | `backend/app/quote/contracts.py` (`Catalog`) | Skip-AI manual picker (D3): services with plain + technical name, codes, care paths | quote engine (C), built from care paths | frontend (D) |
| `site` | `backend/app/sites/contracts.py` | `data/sites/sites.yaml`: coordinates, billing type, booking links (On My Way / Solv / Clockwise / MyChart / Patient Gateway, links only), hours + source, posted cash prices with checked date + URL | gov data + sites (A3) | quote engine (C) |

`quote_api` and `chat_api` hold two roots each (request and response) under `$defs`. The file's top-level
`anyOf` accepts either.

## Rules the contracts enforce

Every rule below is a model validator with a negative test that fails when the rule is deleted
(`backend/tests/contracts/test_quote_rules.py`, `test_chat_rules.py`, `test_api_contracts.py`,
`backend/tests/etl/test_contracts.py`). Rules checked only against the committed fixtures are listed
separately at the end.

- **AI never produces dollars.** There is no AI `SourceKind` and no AI `Method`, so no `Money` can say an
  AI wrote it. AI-suggested lines (`ai_suggested`, or a whole quote with `picked_by: assistant`) may show
  a deterministic price but are never in a total.
- **A number's chip is its provenance.** `Provenance.source_id` names the registered source;
  `row_ref` must start with `<source_id>:<sha256[:12]>:`. `QuoteResponse.sources` holds each source
  once (kind, publisher, freshness, P2), and must list exactly the sources the response uses (every
  Money, both sides of a conflict, elsewhere cells, list prices, other-payer points, every
  `searched` file, every site's price source). A Money's `source_kind` must equal its source's kind.
- **Payment ↔ price type** (`PRICE_MATRIX`): insurance → hospital-MRF / TiC negotiated rates of the
  same payer (`prov.payer_id`), or a rung-6 estimate; Medicare → fee schedules or the hospital's own
  Medicare row; MassHealth → its fee schedule or the hospital's MassHealth row; cash → discounted cash or
  a posted self-pay price. Doctor-fee rungs per payment (`RUNGS_BY_PAYMENT`); rung 7 is the Medicare
  reference (shown, never summed); a rung-6 multiple is the same payer's. A gross charge is never a
  line price: it can only be `list_price`, which no total reads. `you_pay.kind` fits the payment
  (commercial: `deductible_then_coinsurance` or `copay_or_deductible`, P11).
- A price cell is a `Cell` (Money or one of five Gap kinds). Tier `not_in_public_data` holds exactly the
  "no number" Gaps (`not_published`, `not_loaded`, `no_source`). `not_published` and `percent_only` say
  which file was searched (`searched`). Display tier = care-path likelihood (`rare` → `possible`).
  Each line carries `tier_basis` (guideline / plan_rule / our_judgment, derived from the step's
  rating; `picked` exactly when there is no step).
- `in_total` only for certain/likely, offered, one-off Money lines that are not AI-suggested. Doctor-fee
  rungs 7–8 are reference only. `totals.likely` is exactly the sum of those lines, and its
  `includes_estimate` / `includes_late_source` / `includes_stale_source` are derived from them. Every
  other line is in `totals.excluded` with a reason. `totals.complete` is false when a certain/likely
  line is missing.
- **I7, ranking never rewards missing data.** `totals.missing` = certain/likely non-AI lines not in the
  total + certain/likely steps another site in the quote lists and this one does not. Sites are ordered
  by `(missing, total low)`, so losing a price always moves a site down.
- Doctor fee: rung 1–8 plus a fixed `fee.*` copy key. Rung 6 carries its multiple, and its Money is
  basis `estimate` + method `estimate_medicare_multiple`. Rung 8 needs its CHIA badge. Self-pay has no
  rung. `by_npi` (D6) needs ≥ 2 different prices.
- **Freshness is computed per request** (`QuoteResponse.as_of`, `OurDataResponse.as_of`): each source's
  stored `Freshness` must equal `Freshness.at(as_of)` on its own inputs, so a shipped image that nobody
  rebuilt still turns "stale on our side". The two sides are never merged (`Freshness` in
  `backend/app/sites/contracts.py`):
  - (a) Publisher side, `late_to_refresh`: the publisher is past its own deadline (`last_updated`,
    `expected_by`, `source_rule`). Hospital MRF 365 days, TiC 45 days, fee schedules at their next release,
    a clinic page 365 days after its printed date (never, if undated). Shown, labelled "late to refresh".
  - (b) Our side, `stale_on_our_side`: our last successful fetch (`fetched_at`) is past our own schedule
    (`our_refresh_due`, `our_rule`). Our fault, never worded as the publisher's.
  - We never call a publisher late while we are stale ourselves. The notices `late_to_refresh_sources` /
    `stale_on_our_side_sources` appear exactly when one applies.
- TiC: an `insurer_tic` source needs `data_version.tic_release`; `tic_not_loaded` ⇔ no release.
- Sites: `hospital_outpatient` never bills as `office_visit`; `billing_type: asc` ⇔ an ambulatory surgery
  center; `tins` are 9 digits and need `tins_source`; a `registry_only` listing may sit in sites.yaml but
  is never quoted (`SiteSummary.listing_status`).
- No personal data. The quote request has no location: distance is computed in the browser. The only
  personal field anywhere is the unverified `email` in `ChatRequest` (D2). Request `answers` are bounded
  (20 ids × 8 values × 40 chars), as are codes, site ids and chat history.
- Placeholders: an all-zero sha256 or an NPI not starting with 1/2 is refused unless the caller validates
  with `context={"allow_placeholders": True}` (fixtures only).
- **Chat** (`ChatResponse` validates only with a `ChatContext`: the registries, the request it answers
  and the LLM call meter; without one validation fails, so the endpoint cannot skip these):
  - path ids, titles and review status come from the catalog; chip questions, answers and `multi` are
    verbatim from `questions.yaml`; red-flag dispositions, copy and flag ids are read from whatever
    `redflags.json` holds; card ids, glossary keys and suggested services (P5) are members, with catalog
    names; `focus_line_id` must be the line the request focused on;
  - D33, the AI only phrases: LLM text may name a condition only if the shown care path's own title or
    intro names it (allowed list derived, never authored per path; vocabulary
    `data/chat/condition_names.yaml`, a deny-list with the known limit that unlisted names pass);
    `CandidatePath.because` is built from the person's own chip answers that satisfied the path's entry
    rule (an `entry_matched` path must really match; `ai_ranked` lists none); every reply showing care
    paths carries `copy.not_a_diagnosis` + `copy.when_to_see_a_doctor`;
  - `understood` (P5): question/value members, `evidence` quotes the person's own words (current or
    earlier turn), never a `none` value;
  - `llm_called` equals the meter (`LlmMeter.record()` in the LLM client wrapper), never a handler bool;
    `red_flag` / `ai_paused` have no LLM call; at most 2 attempts; `llm_invalid` needs a call;
  - every LLM-written string is `LlmText`: ≤ 300 chars, no currency symbol, no number next to a money word
    (en / zh), no CPT/HCPCS-like code, link, email, phone number or markup;
  - at most 2 chip questions; `ChatRequest.history` holds only the person's own turns (P5b, ≤ 6,
    ≤ 4000 chars); answers are checked against `questions.yaml` by `ChatContext.for_request`;
  - budget: hard cap, turn cap or an empty wallet ⇒ `paused`; `turns_today ≤ turn_cap`; times are
    timezone-aware; `conversation_turn` is the server's count and past 12 turns the reply is
    `ai_paused(conversation_cap)`.
  - For stream E: do not declare `response_model=ChatResponse` on the route (FastAPI re-validates without
    the context); validate once with the context and return its JSON.

Checked against the committed fixtures and registries only (tests, not validators):
- every hospital-MRF and TiC number in a quote fixture is the cited row's number for the line's code,
  modifier and the payment's payer, a range's high end is the highest row the same lookup finds, and
  every `not_published` / `percent_only` claim survives re-running the lookup (`rate_row_extract.csv` +
  `rate_row_extract.sources.yaml`, written by `python -m app.quote.fixtures_gen` from hospital build
  `20261024-10d8a893` and the 2026-10 BCBS HMO Blue TiC files);
- payer, product, site, hospital, source, care-path, question, card and glossary ids resolve against
  their registries; three unregistered placeholder sources are listed in `test_fixtures.py`;
- quote lines match their care-path step (codes, likelihood, `tier_basis`).

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
"cheapest elsewhere", a per-15-minute line, a list price, a copay plan, and a source late to refresh
(publisher) and one stale on our side.

| Fixture | Shows |
|---|---|
| `quote_request_*` / `quote_*_shoulder` | Chronic shoulder pain with clicking. **BCBS HMO and cash are real P1 engine output** (Tufts Medical Center, Mount Auburn Hospital, AFC Urgent Care Watertown; `python -m app.quote.fixtures_gen`, see `docs/p1-slice.md`); the engine reproduces them from `rate_row_extract.csv` in CI. Medicare is still hand-made (Brigham rows real, Medicare PFS a placeholder until A3). The pre-P1 hand-made BCBS / cash quotes live in `backend/tests/contracts/handmade/` as the mutation base of the negative rule tests. |
| `quote_request_masshealth_manual` | Skip-AI manual pick (D3) with MassHealth |
| `chat_request_first_message`, `chat_red_flag`, `chat_clarify`, `chat_care_paths`, `chat_text`, `chat_llm_invalid`, `chat_ai_paused` | Chat request and every reply kind |
| `catalog` | Built from the 10 care paths in `data/care_paths/paths/` |
| `sites` | `sites.yaml` entries for every site the quotes use (urgent care with posted prices, On My Way link, hospital outpatient) |

Values that do not exist in loaded data yet are placeholders, validated only with `allow_placeholders`:
Medicare PFS RVU26A in the Medicare quote (not registered until A3 adds its reader) and, in the hand-made
mutation bases under `backend/tests/contracts/handmade/`, the BCBS TiC group rate at Brigham (`bcbs_ma_tic_hmo`),
the AFC posted page and NPIs `0000000001`/`0000000002`. The real BCBS / cash quotes validate without
placeholders (`test_real_fixtures_need_no_placeholders`). Shapes real P1 data cannot show yet (percent-only,
by-NPI, not offered, late / stale sources, rung 7) are listed in `test_fixtures.py::NOT_IN_REAL_DATA`.

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

`SourceSpec` (`backend/app/etl/config.py`) registers only formats that have a reader (P3). A stream adds its
format row in the same commit as its reader, with rules taken from the real file:

| format | kind | media | container | access |
|---|---|---|---|---|
| `cms_v3_csv_tall` / `cms_v3_csv_wide` / `cms_v3_json` | `hospital_mrf` (needs `entity_id` + `npis`) | csv / json | zip, plain | download |
| `tic_table_of_contents` | `insurer_tic` (needs `payer_id`) | json | plain, gzip | download |
| `tic_in_network` | `insurer_tic` (needs `payer_id`) | json | gzip, plain, zip (D30) | http_range, download |

`RateRow` carries the insurer-TiC `tic_*` fields (D30): required on `insurer_tic` rows, absent on hospital
rows. The hospital rate_row pipeline reads only `SourcesFile.rate_row_sources` (the MRF formats) and skips
other formats with a `SKIP` line; `fetch` also skips `http_range` sources, which the TiC pipeline reads.
