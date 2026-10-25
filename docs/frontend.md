# Frontend (wave 2, stream D)

The CareCost price tool at `/start`: payment choice, chat, "Skip AI → Browse prices", a split view
(chat | receipt · list · map), the gradient receipt, and full-page red-flag / 988 stops. It runs on the
committed contract fixtures (mock mode) until streams C and Chat merge.

## Run

```bash
cd frontend
npm ci
npm run dev:app                      # http://127.0.0.1:5180/start  (mock data, the default)
VITE_DATA_SOURCE=api npm run dev:app # real API: /api is proxied to 127.0.0.1:$VITE_API_PORT (default 8000)
# or add ?data=api / ?data=mock to the URL

npm run typecheck:contracts          # generated contract types + exhaustive.ts + the copy file
npm run typecheck:app                # tsc -p tsconfig.app.json (0 errors)
npx vitest run                       # logic + component tests
npm run content:build                # glossary / cards / questions / MA ZIP JSON from their YAML sources
npm run build && npx vite preview --host 127.0.0.1 --port 5180 --strictPort
npm run screenshots                  # Playwright, needs a server on :5180; writes docs/frontend/*.png + switch-timing.json
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
| `src/app/api/client.ts`, `mock.ts` | `POST /api/quote`, `POST /api/chat`, `GET /api/catalog`; mock mode from `contracts/fixtures/*.json` |
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
- Location never leaves the browser: device geolocation or a typed MA ZIP (bundled centroid table).
- Red flag → full page, no prices. crisis_988 has its own page (tel:988, sms:988, 988lifeline.org chat, 911).
- No accounts (D19). Email is asked only before AI use (D2), unverified.

## Mock mode

Quotes: chronic shoulder pain × {BCBS MA HMO (real P1 output), cash (real P1 output), Medicare (hand-made)}.
Anything else (other insurers, MassHealth, other care paths, single-service picks) shows "No test data for this
choice yet" instead of inventing numbers. Chat is a demo script, not the red-flag gate: crisis words → the
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
Mock mode has no network round trip; with the real API add the quote latency (P1 bench: p50 2.7 ms on loopback).

## Screenshots (`docs/frontend/`)

`start`, `receipt-bcbs`, `receipt-cash`, `list`, `map`, `red-flag`, `crisis-988` at 375 and 1280 px, plus
`split-stacked-flipped-1280`.
