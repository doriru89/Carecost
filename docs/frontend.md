# Frontend (wave 2, stream D)

The CareCost price tool at `/start`: payment choice, chat, "Skip AI → Browse prices", a split view
(chat | receipt · list · map), the gradient receipt, and full-page red-flag / 988 stops. Mock mode runs on the
committed contract fixtures; api mode runs on the merged backend (`app.server`, wave2/base 9c54616 + D3).

## Run

```bash
cd frontend
npm ci
npm run dev:app                      # http://127.0.0.1:5180/start  (mock data, the default)
VITE_DATA_SOURCE=api npm run dev:app # real API: /api is proxied to 127.0.0.1:$VITE_API_PORT (default 8100)
# or add ?data=api / ?data=mock to the URL

npm run typecheck:contracts          # generated contract types + exhaustive.ts + the copy file
npm run typecheck:app                # tsc -p tsconfig.app.json (0 errors)
npx vitest run                       # logic + component tests
npm run content:build                # glossary / cards / questions / MA ZIP JSON from their YAML sources
npm run build && npx vite preview --host 127.0.0.1 --port 5180 --strictPort
# api mode needs the backend: cd backend && uv run --frozen uvicorn app.server:app --port 8100
MODE=both npm run screenshots        # Playwright, needs a server on :5180; mock -> <screen>-<w>.png + switch-timing.json,
                                     # api -> <screen>-api-<w>.png + switch-timing-api.json
```

## Where things are

| Path | What |
|---|---|
| `src/app/pages/CareApp.tsx` | `/start`: start page → workspace; chat state, quote requests (cached per payment × query), red-flag stop, insurance-switch timer |
| `src/app/components/SplitView.tsx` | D9: side by side / stacked, swap or flip; two tabs under 768 px |
| `src/app/components/Receipt*.tsx`, `CellView.tsx`, `SourceChip.tsx`, `OtherPayers.tsx`, `DoctorFeeNote.tsx` | D8 gradient receipt |
| `src/app/components/SiteList.tsx`, `SiteMap.tsx`, `Booking.tsx` | §4.3 list and MapLibre map (OpenFreeMap `liberty` style, no key; loaded lazily) |
| `src/app/components/ChatPane.tsx` | every chat reply kind; chips; "Because you said"; D33 lines |
| `src/app/pages/StopPages.tsx` | red flag (911 / ER / seen today / routine) and the separate crisis_988 page |
| `src/app/api/client.ts`, `mock.ts` | `POST /api/quote`, `POST /api/chat`, `GET /api/catalog`, `GET /api/catalog/paths`, `GET /api/catalog/paths/{id}/services`; mock mode from `contracts/fixtures/*.json`. `quoteBody()` is the only place that sets C2's `near` / `max_sites` |
| `src/app/lib/*` | pure logic: tiers, source hover text, freshness, cash-discount check, hours (Boston time), distance, sorting, payment list |
| `src/contracts/copy.ts` | the copy file every contract copy key resolves to (compile-checked) |
| `src/app/content/*.json` | built from `content/glossary/glossary.yaml`, `data/questions/questions.yaml`, and the `zipcodes` package (MA only) |

## Rules the UI keeps

- Every dollar on screen is a contract `Money` (or a `SummedAmount` total); the UI never computes a price.
  The only arithmetic is min/max for the range-bar scale and distance in miles.
- A cell renders only through `CellView`, a switch over `Cell` that fails to compile on a new kind.
- Tiers are shown by visual weight (solid → lighter → dashed → warning colour), never numbered.
  "Possible" lines and AI-suggested lines (dashed box) are never in the total; the total sits at the top and
  is repeated at the bottom. A total with missing likely items shows "≥".
- A chip is derived from `prov.source_id` → `QuoteResponse.sources`; hover text is the §2.2 sentence.
  "Late to refresh" (publisher) and "Stale on our side" (us) are separate labels; stale wins.
- "Price" sort keeps the engine's I7 order, so missing data never moves a site up.
- Location: device geolocation or a typed MA ZIP (bundled centroid table). Since C2 the quote request carries it as
  `near` so the server can pick the closest sites (see "C2 contract" below); distances are still computed in the browser.
- Red flag → full page, no prices. crisis_988 has its own page (tel:988, sms:988, 988lifeline.org chat, 911).
- No accounts (D19). Email is asked only before AI use (D2), unverified.

## Merged quote contract (D2)

- A range cites both ends: `Money.prov` (low) and `Money.prov_high` (high) render as a "Low:" and a "High:" chip
  when they are different rows; the hover shows `row_ref` and `Provenance.row_id`.
- `SiteSummary.price_source_id: null` → "This place has its own price list, but we do not read it yet".
- `ReceiptLine.at = your_primary_care` → "Happens at your own primary care office, not at this place".
- Rung 6 (`basis: estimate`) carries an "Estimate" tag (the total already flags `includes_estimate`); rung 7
  carries "Reference only, not added" and its amount is dimmed.
