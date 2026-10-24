# Coverage report: build `20261024-1cb8089d`

Build date 2026-10-24 · gates: **PASS** (0 fail, 12 warn) · source: hospital MRFs only (12/12 files). Usable rate = payer-specific line, not excluded, with a dollar amount (stated, or % x the line's gross charge).

## Headline: old DB vs new rate_row

| measure | old (DB / audit) | new | denominator |
|---|---|---|---|
| target codes with any hospital payer rate | 13 | 42 | 48 codes |
| code x hospital cells with a payer rate | 84 | 397 | 48 x 12 = 576 |
| hospitals with MRF payer rates | 7 | 12 | 12 |
| MRF payer-rate rows, target codes | 902 (DB) | 13883 usable | — |
| target payer-$ rows in raw files (audit census) | 23581 | 23581 stated-$ rows kept (+32 derived from %) | — |
| rows with a mapped payer | 4822 (4 payers) | 9946 (18 payers) | 13883 usable |
| distinct rates thrown away by coarse dedup | 3,613 | 0 (never collapsed; 66 rows flagged ambiguous) | — |

Also: 0 placeholder rows ($0 / $0.01 / $1) dropped and counted; 1461 usable rows above gross (flagged); components of usable rows: facility 11969, professional 787, unknown 1127; excluded payer rows: workers_comp 4844, catch_all 1500, dental 939, retired_contract 823, out_of_state 718, behavioral_carveout 601, transplant 365, international 255, vision 60.

## Per code

| domain | code | what | hospitals w/ rate (old DB → new) /12 | files w/ payer $ (audit) | usable rows (old DB MRF rows → new) | %-only, no gross | algorithm-only |
|---|---|---|---|---|---|---|---|
| derm | 11102 | Tangential (shave) skin biopsy, single lesion | 6 → **10** | 10 | 71 → **334** | 0 | 15 |
| derm | 11104 | Punch skin biopsy, single lesion | 7 → **11** | 11 | 83 → **367** | 0 | 15 |
| derm | 11300 | Shave removal, trunk/arms/legs, 0.5 cm or less | 6 → **9** | 9 | 41 → **182** | 0 | 12 |
| derm | 11301 | Shave removal, trunk/arms/legs, 0.6-1.0 cm | 0 → **8** | 8 | 0 → **156** | 0 | 12 |
| derm | 11302 | Shave removal, trunk/arms/legs, 1.1-2.0 cm | 0 → **7** | 7 | 0 → **154** | 0 | 12 |
| derm | 11303 | Shave removal, trunk/arms/legs, over 2.0 cm | 0 → **7** | 7 | 0 → **138** | 0 | 12 |
| derm | 11305 | Shave removal, scalp/neck/hands/feet/genitalia, 0.5 cm or less | 6 → **9** | 9 | 35 → **165** | 0 | 12 |
| derm | 11306 | Shave removal, scalp/neck/hands/feet/genitalia, 0.6-1.0 cm | 0 → **9** | 9 | 0 → **180** | 0 | 12 |
| derm | 11307 | Shave removal, scalp/neck/hands/feet/genitalia, 1.1-2.0 cm | 0 → **7** | 7 | 0 → **140** | 0 | 12 |
| derm | 11308 | Shave removal, scalp/neck/hands/feet/genitalia, over 2.0 cm | 0 → **6** | 6 | 0 → **134** | 0 | 12 |
| derm | 11310 | Shave removal, face/ears/eyelids/nose/lips, 0.5 cm or less | 0 → **9** | 9 | 0 → **192** | 0 | 12 |
| derm | 11311 | Shave removal, face/ears/eyelids/nose/lips, 0.6-1.0 cm | 0 → **10** | 10 | 0 → **217** | 0 | 15 |
| derm | 11312 | Shave removal, face/ears/eyelids/nose/lips, 1.1-2.0 cm | 0 → **7** | 7 | 0 → **143** | 0 | 12 |
| derm | 11313 | Shave removal, face/ears/eyelids/nose/lips, over 2.0 cm | 0 → **6** | 6 | 0 → **135** | 0 | 12 |
| derm | 17000 | Destruction of premalignant lesion, first | 6 → **9** | 9 | 63 → **268** | 0 | 12 |
| derm | 17110 | Destruction of benign lesions, up to 14 | 6 → **10** | 10 | 75 → **373** | 0 | 15 |
| derm/gi | 88305 | Surgical pathology, level IV (tissue exam) | 7 → **11** | 11 | 63 → **467** | 0 | 10 |
| gi | 00811 | Anesthesia, lower GI endoscopy | 0 → **0** | 0 | 0 → **0** | 0 | 0 |
| gi | 00812 | Anesthesia, screening colonoscopy | 0 → **0** | 0 | 0 → **0** | 0 | 0 |
| gi | 00813 | Anesthesia, combined upper and lower GI endoscopy | 0 → **0** | 0 | 0 → **0** | 0 | 0 |
| gi | 43239 | Upper endoscopy (EGD) with biopsy | 7 → **11** | 11 | 95 → **400** | 0 | 39 |
| gi | 45378 | Colonoscopy, diagnostic | 7 → **10** | 10 | 92 → **683** | 0 | 41 |
| gi | 45380 | Colonoscopy with biopsy | 7 → **10** | 10 | 87 → **367** | 0 | 44 |
| gi | 45385 | Colonoscopy with polyp removal (snare) | 7 → **10** | 10 | 82 → **451** | 0 | 41 |
| ortho | 20610 | Joint injection/aspiration, major joint | 0 → **11** | 11 | 0 → **521** | 0 | 27 |
| ortho | 20611 | Joint injection/aspiration, major joint, with ultrasound guidance | 0 → **11** | 11 | 0 → **429** | 0 | 15 |
| ortho | 29826 | Shoulder arthroscopy, subacromial decompression (add-on) | 0 → **3** | 3 | 0 → **7** | 0 | 0 |
| ortho | 29827 | Shoulder arthroscopy, rotator cuff repair | 0 → **6** | 6 | 0 → **65** | 0 | 14 |
| ortho | 73030 | X-ray shoulder, 2+ views | 0 → **11** | 11 | 0 → **423** | 0 | 5 |
| ortho | 73221 | MRI shoulder (joint) without contrast | 0 → **11** | 11 | 0 → **388** | 0 | 6 |
| ortho | 73222 | MRI shoulder (joint) with contrast | 0 → **10** | 10 | 0 → **236** | 0 | 9 |
| ortho | 76881 | Ultrasound joint, complete | 0 → **10** | 10 | 0 → **412** | 0 | 5 |
| ortho | 76882 | Ultrasound joint, limited | 0 → **11** | 11 | 0 → **428** | 0 | 5 |
| ortho | 97110 | Therapeutic exercise, each 15 min | 0 → **12** | 12 | 0 → **448** | 2 | 12 |
| ortho | 97161 | Physical therapy evaluation, low complexity | 0 → **12** | 12 | 0 → **316** | 2 | 9 |
| ortho | 97162 | Physical therapy evaluation, moderate complexity | 0 → **12** | 12 | 0 → **302** | 2 | 9 |
| ortho | 97163 | Physical therapy evaluation, high complexity | 0 → **12** | 12 | 0 → **261** | 2 | 7 |
| ortho | 99202 | New patient office visit, level 2 | 0 → **9** | 10 | 0 → **235** | 0 | 12 |
| ortho | 99203 | New patient office visit, level 3 | 0 → **10** | 11 | 0 → **395** | 0 | 12 |
| ortho | 99204 | New patient office visit, level 4 | 0 → **10** | 11 | 0 → **353** | 0 | 12 |
| ortho | 99205 | New patient office visit, level 5 | 0 → **10** | 11 | 0 → **390** | 0 | 12 |
| ortho | 99212 | Established patient office visit, level 2 | 0 → **9** | 10 | 0 → **588** | 0 | 18 |
| ortho | 99213 | Established patient office visit, level 3 | 6 → **10** | 11 | 64 → **700** | 2 | 17 |
| ortho | 99214 | Established patient office visit, level 4 | 6 → **10** | 11 | 51 → **620** | 2 | 18 |
| ortho | 99215 | Established patient office visit, level 5 | 0 → **11** | 12 | 0 → **720** | 2 | 20 |
| urgent_care | 99051 | After-hours / evening / weekend service add-on | 0 → **0** | 0 | 0 → **0** | 0 | 0 |
| urgent_care | S9083 | Urgent care center global fee | 0 → **0** | 0 | 0 → **0** | 0 | 0 |
| urgent_care | S9088 | Services provided in an urgent care center | 0 → **0** | 0 | 0 → **0** | 0 | 0 |

## Per hospital

| hospital | file date | staged rows (= independent count) | rate rows | usable payer rates | payers | target codes /48 | placeholders dropped |
|---|---|---|---|---|---|---|---|
| mgh | 2026-03-27 | 159,489 (= 159,489) | 1,516 | 1,228 | 16 | 36 | 0 |
| brigham | 2026-03-27 | 109,293 (= 109,293) | 1,160 | 1,014 | 15 | 39 | 0 |
| faulkner | 2026-03-27 | 39,202 (= 39,202) | 250 | 215 | 15 | 16 | 0 |
| bmc | 2026-03-13 | 1,329,567 (= 1,329,567) | 4,067 | 3,113 | 15 | 41 | 0 |
| bmc_brighton | 2026-03-13 | 552,814 (= 552,814) | 1,846 | 1,543 | 14 | 33 | 0 |
| cha | 2026-03-20 | 1,022,366 (= 1,022,366) | 4,121 | 894 | 16 | 41 | 0 |
| tufts | 2026-04-01 | 5,877,884 (= 5,877,884) | 9,207 | 3,978 | 16 | 40 | 0 |
| franciscan | 2026-04-01 | 5,085 (= 5,085) | 297 | 233 | 12 | 10 | 0 |
| bidmc | 2026-04-01 | 105,362 (= 105,362) | 245 | 205 | 6 | 42 | 0 |
| childrens | 2026-04-01 | 465,548 (= 465,548) | 1,723 | 1,235 | 11 | 28 | 0 |
| dana_farber | 2026-04-01 | 55,667 (= 55,667) | 286 | 41 | 2 | 29 | 0 |
| mtauburn | 2026-04-01 | 64,504 (= 64,504) | 212 | 184 | 4 | 42 | 0 |

## Hospital x payer: target codes with a usable rate

| hospital | BCBS_MA | HARVARD_PILGRIM | TUFTS_HP | MGB_HP | AETNA | UHC | UHC_HPHC_ALLIANCE | CIGNA | WELLSENSE | FALLON | MEDICARE | MASSHEALTH |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mgh | 18 | 17 | 14 | 26 | 25 | 29 | 18 | 23 | 3 | 7 | 20 | 0 |
| brigham | 25 | 18 | 13 | 31 | 25 | 30 | 15 | 24 | 0 | 7 | 21 | 0 |
| faulkner | 7 | 6 | 7 | 5 | 10 | 14 | 6 | 8 | 0 | 1 | 8 | 0 |
| bmc | 41 | 41 | 41 | 41 | 41 | 41 | 0 | 41 | 39 | 41 | 41 | 0 |
| bmc_brighton | 33 | 33 | 33 | 33 | 33 | 33 | 0 | 33 | 33 | 33 | 33 | 0 |
| cha | 41 | 19 | 23 | 41 | 33 | 20 | 0 | 36 | 1 | 6 | 1 | 1 |
| tufts | 37 | 38 | 40 | 17 | 40 | 34 | 0 | 40 | 40 | 18 | 17 | 40 |
| franciscan | 9 | 10 | 10 | 10 | 10 | 10 | 0 | 10 | 10 | 10 | 0 | 10 |
| bidmc | 42 | 29 | 0 | 0 | 33 | 0 | 0 | 4 | 0 | 0 | 0 | 8 |
| childrens | 28 | 28 | 28 | 28 | 28 | 28 | 0 | 28 | 0 | 28 | 0 | 0 |
| dana_farber | 0 | 29 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mtauburn | 42 | 29 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8 |

## Gates

| gate | subject | status | detail |
|---|---|---|---|
| staleness | bidmc_mrf | warn | last_updated_on 2026-04-01 (206 days) |
| staleness | bmc_brighton_mrf | warn | last_updated_on 2026-03-13 (225 days) |
| staleness | bmc_mrf | warn | last_updated_on 2026-03-13 (225 days) |
| staleness | brigham_mrf | warn | last_updated_on 2026-03-27 (211 days) |
| staleness | cha_mrf | warn | last_updated_on 2026-03-20 (218 days) |
| staleness | childrens_mrf | warn | last_updated_on 2026-04-01 (206 days) |
| staleness | dana_farber_mrf | warn | last_updated_on 2026-04-01 (206 days) |
| staleness | faulkner_mrf | warn | last_updated_on 2026-03-27 (211 days) |
| staleness | franciscan_mrf | warn | last_updated_on 2026-04-01 (206 days) |
| staleness | mgh_mrf | warn | last_updated_on 2026-03-27 (211 days) |
| staleness | mtauburn_mrf | warn | last_updated_on 2026-04-01 (206 days) |
| staleness | tufts_mrf | warn | last_updated_on 2026-04-01 (206 days) |
| anchor | brigham_11102_aetna_hmo_facility | pass | exact match required on the anchor file: want 417.4, got [417.4] |
| anchor | brigham_11102_aetna_hmo_professional | pass | exact match required on the anchor file: want 115.17, got [115.17] |
| anchor | bidmc_73030_bcbs_hmo | pass | exact match required on the anchor file: want 110.42, got [110.42] |

