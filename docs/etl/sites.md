# Site registry (stream A3, 2026-10-24)

`data/sites/sites.yaml` is the list of places the quote engine may price (D14, D27, P12);
`data/sites/to_verify.yaml` is the queue of listings we are not sure exist (never quoted). Both are
generated; hand-checked fields live in `data/sites/curated.yaml`.

```
python -m app.sites.build [--check]          # census + hospitals + curated -> sites.yaml / to_verify.yaml
python -m app.sites.dph fetch|check          # DPH lists (plain browser) -> dph_check.json, dph_services.yaml
python -m app.sites.anchors                  # NPPES + TIN anchors
python -m app.sites.posted_prices            # AFC Watertown self-pay page -> posted/afc_watertown.json
python -m app.sites.radiology --dac … --tic-index …   # radiology_groups.yaml (P1 problem 6)
```

Monthly: `.github/workflows/etl-sites.yml` (DPH fetch + check, anchors, rebuild, tests; uploads the
diff for review; nothing is committed by CI).

## Sources and dates

| Input | Where | Date | Note |
|---|---|---|---|
| Clinic census | `data/sites/census/clinic-census-2026-10-24.csv` (copy of research-v3, sha256 8e9cc2ae…) | 2026-10-24 | 398 rows, registry-first (DPH, CMS, NPPES, HPC RPO, payer TiC, Humana FHIR) |
| Hospital campuses | `data/registries/hospitals.yaml` + each price file's own `hospital_address` (`data/sites/hospital_addresses.yaml`) | files of 2026-03-13 … 2026-04-01, fetched 2026-10-25 UTC | 17 hospitals |
| DPH facility list | https://www.mass.gov/doc/list-of-health-care-facilities-licensed-or-certified-by-the-division/download (`healthcare-facilities-sept-2026.xlsx`, sha 163b9697…) | file date 2026-09-08 | 3,418 rows, 920 in scope |
| DPH licensed clinics + services | https://www.mass.gov/doc/list-of-licensed-clinics-and-services-provided/download (sha 292e0bb1…) | Sept 2026 | 1,059 rows, 306 in scope |
| DPH/HPC urgent care + retail data | https://www.mass.gov/doc/urgent-care-and-retail-clinics-data/download (sha 7d97d259…) | data 2024-07 | 288 rows, 77 in scope; self-reported |
| CMS Doctors & Clinicians | data.cms.gov mj5m-pzi6 (census download, modified 2026-10-02) | 2026-10 | radiology groups only |
| BCBS MA TiC provider references | HMO Blue 2026-05-01 file (census index) | 2026-05 | NPI -> TIN for radiology groups |
| AFC Watertown self-pay page | https://www.afcurgentcare.com/watertown/resources/self-pay/ (robots.txt allows it) | checked 2026-10-24 | 86 priced rows |
| NPPES API | https://npiregistry.cms.hhs.gov/api/?version=2.1 | live | anchor only |

## Row counts (`data/sites/build_report.json`)

- Census 398 rows; **271 active** by the census's own rule (`final.py`: no `closed`, `likely_closed`,
  `registry_only`, `terminated`, `remove` flag). The census write-up says 273; the committed CSV
  gives 271 under that same rule, so 271 is the measured number.
- Left out: 9 restricted rows (student / employee health, restricted programs: GB0022–GB0025,
  GB0164, GB0167, GB0229, GB0313, GB0316).
