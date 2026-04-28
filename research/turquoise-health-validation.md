# Turquoise Health — New Haven CT Pricing Data Validation

**Date:** 2026-03-28
**Purpose:** Validate real pricing data availability for hackathon demo
**ZIP:** 06510/06511 (New Haven, CT)
**Radius:** 50 miles (default)

## Key Finding: Data EXISTS and is RICH

Turquoise Health has extensive consumer-facing pricing data for the New Haven CT area. The data is real, verified, and free to access (no signup required).

## Important: Turquoise Uses SSP Codes, Not Raw CPT Codes

Turquoise's consumer tool uses their own "Standard Service Package" (SSP) codes that **bundle** multiple CPT/HCPCS codes into a single service package. For example:
- **NU002** = Carpal Tunnel Repair (bundles HCPCS 29848 + facility fees)
- **GA002** = Colonoscopy
- **MS006** = Knee Repair - Arthroscopic
- **RA005** = MRI without Contrast
- **RA004** = CT of abdomen and pelvis
- **EN004** = Tonsil and/or adenoid removal

They do NOT support raw CPT code search (99213, 99283, 99203) in the consumer tool. Those are E&M codes for office/ER visits which Turquoise doesn't package as shoppable services — this aligns with the CMS shoppable services mandate which focuses on procedural services.

## Search Results Summary

### 1. Carpal Tunnel Repair (SSP NU002)
- **Results:** 17 providers
- **Price range:** $1,177 — $8,742 (cash/self-pay)
- **Midpoint:** $4,595
- **Closest CT facilities:**
  - Griffin Hospital, Derby CT (9 mi) — $1,913
  - Saint Marys Hospital, Waterbury CT (18 mi) — $1,177
  - Saint Francis Hospital, Hartford CT (34 mi) — $1,177
- **Notable:** Yale-New Haven Hospital NOT listed for this procedure

### 2. Colonoscopy (SSP GA002)
- **Results:** 31 providers (2 pages)
- **Price range:** $580 — $7,966 (cash/self-pay)
- **Midpoint:** $2,295
- **Yale-New Haven Health system facilities:**
  - **Yale New Haven Hospital** — New Haven, CT (2 mi) — $1,899, CMS Rating: 4
  - **Yale New Haven Hospital - St Raphael Campus** — New Haven, CT (1 mi) — $1,899
  - **Yale New Haven Childrens Hospital** — New Haven, CT (1 mi) — $1,899
  - **Smilow Cancer Hospital at Yale New Haven** — New Haven, CT (2 mi) — $1,899
  - **Yale New Haven Childrens Hospital - Bridgeport Campus** — Bridgeport, CT (15 mi) — $1,674
- **Other nearby CT facilities:**
  - Griffin Hospital, Derby CT (9 mi) — $1,410
  - Bridgeport Hospital, Bridgeport CT (15 mi) — $1,641
  - Bridgeport Hospital Milford Campus, Milford CT (10 mi) — $1,674
  - Waterbury Hospital, Waterbury CT (19 mi) — $1,646
  - Greenwich Hospital, Greenwich CT (41 mi) — $1,674
  - Lawrence & Memorial Hospital, New London CT (43 mi) — $1,867
  - Stamford Hospital, Stamford CT (37 mi) — $3,066

### 3. MRI without Contrast (SSP RA005)
- **Results:** 38 providers (2 pages)
- **Price range:** $270 — $7,045 (cash/self-pay)
- **Midpoint:** $1,133
- **Yale-New Haven Health system facilities:**
  - **Smilow Cancer Hospital at Yale New Haven** — New Haven, CT (2 mi) — $1,182
  - **Yale New Haven Childrens Hospital - Bridgeport Campus** — Bridgeport, CT (15 mi) — $1,042
  - Bridgeport Hospital, Bridgeport CT (15 mi) — $1,022
  - Bridgeport Hospital Milford Campus, Milford CT (10 mi) — $1,042
  - Greenwich Hospital, Greenwich CT (41 mi) — $1,042
- **Other nearby CT facilities:**
  - Griffin Hospital, Derby CT (9 mi) — $289
  - Stamford Hospital, Stamford CT (37 mi) — $270
  - Norwalk Hospital, Norwalk CT (29 mi) — $1,083
  - Lawrence & Memorial Hospital, New London CT (43 mi) — $895

### 4. Knee Repair - Arthroscopic (SSP MS006)
- **Results:** 24 providers (2 pages)
- **Price range:** $1,773 — $17,287 (cash/self-pay)
- **Midpoint:** $4,595
- **Nearby CT facilities:**
  - Griffin Hospital, Derby CT (9 mi) — $3,879
  - MidState Medical Center, Meriden CT (18 mi) — $3,725
  - Hospital of Central CT - Bradley Campus, Southington CT (20 mi) — $2,945
  - Hartford Hospital, Hartford CT (33 mi) — $2,945
  - Charlotte Hungerford Hospital, Torrington CT (35 mi) — $3,250
- **Notable:** Yale-New Haven NOT listed for this procedure in first page

## Data Quality Notes

1. **Prices shown are CASH/SELF-PAY (no insurance)** — "max estimated amount you'd pay without insurance"
2. **Insurance personalization available** — users can add their insurance to get personalized out-of-pocket estimates
3. **Verification methodology:** Prices are "fully verified" when confirmed by both provider and insurer with low variability; "partially verified" when from one source corroborated by claims data
4. **Bundled pricing** — each SSP includes facility fees + professional fees (e.g., Carpal Tunnel = 9 bundled line items including HCPCS codes, Revenue Codes for OR, recovery room, pharmacy, etc.)
5. **Quality scores** — CMS ratings (1-5 stars) shown per provider
6. **Price comparison indicators** — "Significantly lower", "Slightly lower", "Slightly higher", "Significantly higher" relative to midpoint

## Payer Data

The consumer tool shows **cash prices by default**. Payer-specific rates are available when users "Add Insurance" — this triggers a coverage check. The enterprise product (Analyze platform) has full payer-specific rate transparency.

Insurance plans are being added "on a rolling basis." Government plans (Medicare/Medicaid) are explicitly excluded from the consumer tool.

## API / URL Pattern

Consumer search URL pattern:
```
https://turquoise.health/care/search/?service={SSP_CODE}&action=common-service&plan=specified-no-plan
```

Provider detail URL pattern:
```
https://turquoise.health/care/service/{SSP_CODE}/provider/{PROVIDER_ID}/cost_breakdown/?plan=specified-no-plan
```

## Implications for Hackathon Demo

1. **Turquoise is the best free source** for real healthcare pricing data in New Haven CT
2. **Yale-New Haven Hospital is well-represented** (especially for common procedures like Colonoscopy, MRI)
3. **Price variance is dramatic** — e.g., MRI ranges from $270 to $7,045 (26x difference), which is exactly the problem we're solving
4. **Bundled pricing approach** is sophisticated and consumer-friendly
5. **No raw CPT search** — the tool uses SSP bundles, which is actually better for consumers
6. **Limitation:** No office visit (E&M) or ER visit pricing — those aren't "shoppable" services
7. **Scraping consideration:** Data is rendered client-side via React; would need API access or Playwright-based extraction for demo data
