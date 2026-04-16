# Scraping & Enrichment Pipeline

This document describes the data-enrichment work done on the Hyde Park
recommender catalog: what we tried, what worked, what didn't, and where
the current output lives.

## TL;DR

- **Source catalog:** `data/cleaned_data.csv` — 292,640 parts × 22 columns.
- **Enriched output:** `data/enriched_data.csv` — 292,640 parts × 38 columns.
- **Dominant enrichment source:** a rule-based extractor that parses the
  catalog's existing description text into 14 structured spec columns. This
  requires zero network access and adds features to 25.7 % of rows on its
  best-covered column (`spec_port_size`).
- **Web scraping:** a working Zoro scraper was built (`scraper/parsers/zoro.py`)
  and wired into the pipeline. The real-world hit rate against this highly
  specialised hydraulic / pneumatic catalog is ~3–7 %, so scraping is a
  secondary signal, not the primary one.

## Why web scraping was not the silver bullet

The catalog is dominated by specialist industrial parts — hydraulic
fittings, pneumatic valves, filter elements, directional valves — sold
through niche distributors rather than broad MRO catalogs.

| Source            | Notes                                                          | Status |
|-------------------|----------------------------------------------------------------|--------|
| **Grainger**      | Embedded JSON works, but search rarely returns an exact MFR PN match for these specialised SKUs. A "loose" match pattern (used in an earlier iteration) produced unrelated results (e.g. "Stacking Tie-Rod Kit" for every Humphrey Products query). Strict MFR-PN matching gives ~0 % on the top 8 brands. | ✅ Built, kept strict — low hit rate |
| **Parker direct** (`ph.parker.com`) | Protected by Akamai Bot Manager. Even with ScraperAPI `ultra_premium=true` + JS render, Akamai serves an interstitial challenge page (`sec-if-cpt-container`). Consistent failure. | ❌ Blocked |
| **Zoro**          | Clean JSON-LD `Product` schema, easy to parse. Carries Parker, a handful of Schroeder / Hydac / Aventics parts. Does not carry Bosch Rexroth, Versa, Hengli, Balluff, Daman, Graco for the sampled part numbers. | ✅ Built — ~3–7 % hit rate |
| **MotionIndustries** | Consistent request timeouts (via ScraperAPI). | ❌ |
| **Applied.com**   | Works but returns "No Results" for most sampled parts. | ❌ — no inventory |

**Conclusion:** for this catalog, the best hit rate from any single public
distributor was ~7 %. Web scraping is kept as an additive source, not the
primary engine.

## Where the structured spec columns come from

The catalog already contains rich short descriptions, e.g.:

```
TAC Valve, 3-Way, Normally Closed, 2-Position, Push Button, Spring Return,
M5 X 0.8 Ports, Brass Body, NBR Seals, 0-125 PSI Pressure Range
```

`scraper/spec_extractor.py` applies conservative regex rules to pull typed
features out of these sentences. Conservative = "emit `None` rather than
guess," so the model does not learn from noise.

### Extracted columns and coverage

Applied across all 292,640 rows:

| Column                       | Rows filled | Coverage |
|------------------------------|-------------|----------|
| `spec_port_size`             | 75,329      | 25.7 %   |
| `spec_bore`                  | 59,929      | 20.5 %   |
| `spec_stroke`                | 59,492      | 20.3 %   |
| `spec_body_material`         | 50,287      | 17.2 %   |
| `spec_pressure_psi_min`      | 23,929      |  8.2 %   |
| `spec_pressure_psi_max`      | 23,929      |  8.2 %   |
| `spec_voltage_v`             | 20,137      |  6.9 %   |
| `spec_seal_material`         | 14,737      |  5.0 %   |
| `spec_valve_ways`            | 11,753      |  4.0 %   |
| `spec_valve_positions`       |  3,740      |  1.3 %   |
| `spec_flow_value` / `_unit`  |    475      |  0.2 %   |
| `spec_temperature_f_min/max` |    366      |  0.1 %   |