- **sites.yaml: 208** = 191 census sites (active, ≥2 registries or web-verified, geocoded) + 17
  hospital campuses. By type: 65 urgent care, 97 specialist office, 40 hospital outpatient
  (incl. the 17 campuses), 6 ASC. Billing: 113 office visit, 48 hospital outpatient, 4 ASC, 43
  unknown. Ownership includes `payer_owned` (Atrius, 17), `franchise` (AFC, 17),
  `community_health_center` (7). 10 `children_only` (PM Pediatrics, MGB for Children GI,
  Children's, Franciscan ...).
- **to_verify.yaml: 131**: rows flagged `registry_only_unverified` (not closed) plus active rows
  seen in only one registry. 36 rows (active or registry-only) have no coordinates and cannot be a
  `Site` yet; their census ids are in `build_report.json` (`no_coordinates_not_written`).
- TINs on 171 sites (`tins`, 9 digits) and 19 with NPI-type TiC "TINs" (`tin_npis`).

## Fields filled for P1

- **Problem 4 (TINs):** `tins` are digits only; `normalize_tin("04-3026897") == "043026897"`, the
  form a TiC file prints. Each site also carries `census_id` (`GB0378` ...), the id TiC rows
  already store in `tic_site_ids`. Hospital campuses take the EIN from their own price-file name.
- **Problem 6 (radiology groups):** `data/sites/radiology_groups.yaml`, 14 hospitals. E.g. Mount
  Auburn: Schatzki Associates (17 radiologists, TIN 042482067); Tufts: Pratt Radiology Associates
  (51, 043148388); NEBH: NEB Radiology (10, 043034933); MGH: MGPO (226, 042807148). No radiologists
  matched Dana-Farber, Franciscan or BMC South's address keys.
- **Problem 9 (AFC posted prices):** reader for AFC's self-pay tables; it agrees with every curated
  cash price (Evaluation $179, X-ray 2 views $150, sling $32); diffs go to a person, never straight
  into sites.yaml. Carbon Health's pricing page (5 sites) has no reader yet.
  A7 (2026-10-25): `evaluation_consultation` ($179, `includes_provider_fee: true`) now carries the
  visit codes 99202-99205 and 99212-99215 in `curated.yaml`, so a self-pay visit at AFC is priced
  from the page instead of `not_published`. The page posts one provider-visit price with no levels
  ("Evaluation Consultation (provider)", and "STD Testing $179 plus the cost of the test"), so the
  mapping reads it as any level 2-5 office visit; 99211 (a nurse visit) is left out. The other two
  cash prices: `xray_2_views` has 73030; `sling` has no code (a supply with no confident CPT /
  HCPCS mapping, left empty on purpose). No other site has cash prices.
- **Problem 14 (offered services):** `Site.offered` holds positive evidence only (absence = unknown,
  never "not offered"): census category (visit / endoscopy), AFC's posted X-ray price, DPH licensed
  service flags (MRI, physical rehab) and the DPH/HPC urgent-care flags (imaging, lab) applied only
  when the census matched that very site to that DPH list (a licence in a building does not cover
  every tenant). 79 DPH-based entries.

## DPH (D28)

1. Looked for a public data API first. The DPH "Urgent care and retail clinics" dashboard is an
   ArcGIS Instant App (item f8e64de306674887ab98451a9cbe0091). Its clinic layer
   (`HPC_Retail_and_Urgent_Care_Clinics_Dataset_June_2024_v5`) answers "Item does not exist or is
   inaccessible", so there is no public API for the clinic data; only its "Acute Care Hospitals"
   layer (`HOSPITALS_PT`, 72 features) is public. The facility and clinic lists are XLSX only.
2. So `python -m app.sites.dph fetch` opens the mass.gov page in a plain headed Chromium (its own
   user agent, no fingerprint changes, no stealth) and clicks each download link. On 2026-10-24
   all three downloads worked (landing HTTP 200); no 403 or captcha.
3. If a 403 or captcha appears the command stops (`BrowserBlocked`) and does not escalate. Manual
   steps then: open the two pages below in a normal browser, download the three XLSX files, save
   them as `data/raw/manual/dph/facilities-<yyyy-mm>.xlsx`, `clinic_services-<yyyy-mm>.xlsx`,
   `uc_retail-<yyyy-mm>.xlsx`, run `python -m app.sites.dph check` (it reads manual copies when no
   browser copy exists, `method: manual`).
   - https://www.mass.gov/info-details/find-information-about-licensed-or-certified-health-care-facilities
   - https://www.mass.gov/info-details/urgent-care-and-retail-clinics-in-massachusetts
4. `check` is loud: in-scope counts per facility type must stay within 15% of last month (first
   run = the census: Hospital Satellite 169, Clinic 166, Clinic Satellite 132, ASC 17, Acute
   Hospital 21; 2026-10-24 matched all five exactly), anchor DPH 2ED8 (BIDMC Chelsea) must exist,
   and new / gone facility ids are listed for review.

## Monthly funnel (census §8) — what is automated

| §8 step | Automated here | Not yet |
|---|---|---|
| Inputs | DPH lists (browser), NPPES anchor (API) | NPPES bulk (CMS page "down for maintenance" on 2026-10-24), CMS DAC / Reassignment / POS, HPC RPO, TiC provider-ref heads, Humana FHIR sweep, operator location pages |
| 1–3 normalize / classify / dedupe | the census `akey` ported (`app.sites.address`, 398/398 equal to the census `site_key`) | re-running classification on new registry pulls |
| 5 billing class | from the census evidence (`billing_type_confidence` stated / likely / unknown) | |
| 6 diff | DPH new / gone ids; `git diff` of the regenerated files in the workflow artifact | NPPES / operator-page closure detection |
| 7 checks | DPH counts ±15%, DPH 2ED8, NPPES 1164772299 active in Watertown, AFC TIN 460903626 | DAC ±15%, RPO provider-based check, HTTP 206 checks (A2 owns TiC) |
| 8 output | sites.yaml (approved rows only), to_verify.yaml, build_report.json, dph_check.json | census-YYYY-MM.csv re-harvest |

## Billing type through system structure (A5, R7 / P9)

`python -m app.sites.billing` resolves `billing_type: unknown` from public structure and writes
`data/sites/billing_structure.yaml` (committed; `app.sites.build` reads only that file). Rules
(each recorded as the site's `billing_type_source`): a DPH **Acute Hospital** licence of the
site's own system at its address (on-campus department) → `hospital_outpatient`; a DPH
**Hospital Satellite** licence of its system where the site is named as that hospital's own
department → `hospital_outpatient`; the HPC RPO 2024 provider-based status (YES/NO) for the
site's own location; an NPPES type-2 NPI of the site that is a hospital (282N) of its system.
Another organisation's licence in the same building never decides; disagreeing rules leave the
site `unknown`. 2026-10-25: 43 unknown → 20 resolved, 23 listed under `billing_to_verify` in
`to_verify.yaml` (still quoted; the engine prices them as hospital outpatient + a facility-fee
gap). One ASC on a hospital satellite licence (Newton-Wellesley Outpatient Surgery Center)
becomes `site_type: hospital_outpatient`.
