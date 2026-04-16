# Scraping Summary — What Was Done, What Worked, What Didn't

> Reading order: this document is the honest, numbers-first summary of the
> scraping work. For the implementation-level detail (code layout, how to
> run), see [SCRAPING_AND_ENRICHMENT.md](./SCRAPING_AND_ENRICHMENT.md).

## The bottom line

- The source catalog (`data/cleaned_data.csv`, 292,640 rows) is already
  ~100 % covered by at least one descriptive text field. Spec-dense short
  descriptions exist for 84.9 % of rows.
- **Public web scraping is _not_ a meaningful enrichment source for this
  catalog.** After building and running scrapers against Grainger and
  Zoro, only **35 rows (0.012 % of the catalog)** gained genuinely novel
  information. 14 rows were wrong-match data pollution that had to be
  filtered out.
- The real dataset-level improvement — 14 new structured spec columns
  covering 46.6 % of rows — came from a _rule-based text extractor_ that
  parses the catalog's existing descriptions. No network required.

## Scraping attempts, in order

### 1. Grainger (first, most time invested)

- Built a scraper that pulls Grainger's embedded `<script type="application/json">`
  blob (search payload → candidate SKUs → per-SKU product payload).
- Used strict MFR-part-number matching after an earlier loose-match
  version produced obvious garbage (every Humphrey Products query was
  returning "Stacking Tie-Rod Kit").
- **Measured hit rate across the top 8 brands: ~0 %.** Grainger simply
  does not index the specialised hydraulic/pneumatic SKUs that dominate
  this catalog.

### 2. Parker direct (`ph.parker.com`)

- Tried six URL patterns, four ScraperAPI proxy tiers
  (`default`, `premium`, `ultra_premium`, `ultra_premium+render`).
- Every variant returned Akamai's `sec-if-cpt-container` interstitial
  challenge page instead of product HTML.
- **Conclusion: Parker is unscrapeable at the current ScraperAPI tier.**
  90 k parts (~31 % of the catalog) locked behind Akamai.

### 3. SMC direct

- Same Akamai issue. Scraper module kept in the tree but disabled in the
  pipeline.

### 4. Zoro (final source, integrated into pipeline)

- Built `scraper/parsers/zoro.py` — parses the clean JSON-LD `Product`
  schema Zoro ships on search/product pages, with strict MFR-PN matching.
- Ran a 1,050-row stratified sample across the top 15 brands.

| Cohort | Brands | Measured hit rate |
|--------|--------|-------------------|
| Hydraulic/pneumatic specialists | Bosch Rexroth, Versa, Hydac, Aventics, Hengli, Balluff, Daman, Graco | ~0 % |
| Mixed industrial | Parker, Schroeder | 5–20 % |
| Electrical / filter / instrumentation | Phoenix Contact, Donaldson, NOSHOK, Hengst, Bijur Delimon | 40–90 % |
| **Overall** | — | **9.7 %** |

### 5. MotionIndustries, Applied.com, other distributors

- MotionIndustries: consistent timeouts through ScraperAPI.
- Applied.com: reachable, but search returns "No Results" for the sampled
  parts. They don't carry this inventory either.

## Post-scrape quality analysis — why scraping was downgraded to "minor contributor"

After the Zoro sample landed 147 initial hits, I compared each scraped
description to the row's existing descriptive fields:

| Category | Definition | Count | % of scraped rows |
|----------|------------|-------|-------------------|
| **Wrong match (dropped)** | Scraped tokens share <15 % with existing text despite ≥10 existing tokens | **14** | **11.8 %** |
| Redundant | ≤1 new meaningful token beyond existing | 79 | 67 % |
| Partial novelty | 2 new tokens | 19 | 16 % |
| **Novel** | ≥3 new tokens or fills a genuinely empty row | **35** | **30 %** of kept rows |

Concrete wrong-match examples that were filtered out:

