# Site facts: services, name, hours and phone from each site's own website

Plan rule P10 (Austin, 2026-10-25, Q8): what a site offers, its official name, hours and phone
are read from the site's **own** website, **twice independently**, with a URL and a verbatim
quote for every claim. Where the two runs disagree, Austin decides. Contract X1 (S0 writes,
C3 reads) is in `WORK/PLANS/carecost-mvp-2026-10-24/wave2-c3-briefs.md` §X.

Code: `backend/app/site_facts/`. Data: `data/sites/site_facts/`.

| File | What | Who writes it |
|---|---|---|
| `capabilities.yaml` | X1 vocabulary: one capability per kind of service; every care-path step covered exactly once | hand (tests enforce coverage) |
| `finders.yaml` | operators' own location finders (sitemaps) used by discover | hand |
| `found.yaml` | hand-checked / web-search-found own pages, and "no own page" decisions; wins over everything | hand |
| `pages.yaml` | each site's own pages (generated) | `discover` |
| `cache/` | visible text of every fetched page (**gitignored**) | `fetch` |
| `manifest.yaml` | one row per fetched URL: status, `fetched_at`, `page_sha256`, method, why manual | `fetch` |
| `runs/<run_id>.yaml` | one extraction run (X1 shape without `status`) | an extraction agent |
| `reviews.yaml` | Austin's decisions on disputed claims | Austin |
| `facts.yaml` | X1 merged result, read by C3 | `merge` |
| `review/<a>__<b>.html` | disagreements side by side, for Austin | `merge` |

## Commands

```
cd backend
uv run --frozen python -m app.site_facts discover            # -> pages.yaml (polite sitemap reads)
uv run --frozen --extra etl python -m app.site_facts fetch [--sites a,b] [--follow 3] [--no-js]
uv run --frozen python -m app.site_facts show <site_id>[,...] # what a run may read, with EV fields
uv run --frozen python -m app.site_facts verify <run_id> [--strict]
uv run --frozen python -m app.site_facts merge <run_a> <run_b>
uv run --frozen python -m app.site_facts coverage
```

## Fetch rules

- Plain HTTPS through `app.etl.fetch.http_open` (https only, host allowlist on every redirect hop,
  8 MB cap) with its one honest user agent `CareCost-ETL/1.0 (+price transparency research; contact via repo)`.
  Never a different user agent.
- `robots.txt` read first for every host and obeyed (product token `CareCost-ETL`); a 401/403 on
  robots.txt means "disallow all".
- At most 1 request per second per host.
- Plain headless Chromium (no stealth, same user agent) only for a page marked `needs_js` in
  `found.yaml`, or when the plain text is under 400 characters.
- HTTP 401/403/429/503, a bot-check page, or a robots disallow -> `status: manual` with the reason.
  Never retried another way; a person reads it.
- `--follow N` also fetches up to N same-host links from a location page whose text or path names
  services, hours, imaging, treatments (own sub-pages first).
- Cache text = the page's visible text (`app/site_facts/text.py`): no scripts / styles / templates
  / `hidden` elements, one block per line, the `<title>` as the first line `TITLE: ...`.
  `page_sha256` is the sha256 of that text. schema.org JSON-LD hours are **not** visible text and
  so not quotable; the manifest only flags them (`jsonld_hours: true`).

## Extraction run: instructions for the agent doing it

You get a list of site ids. For each, run `show <site_id>` and read **only** that output. Do not
open other runs, `facts.yaml`, `sites.yaml` values for phone/hours, or the web. Write
`data/sites/site_facts/runs/<run_id>.yaml`:

