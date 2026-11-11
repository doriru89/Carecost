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
| `found.yaml` | hand-checked / web-search-found own pages, "no own page" decisions, and `scope: hospital_page` per site; wins over everything | hand |
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
uv run --frozen python -m app.site_facts targets [--ids]       # the sites a run covers (>=1 ok page)
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

## Extraction runs S1 and S2: the runbook

Two agents, S1 and S2, each write one run. They work **independently**: neither may see the
other's run, and neither may see any earlier result. Everything an extractor needs is in this
section; do not read other docs for instructions.

### 0. Setup (each agent, its own worktree)

1. Make a worktree from the branch the orchestrator names (it contains this file, `pages.yaml`,
   `manifest.yaml` and `capabilities.yaml`). Work only there.
2. **The page cache is not in git.** Copy the one shared cache into your worktree, read-only in
   spirit, before anything else:
   `cp -R <the S0b worktree>/data/sites/site_facts/cache <your worktree>/data/sites/site_facts/`
   (The 2026-10-25 cache was lost when the wave2 worktrees were removed on 2026-11-11. The
   committed `manifest.yaml` still records each page's URL, sha and `fetched_at`; a new run needs
   a fresh `fetch`, which gives new shas, so plan it as a new run, not a re-check of S1/S2.)
   Both runs must read the same cache, because every quote is checked against it by URL, sha and
   `fetched_at`. **Never run `fetch` or `discover`**, never fetch a page another way, and never use
   the web: a re-fetched page gets a new sha and your evidence would stop matching the manifest.
3. Check the copy: `cd backend && uv run --frozen python -m app.site_facts targets | tail -1`
   must print `# 139 sites; 18 with scope: hospital_page` (as of 2026-10-25).

### 1. What you may read, and what you may not

May read: the output of `show <site_id>` for your sites, `data/sites/site_facts/capabilities.yaml`
(the capability ids and the care-path steps each one covers), and this section.

May **not** read or open: any file in `data/sites/site_facts/runs/` other than your own,
`facts.yaml`, `review/`, `reviews.yaml`, the pilot runs, any other agent's report or message,
`data/sites/sites.yaml` values for phone / hours / services, `found.yaml` notes, or the web.
If you see another run by accident, say so in `extracted_by` and stop.

### 2. Which sites, which pages

- **Sites:** every site that `targets` lists (139 on 2026-10-25: urgent care 50, hospital
  outpatient 32, specialist office 56, ASC 1). Get the list with `targets --ids`. Do all of
  them; you may work in batches and write one file at the end, or several runs merged by the
  orchestrator only if it says so.
- **Pages:** for each site, exactly the pages `show <site_id>` prints, nothing else. A page
  with `status: manual` has no text: you cannot cite it. A site's pages often include the
  location page, its services page and up to three linked sub-pages (services, hours, imaging).
  A page can belong to several sites (e.g. one Atrius building page for its primary-care record
  and its urgent-care record; bmc.org/locations for several BMC campuses): read it for each site
  separately and claim only what the page says about **that** site.

### 3. The run file (X1 shape without `status`)

Write `data/sites/site_facts/runs/<run_id>.yaml`, with `run_id` = `s1_<yyyymmdd>` or
`s2_<yyyymmdd>`:

```yaml
version: 1
run_id: s1_20261026          # snake_case, unique
extracted_by: "S1 / <model>; did not see any other run or result"
extracted_at: '2026-10-26'
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
#      plus `scope: hospital_page` when show prints that line for the site (rule 12)
```

`days` are `mon tue wed thu fri sat sun`. `value` of a capability is `offered`, `not_offered` or
`unknown`. Capability ids are only those in `capabilities.yaml` (as of S0b: 25 ids, including
`urine_test`, `pregnancy_test`, `abdominal_ultrasound`, `ct`, `blood_tests`, `skin_scraping` for
the stomach-ache and rash paths).

