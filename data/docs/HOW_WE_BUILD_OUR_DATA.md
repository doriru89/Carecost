# How We Build Our Data

> Healthcare prices exist in public databases — but no one has assembled them into something a normal person can use. We did.

---

## The Problem

Since 2021, two federal rules require price transparency:

- **Hospitals** must publish every negotiated rate with every insurer ([45 CFR 180](https://www.cms.gov/hospital-price-transparency))
- **Insurers** must publish what they pay every provider ([45 CFR 147.212](https://www.cms.gov/healthplan-price-transparency))

The data is public. But it was designed for compliance, not for you. Hospital files range from 1 MB to 5 GB, in inconsistent formats — CSV, JSON, Excel — with different column names, encodings, and bundling rules. Insurer files are 100+ MB compressed JSON streams. No consumer tool stitches them together.

**The result:** Turquoise Health and similar companies clean this data — for hospitals and employers. Your insurer has a cost estimator — locked behind their login, showing only their network. FAIR Health publishes regional benchmarks — averages, not your hospital's actual price.

**What's missing** is a single place where you can see every price source for a specific procedure at a specific hospital, labeled honestly, across insurers.

---

## Our Pipeline

We collect from **6 independent sources**, cross-validate, and show you everything — not a "best guess."

```
                        ┌──────────────────────────────────────────────────┐
                        │              What the consumer sees              │
                        │                                                  │
                        │   Hospital X — Skin Biopsy (CPT 11104)           │
                        │                                                  │
                        │   Gross charge .............. $1,183   [Hospital] │
                        │   Cash/self-pay ............. $592     [Hospital] │
                        │   BCBS negotiated ........... $487     [Hospital] │
                        │   BCBS insurer-reported ..... $56      [Insurer]  │
                        │   Harvard Pilgrim ........... $420     [Hospital] │
                        │   De-identified range .. $201 – $633   [Hospital] │
                        │   Regional benchmark ........ $496     [FAIR Health] │
                        │                                                  │
                        │   ⚠ Hospital and insurer BCBS rates differ.      │
                        │     Hospital rate is facility; insurer rate may   │
                        │     be professional component only.              │
                        │                                                  │
                        └──────────────────────────────────────────────────┘
                                             ▲
                                             │ merge + label + validate
                        ┌────────────────────┴───────────────────────┐
                        │          Our Data Pipeline                  │
                        │                                            │
                        │  ┌─ Clean each hospital's MRF format       │
                        │  ├─ Stream-parse insurer TiC files         │
                        │  ├─ Match providers via NPI registry       │
                        │  ├─ Cross-validate hospital vs insurer     │
                        │  ├─ Flag discrepancies with notes          │
                        │  └─ Attach regional benchmarks per CPT     │
                        └──────────────┬─────────────────────────────┘
                                       │
            ┌──────────┬──────────┬────┴────┬──────────┬──────────┐
            ▼          ▼          ▼         ▼          ▼          ▼
      ┌──────────┐┌──────────┐┌────────┐┌────────┐┌──────────┐┌──────────┐
      │ Hospital ││ Insurer  ││  FAIR  ││ Mass   ││Turquoise ││  NPPES   │
      │  MRFs    ││  TiC     ││ Health ││Compare ││  Health  ││(Doctors) │
      │          ││  Files   ││        ││  Care  ││          ││          │
      │ 13 files ││ 111 MB   ││ 80th % ││ Claims ││ Bundled  ││ Provider │
      │ per city ││ per      ││ bench- ││ data   ││ all-in   ││ names,   │
      │          ││ insurer  ││ marks  ││ (MA)   ││ prices + ││ addresses│
      │ Gross,   ││          ││        ││        ││ quality  ││ NPI,     │
      │ cash,    ││ Every    ││ ZIP-   ││ Real   ││ ratings  ││ specialty│
      │ per-plan ││ provider ││ level  ││ total  ││          ││          │
      │ rates    ││ × code   ││ fees   ││ paid   ││          ││          │
      └──────────┘└──────────┘└────────┘└────────┘└──────────┘└──────────┘
       Hospital     Insurer    Private    State     Private    Federal
       mandate      mandate    (50B+      APCD      (HPT+TiC   registry
       (federal)    (federal)  claims)    (MA law)  +claims)
```

---

## What Makes This Different

| What exists today | What we do differently |
|---|---|
| **Insurer portals** show your plan's estimate — but only for their network, behind a login | We show negotiated rates from **every insurer** at **every hospital**, side by side |
| **FAIR Health** publishes regional averages — useful as a benchmark, not as your price | We use FAIR Health as a **cross-reference**, not the primary number |
| **Turquoise Health** cleans transparency data — for hospitals and employers (B2B) | We take the same raw data and build a **consumer product** on top |
| **Hospital billing pages** post their MRF files — multi-GB, unreadable | We parse, standardize, and **label every number** by what it is and where it came from |

### We don't pick a "best" price. We show you all of them.

When a hospital says BCBS pays $487 and BCBS says they pay $56, both numbers appear — with a note explaining the likely reason (facility vs. professional component). You see the spread. You decide what matters.

---

## Coverage Today

| | Gastroenterology | Dermatology |
|---|---|---|
| **Hospitals** | 13 (Greater Boston) | 13 (Greater Boston) |
| **Procedures** | 17 CPT codes | 20 CPT codes |
| **Insurer rates** | BCBS, Aetna, Harvard Pilgrim, UHC | BCBS, Harvard Pilgrim, UHC |
| **Sources per row** | Up to 6 independent price points | Up to 5 independent price points |

### Expanding is a pipeline problem, not a research problem.

Every specialty uses the same 6 sources. Adding orthopedics or cardiology means:
1. Define the CPT codes
2. Re-run the parsers with new codes
3. Match providers via NPPES
4. Output the same standardized CSV

The infrastructure is built. The data is public. We just keep turning the crank.

---

## Why This Gap Still Exists

It's not that nobody thought of it. Three hard problems stack on top of each other:

**1. The data is genuinely messy.** Each hospital publishes in a different format, with different column names, different bundling rules, and varying compliance levels. Even Turquoise Health — a $100M+ company — spends most of its engineering on crosswalks, deduplication, and active-rate filtering.

**2. Showing prices without misleading people is hard.** A "negotiated rate" isn't your out-of-pocket cost. It depends on your deductible, coinsurance, whether you've hit your out-of-pocket max, and whether the rate covers the full service or just one component. Getting this wrong erodes trust fast.

**3. Insurers already own the member relationship.** BCBS Massachusetts has a cost estimator inside their member portal. So does every major insurer. The most actionable use case — "what will I actually pay?" — lives behind their login wall.

We solve #1 with specialty-specific parsing pipelines. We handle #2 by showing every price source with honest labels instead of collapsing them into a single estimate. And we address #3 by being the **cross-insurer, cross-hospital** view that no single insurer will ever build.