```yaml
version: 1
run_id: run_a_20261101          # snake_case, unique
extracted_by: "agent name / model; did not see any other run"
extracted_at: '2026-11-01'
sites:
  afc_watertown:
    pages_read: [https://www.afcurgentcare.com/watertown/]   # every URL you looked at
    official_name: {value: AFC Urgent Care Watertown, evidence: [EV]}
    phone:  {value: (617) 923-2273, evidence: [EV]}
    hours:  {value: [{days: [mon, tue, wed, thu, fri], open: '08:00', close: '20:00'}], evidence: [EV]}
    capabilities:
      walk_in_visit: {value: offered, evidence: [EV]}
      xray: {value: unknown}     # same as leaving it out
    note: optional free text for the reviewer
# EV = {url: ..., quote: "...", fetched_at: '<copied from show>', page_sha256: <copied from show>}
```

Rules:

1. **Quote verbatim.** Copy the quote character for character from the `show` text (line breaks
   may become spaces; nothing else may change). Keep quotes short: the smallest span that proves
   the claim. A claim with any quote not found is rejected whole.
2. **Copy `fetched_at` and `page_sha256` exactly** from the `show` header of that page.
3. **official_name**: the site's name as the page writes it (prefer the heading of the location
   page over the `TITLE:` line). **phone**: the main number for this location (not fax, not
   billing, not a central scheduling line for the whole system unless it is the only one); the
   quote must contain the digits. **hours**: 24-hour `HH:MM`, `24:00` allowed as a close; leave
   out days the page says are closed; leave hours out when the page gives none for this site
   (e.g. "hours vary by clinic", or only emergency-department hours on a hospital page: say so in
   `note`).
4. **Capabilities** (ids in `capabilities.yaml`): `offered` only when the page says this site
   (not "our system", not a sister site) does it; `not_offered` only when the page says it does
   not; conditional wording ("X-ray not always available, please call") is `unknown` with the
   quote in `note`. Everything you cannot see stays out. Never infer from the kind of site.
5. A site whose pages are all `manual` or empty: write only `pages_read` and a `note`.
6. **Quotes may include neighbouring words** so they are unambiguous ("Phone: 781-416-3500",
   "Newton, MA 02462 617-243-6000"); a bare number or a one-word menu item is allowed but weak.
7. **Conflicting statements on the site's own pages** (e.g. "Onsite Xrays" in a list and "X-ray not
   always available, please call to confirm" in a banner): the more restrictive statement wins ->
   `unknown`, both quotes in `note`.
8. **Whole-organization lists.** A services index that lists a specialty for a whole hospital or
   practice ("Digestive Care", "Dermatology") counts as `offered` for that site only when the
   site *is* that hospital / practice location. When the site is a different entity at the same
   address (e.g. a physician-group record whose pages in `found.yaml` are the hospital's), say so
   in `note`; the reviewer decides. Menu items and "featured services" lists count as the page
   saying it.
9. **Hours shown as 00:00–24:00 every day next to "hours vary by clinic"** (hospital campus pages):
   leave hours out and say so in `note`.
10. **Mapping words to capabilities.** Map only when the page names the service itself (e.g.
    "colonoscopy", "X-ray", "physical therapy", "biopsy"). A broader phrase ("gastrointestinal
    procedures") or a neighbouring procedure ("Mohs surgery" for `skin_excision`) stays out, with
    a `note`. Conditions treated ("joint pain") are not services.
11. The `show` output repeats each site's navigation menu on every page; read the menu once.

`verify` checks every quote against the cache; `merge` marks a claim `agreed` only when both runs
make it with the same value (names compared ignoring case and punctuation, phones by digits,
hours per day) and both verify. Everything else either run claims is `disputed` and goes on
the review page; a claim neither run makes is left out (C3 reads it as unknown).

## Review (Austin)

Open `review/<a>__<b>.html`. Each row shows both runs' values with their quotes and links, or why
the verifier rejected one. Copy the YAML in the last column into `reviews.yaml` under
`decisions:`, keep the value you accept, re-run `merge`. A decision is applied
(`status: austin_reviewed`) only when its value equals a verified claim from one of the runs, so
it always carries a real quote; when the page later changes and no run makes that claim any
more, the decision is listed as stale instead of applied.