### 4. Rules

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
4. **Capabilities**: `offered` only when the page says this site (not "our system", not a sister
   site) does it; `not_offered` only when the page says it does not; conditional wording ("X-ray
   not always available, please call") is `unknown` with the quote in `note`. Everything you
   cannot see stays out. Never infer from the kind of site.
5. A site whose pages are all `manual` or empty: write only `pages_read` and a `note`.
6. **Quotes may include neighbouring words** so they are unambiguous ("Phone: 781-416-3500",
   "Newton, MA 02462 617-243-6000"); a bare number or a one-word menu item is allowed but weak.
7. **Conflicting statements on the site's own pages** (e.g. "Onsite Xrays" in a list and "X-ray
   not always available, please call to confirm" in a banner): the more restrictive statement
   wins -> `unknown`, both quotes in `note`.
8. **Whole-organization lists.** A services index that lists a specialty for a whole hospital or
   practice ("Digestive Care", "Dermatology") counts as `offered` for that site only when the
   site *is* that hospital / practice location. Menu items and "featured services" lists count
   as the page saying it.
9. **Hours shown as 00:00–24:00 every day next to "hours vary by clinic"** (hospital campus
   pages): leave hours out and say so in `note`.
10. **Mapping words to capabilities.** Map only when the page names the service itself (e.g.
    "colonoscopy", "X-ray", "physical therapy", "biopsy", "urinalysis", "pregnancy test",
    "ultrasound" of the abdomen). A broader phrase ("gastrointestinal procedures", "lab
    services", "imaging") or a neighbouring procedure ("Mohs surgery" for `skin_excision`) stays
    out, with a `note`. Conditions treated ("joint pain", "rashes") are not services.
11. The `show` output repeats each site's navigation menu on every page; read the menu once.
12. **Hospital page cited for a physician group (`scope: hospital_page`).** For 18 sites
    (`targets` marks them) the site is a physician group or similar entity at a hospital's
    address, and its only pages are the hospital's (e.g. the HMFP record at 148 Chestnut St,
    Needham, whose pages are BID Needham's). `show` prints `scope: hospital_page` for them.
    Extract as usual, but put `scope: hospital_page` on **every** EV for that site. The verifier
    rejects an EV for such a site without it (`scope_missing`) and an EV with it for any other
    site (`scope_wrong`). `merge` never marks these claims `agreed`, even when both runs agree:
    they go on the review page and Austin decides whether a hospital page counts for the group.
    The official name you record is the name the page gives (usually the hospital's); say in
    `note` that the record is a physician group.

### 5. Verify your run (before you hand it in)

```
cd backend
uv run --frozen python -m app.site_facts verify <run_id>            # report; exit 0
uv run --frozen python -m app.site_facts verify <run_id> --strict   # exit 1 if any claim is rejected
```

Every rejection names the site, field, reason and quote: `url_not_cached`, `sha_mismatch`,
`quote_not_found`, `phone_not_in_quote`, `unknown_capability`, `unknown_site`, `no_evidence`,
`scope_missing`, `scope_wrong`. Fix your own quotes until `--strict` passes, or leave a claim out.
Do **not** run `merge`: the orchestrator merges S1 and S2 (`merge s1_<date> s2_<date>`) once both
runs are in, which writes `facts.yaml` and `review/s1_<date>__s2_<date>.html`.

Report back: run id, sites done / 139, claims and accepted claims from `verify`, the time taken,
and anything you could not read. Do not paste quotes from the other run (you have none).

## Review (Austin)

Open `review/<a>__<b>.html`. Each row shows both runs' values with their quotes and links, or why
the verifier rejected one. Copy the YAML in the last column into `reviews.yaml` under
`decisions:`, keep the value you accept, re-run `merge`. A decision is applied
(`status: austin_reviewed`) only when its value equals a verified claim from one of the runs, so
it always carries a real quote; when the page later changes and no run makes that claim any
more, the decision is listed as stale instead of applied.

## State after S0b (2026-10-25)

- `capabilities.yaml`: 25 capabilities; every step of all 12 paths covered exactly once (test).
  New for stomach ache / rash: `urine_test`, `pregnancy_test`, `abdominal_ultrasound`,
  `skin_scraping`; `ct` and `blood_tests` now cover steps. Visit steps written for "urgent care or
  primary care" go to `walk_in_visit` (as `back_new_pain_v1`); the rash path's specialist visit
  goes to `dermatology_visit`.
- Discovery: the 86 sites with no page decision (83 never searched + 3 rejected finder matches)
  all have one now. 47 got an own page: 36 from operators' own sitemaps or known pages (MGB, CHA, Atrius, BIDMC,
  Mount Auburn, NEBH, Winchester, South Shore Health, Children's, Dana-Farber, APDerm), 11 by web
  search (41 searches). 39 recorded `no_own_page` with the query or the block. The 22
  sitemap-finder matches were each checked against the street address on the cached page: 20
  confirmed and pinned in `found.yaml`, 2 wrong (`atrius…weymouth_gb0139` matched the Weymouth MRI
  page at 420 Libbey Pkwy, replaced by the 90 Libbey Pkwy page; `lahey_health_urgent_care_woburn`
  matched an urgent care at 345 Washington St, not 7 Alfred St, now no own page).
- `scope: hospital_page`: 18 sites (HMFP x7 incl. BID Needham, BWPO, MGPO at Spaulding x2, Mount
  Auburn Professional Services x2, NEBH Medical Associates, Children's Hospital Pediatric
  Associates, Evans, BUOSA, BMC Affiliated Physicians, Robert J. Banco MD at the NWH surgery
  center, Community Physicians Associates at BID Milton's office building).
- Coverage: own page **144 / 208** (S0: 98): urgent care 51/65, hospital outpatient 35/41,
  specialist office 57/97, ASC 1/5 (kinds per `sites.yaml` at ee409cf, which moved one ASC to
  hospital outpatient since S0). Fetched ok: 139; 5 sites manual only (codman.org robots x2,
  tuftsmedicalcenter.org -> tuftsmedicine.org, franciscanchildrens.org TLS chain,
  ortho.boston bot-check). Hours in visible text: **95 / 208** (heuristic). Cache: 239 URLs.
- Pilot runs re-marked: the BID Needham group's evidence now carries `scope: hospital_page`; the
  re-merge gives 14 agreed, 7 disputed (was 19 / 2: its 5 agreed claims are now for Austin).

### Earlier: S0 pilot


- `pages.yaml`: an own page for **98 / 208** sites (urgent care 49/65, hospital outpatient 26/40,
  specialist office 21/97, ASC 2/6). Sources: census website column 55, operators' sitemaps 22
  (unchecked matches; check them before trusting), hand-checked 13, web search 8 (23 searches
  used). Every other site has a `no_own_page` reason; 8 are census address clusters
  ("Clinicians at ...") with no single operator; 16 were searched and only third-party listings
  exist; 3 finder matches were rejected by hand. The other 83 were not searched yet ("not found
  yet").
- Cache: 170 URLs fetched for those 98 sites, 166 ok, 4 manual (codman.org robots disallow;
  tuftsmedicalcenter.org redirects to another domain; franciscanchildrens.org serves an
  incomplete TLS chain; one thin Carbon Health page). No 403/429 or bot-check page was hit.
  `coverage.yaml` has the per-kind numbers.
- Pilot runs `pilot_a` / `pilot_b` (5 sites) and their merged `facts.yaml`: 19 agreed, 2
  disputed. `pilot_a` was written after its author had read run B's prose report, so the two are
  not fully independent; the real runs must be.