### Example (Humphrey Products E3P)

| Raw description                                         | Extracted fields |
|---------------------------------------------------------|------------------|
| "TAC Valve, 3-Way, Normally Closed, 2-Position, Push Button, Spring Return, M5 X 0.8 Ports, Brass Body, NBR Seals, 0-125 PSI Pressure Range" | `spec_valve_ways=3`, `spec_valve_positions=2`, `spec_pressure_psi_min=0`, `spec_pressure_psi_max=125`, `spec_body_material=Brass`, `spec_seal_material=NBR` |

## Code layout

```
scraper/
├── http.py                  ScraperAPI-aware async HTTP client + rate limiter
├── cache.py                 SQLite resume cache (data/scrape_cache.db)
├── spec_extractor.py        Rule-based spec extractor (no network)
├── enrich.py                Top-level enrichment pipeline
├── pipeline.py              Full-catalog async scrape runner
└── parsers/
    ├── grainger.py          Grainger JSON-blob scraper (strict MFR match)
    ├── zoro.py              Zoro JSON-LD Product scraper (strict MFR match)
    ├── parker.py            Disabled — Akamai-protected, no viable bypass
    └── smc.py               Disabled — same reason
```

## Running it

```bash
# One-shot enrichment (no network — ~1 minute on 292 k rows)
python -m scraper.enrich

# Optional: run the async web-scrape pipeline against the full catalog
# (Requires SCRAPERAPI_KEY in .env. Costs API credits. Hit rate ~3–7 %.)
python -m scraper.pipeline
```

`data/enriched_data.csv` is the recommended input for downstream modelling.

## Dataset shape after enrichment

| Metric                                      | Value     |
|---------------------------------------------|-----------|
| Rows                                        | 292,640   |
| Columns (original → enriched)               | 22 → 38   |
| Rows with **at least one** extracted spec   | 136,299 (46.6 %) |
| Rows with web-scraped description (from a 1,050-row Zoro sample) | 119 (9.7 % sample hit rate) |

### Measured Zoro hit rate by brand (1,050-row stratified sample)

Brands fall into three cohorts:

- **Hydraulic / pneumatic specialists → ~0 %**: Bosch Rexroth, Versa
  Products, Hydac, Aventics, Hengli, Balluff, Daman Products, Graco
  (Zoro simply doesn't index these SKUs).
- **Mixed industrial → 5–20 %**: Parker, Schroeder Industries.
- **Electrical / filter / instrumentation → 40–90 %**: Phoenix Contact,
  Donaldson, NOSHOK, Hengst Filtration, Bijur Delimon. These are the
  brands where web scraping does pay off.

The pipeline is resumable (SQLite cache at `data/scrape_cache.db`), so a
larger run can continue from the 1,050-part sample without repeating work.

## Known limitations

1. **Regex extraction is conservative.** Some rows have the spec in the
   text but the pattern doesn't catch it (e.g. non-standard unit notation,
   ambiguous phrases). Recall is the tradeoff for high precision.
2. **Web scraping is ~3–7 %.** For the long tail of specialised parts we
   have no general distributor-based enrichment path.
3. **Temperature and flow coverage is very low** (~0.1–0.2 %) because these
   fields rarely appear in the catalog's short-description text. Parser
   improvements won't help here — the data isn't present.

## Next steps (if additional coverage is desired)

- Build manufacturer-specific scrapers for brands that operate
  unprotected sites (e.g. Daman, Humphrey, Schroeder). Expected per-brand
  hit rate: 60-90 %, covering maybe 5-10 % of catalog rows.
- Use a search-engine API (ScraperAPI's Google endpoint) to find the
  canonical manufacturer product URL per part, then follow it.
- Expand the regex rule set for `spec_extractor.py` as concrete gaps are
  surfaced by downstream modelling.