- `QuoteResponse.copy_keys` (D33) render under the receipt as "Before you go"; a manual pick has none.
- Browse uses the two picker routes: a care path opens its services ("Price every step" or "Only: <service>").
- Chat in api mode: without a provider key the merged Chat service answers `ai_paused(provider_unavailable)`, which
  renders `ai.paused_provider` with the browse button; a server error (non-2xx) is a plain error with "Browse prices".

## C2 contract (D3)

- Request: `quoteBody()` always sends `max_sites: 12` and sends `near` only when the person gave a location: a typed
  ZIP's centroid as is, a device fix rounded to 2 decimals (about 0.7 mi). A point outside the server's scope guard
  (lat 41.0-43.5, lon -72.5 to -69.5, e.g. Springfield 01103) is left out rather than answered with 422. The quote
  cache key includes the point, so a new ZIP is a new request.
- Without `near` the server returns the 12 best-ranked sites (I7) of the whole registry; the list and the receipt
  picker say "The 12 best-value places overall" instead of "nearest". With `near`: "The 12 places nearest ZIP 02138".
  Mock mode says "Test data: a fixed sample of places".
- `ReceiptLine.price_notes` render under the amount (`price.national_unadjusted`, `price.anesthesia_base_units_only`,
  both `review: true`); the copy file's key type includes the contract's note union, so a new note fails
  `typecheck:contracts` until it has text.
- `availability: "unknown"` shows a dashed "Not known whether this place offers it" tag; offered lines show none.
- `SiteSummary.children_only` shows a "Children only" badge on the card and the receipt.
- `SiteSummary.data_notices` show one sentence per notice kind (`data_notice.<kind>`, else `data_notice.generic`) on the
  site card and the receipt; the receipt adds the notice's own `detail` / `effect` under "What we saw (date)".
- The person's sort and chosen site live in `CareApp` (`SitePick`), so the pick survives the pane being re-parented
  when the layout crosses 768 px (seen during Playwright full-page captures at 1280).

## Mock mode

Quotes (C2's engine on the full pack, 12 sites nearest Harvard Square; Medicare: Brigham only): chronic shoulder
pain × {BCBS MA HMO, cash, Medicare}, and a manual pick of 73030 + 73221 × MassHealth (reachable through the mock API; the UI picks one service at a time).
Anything else shows "No test data for this choice yet" instead of inventing numbers. Chat is a demo script, not the red-flag gate: crisis words → the
crisis_988 reply (copy from `data/redflags/redflags.json`), emergency words → the call_911 fixture, first
message → clarify, later turns → care_paths; `#text`, `#invalid`, `#paused` return those fixtures.

## Copy review (Austin)

`src/contracts/copy.ts`: all text is AI-drafted (2026-10-24). Keys with `review: true` must be read before
launch: `copy.not_a_diagnosis`, `copy.when_to_see_a_doctor`, the four `youpay.*` insurance rules,
`fee.rung_6_estimate`, the 911 / 988 page labels (`redflag.*`, `crisis.*`). `copy.test.ts` lists them via
`reviewKeys()`. The red-flag headline and text themselves come from `redflags.json` (already under review there).

## Measured

Insurance switch (plan §4.1, < 300 ms): time from the payment `<select>` change to the next animation frame
after the new receipt commits (`window.__carecostSwitch`, `scripts/screenshots.mjs`), production build
(`vite preview`), mock mode, headless Chromium, Austin's Mac, 2026-10-24. See `docs/frontend/switch-timing.json`.
Api mode (D3, 2026-10-25): same method against `uvicorn app.server:app --port 8100` on the committed extract, through
the `vite preview` proxy, with ZIP 02138 sent as `near`; five uncached switches per width, 16.4–19.9 ms; cached
7.4–10.6 ms (`docs/frontend/switch-timing-api.json`). Mock: 9.5–16.4 ms (`switch-timing.json`).

## Screenshots (`docs/frontend/`)

Mock: `start`, `receipt-bcbs`, `receipt-bcbs-mta` (Mount Auburn, both ends of each range cited), `receipt-cash`,
`list` (ZIP 02138, nearest), `map`, `red-flag`, `crisis-988` at 375 and 1280 px, plus `split-stacked-flipped-1280`.
Api (`-api`): `start`, `receipt-bcbs` and `list-overall` (no location: best value overall), `receipt-bcbs-mta` and
`list` (ZIP 02138), `receipt-cash`, `receipt-medicare-brigham` (ZIP 02115: OPPS facility lines with
"Medicare's national rate, not adjusted for Boston", G0463 $136.02, and unknown-availability lines),
`list-medicare-02115` and `receipt-medicare-bidmc` (BIDMC's data notice), `chat-paused` (the real server's no-key reply).