| Brand | Part number | Catalog says | Zoro returned |
|-------|------------|--------------|---------------|
| Graco | 562538 | MX-75S Trabon Divider Valve | "8' X 8' Taupe and Ivory Round Floral Area Rug" |
| Hydac | 2071761 | DF-Series In-Line Filter, 6090 PSI | "Solid Carbide Ball Nose End Mill, 260°, TiAlN" |
| Hydac | 2064907 | RF-Series Return Filter | "4 1/2 gal Oval Dirty Water Bucket" |
| Graco | 563526 | MXP Crossport Plate | "Patchwork Washable Indoor Outdoor Rug" |
| Phoenix Contact | 1648173 | HEAVYCON Test Plug | "Caterpillar Plate Assembly OEM 1648173" |

These are classic part-number collisions — a short numeric MFR PN that
happens to match an unrelated SKU on a distributor with a broader
catalog. Strict MFR matching catches the value field but can't catch
collisions; only a semantic sanity check can.

The sanity filter is now in `scraper/enrich.py::_is_suspicious_match`
and is applied automatically on export.

## What actually added value: the rule-based spec extractor

The catalog already contains strings like:

> TAC Valve, 3-Way, Normally Closed, 2-Position, Push Button, Spring Return,
> M5 X 0.8 Ports, Brass Body, NBR Seals, 0-125 PSI Pressure Range

`scraper/spec_extractor.py` pulls out 14 typed fields from these:

| New column | Rows filled | % of catalog |
|------------|-------------|--------------|
| `spec_port_size` | 75,329 | **25.7 %** |
| `spec_bore` | 59,929 | 20.5 % |
| `spec_stroke` | 59,492 | 20.3 % |
| `spec_body_material` | 50,287 | 17.2 % |
| `spec_pressure_psi_min` / `_max` | 23,929 |  8.2 % |
| `spec_voltage_v` | 20,137 |  6.9 % |
| `spec_seal_material` | 14,737 |  5.0 % |
| `spec_valve_ways` | 11,753 |  4.0 % |
| `spec_valve_positions` |  3,740 |  1.3 % |
| `spec_flow_value` / `_unit` | 475 | 0.2 % |
| `spec_temperature_f_min` / `_max` | 366 | 0.1 % |

Net effect: **136,299 rows (46.6 % of the catalog) gained at least one
typed spec column** — more than 1,000× the enrichment the web scraping
contributed.

## Deliverables

| File | Purpose |
|------|---------|
| `data/enriched_data.csv` (local, gitignored) | Final enriched catalog — 292,640 × 38 |
| `scraper/spec_extractor.py` | Regex-based typed-field extractor |
| `scraper/parsers/grainger.py` | Grainger scraper (strict MFR match) |
| `scraper/parsers/zoro.py` | Zoro scraper (strict MFR match, JSON-LD) |
| `scraper/enrich.py` | End-to-end driver with PN-collision sanity filter |
| `scraper/pipeline.py` | Async full-catalog web-scrape runner |
| `SCRAPING_AND_ENRICHMENT.md` | Implementation-level docs |
| `SCRAPING_SUMMARY.md` _(this file)_ | Honest outcome summary |

## Final verdict

**Did scraping meaningfully enrich the dataset? No — not as a standalone
source.**

- Direct contribution: 35 novel rows out of 292,640 (0.012 %).
- False-match risk: without the post-hoc sanity filter, 12 % of scraped
  rows would have polluted the data.
- The scraping infrastructure, however, is sound and resumable
  (ScraperAPI-aware client, SQLite cache, cohort-aware hit rate data).
  It's the right vehicle for targeted per-brand scrapers in the future
  (Daman, Humphrey, Schroeder direct sites).

**Did the overall enrichment work succeed? Yes — via the rule-based
extractor.** 46.6 % of catalog rows now have structured specs that the
recommender can consume directly (pressure, voltage, valve ways,
port size, bore, stroke, materials). That's the meaningful result.

Recommended next step for the recommender team: treat the `spec_*`
columns as first-class features; treat `scraped_description` as an
optional append to a row's text blob, not as a trusted source.
