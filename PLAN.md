# Enrichment Pipeline Plan

## Goal

Enrich `data/cleaned_data.csv` (292,640 rows) with structured product spec data scraped from the web.
Output: `data/mrostop_intermediate.csv` as the intermediate dataset — no merge into `enriched_data.csv` yet.

Budget: **1,000,000 ScraperAPI credits ($150)**

---

## What We Know About the Dataset

| Field | Filled | Coverage |
|---|---|---|
| `default_short_description` | 248,361 | 84.9% |
| `livhaven_description` | 229,712 | 78.5% |
| `mro_description` | 88,495 | 30.2% |
| `livhaven_short_description` | 56,187 | 19.2% |
| `manufacturer_description` | 38,133 | 13.0% |

`manufacturer_description` is the biggest gap at only 13% — this is the primary field we want to fill.
Only 1,335 rows (0.5%) are missing **all** description fields.

---

## Site Research Findings

We tested MROStop, Grainger, Zoro, RS Components, McMaster-Carr, Parker, and SMC.

### MROStop — Primary Target

- **140,706 product URLs** in their sitemap at `/media/sitemaps/` (accessible without render, no Akamai)
- **66,826 confirmed matches** between our catalog and the sitemap (exact slug match from `default_name`)
- Protected by **Akamai bot protection** on all product pages — requires `render=True` to bypass
- Without render: returns a JS challenge page (`aes.min.js`) — useless
- With `render=True`: returns full HTML (tested on MA6450, E3P) — works

URL construction: `default_name.lower()` → slugify → `https://www.mrostop.com/{slug}`

Fields available on MROStop pages:
| Field | Selector | Present on |
|---|---|---|
| `mro_name` | `h1` | Most pages |
| `mro_item_number` | `div.product-view__content` (Item # pattern) | Most pages |
| `mro_short_description` | `div.product-view__short-description` | Some pages |
| `mro_description` | `div.tab-content__wrapper.descriptions` | Most pages |
| `mro_manufacturer_description` | `div.tab-content__wrapper.manufacturer_description` | Most pages |
| `mro_attrs` | `div.tab-content__wrapper.attribute_table` table | Some pages (e.g. E3P yes, MA6450 no) |

### Other Sites Tested

| Site | Result | Why |
|---|---|---|
| Grainger | 0 specs, no product links | Full React app — product data requires `render=True` |
| Zoro | 208 bytes returned | Blocked entirely without render |
| RS Components | Akamai blocked | Same as MROStop but no sitemap found |
| McMaster-Carr | Pages load, 0 specs | URL pattern wrong for most of our parts |
| Parker (ph.parker.com) | 404 | Existing parser URL is outdated |
| SMC (smcusa.com) | 404 | Wrong URL format |

**Conclusion:** Everything useful requires `render=True`. No cheap 1-credit alternative found for now.
The only free source we found was MROStop's own sitemap (static XML in `/media/`).

---

## Credit Budget

| Mode | Cost per page | Pages from 1M credits |
|---|---|---|
| Basic (no render) | 1 credit | 1,000,000 |
| Render only | 10 credits | 100,000 |
| Premium + Render | 25 credits | 40,000 |

### Plan: Render only (`render=True`)

- 66,826 confirmed MROStop matches × 10 credits = **668,260 credits**
- Remaining: ~332,000 credits (~33,200 more renders)
- Total capacity: ~100,000 pages

---

## Value of Scraping the 66K Confirmed Matches

| Field | Already filled | Would be NEW |
|---|---|---|
| `mro_manufacturer_description` | 6,652 | **60,174** |
| `mro_description` | 51,371 | 15,455 |
| `default_short_description` | 39,934 | 26,892 |
| `livhaven_description` | 38,733 | 28,093 |

`mro_manufacturer_description` is the biggest win — 90% of the 66K confirmed matches would get a manufacturer description for the first time.

---

## Variant / Subtype Handling

MROStop sometimes has product family pages (e.g. E3P, E3P-1, E3P-2 on separate pages) and sometimes
family-level pages covering a range. Since our `default_name` includes the full part number, the constructed
URL slug is specific to that variant. If MROStop doesn't have that exact variant, we get a 404 — which the
cache marks as `not_found` and skips. No credit waste for confirmed misses since we're only targeting
sitemap-matched URLs.

Note: PDFs / datasheets on some pages contain richer spec data but parsing is complex (layout varies,
many are scanned images). Skip for now.

---

## Architecture

### Files to Build

**`scraper/scraperapi.py`**
Async HTTP wrapper around ScraperAPI. Handles retries, credit tracking, configurable render/premium flags.
Used instead of the direct `httpx` client in `scraper/http.py` for Akamai-protected sites.

**`scraper/parsers/mrostop.py`**
Async parser for MROStop product pages. Extracted and refactored from `scraper/testing/test_scrape_mro.py`.
Returns the standard `(status, description, specs, source)` tuple plus the extra MROStop fields.

**`scraper/enrich_mrostop.py`**
Main pipeline script:
1. Reads `data/cleaned_data.csv`
2. Loads confirmed sitemap matches from `data/mrostop_sitemap_urls.txt`
3. Checks SQLite cache — skips already-scraped parts (resumable on crash)
4. Submits URLs to ScraperAPI async batch API (`async.scraperapi.com/batchjobs`, 50K per batch)
5. Polls for completion, parses HTML locally as results arrive
6. Writes `data/mrostop_intermediate.csv` progressively every 5,000 rows
7. Final export when complete

### Intermediate Dataset Schema (`mrostop_intermediate.csv`)

| Column | Source |
|---|---|
| `manufacturer_part_number` | catalog |
| `brand_name` | catalog |
| `mro_url` | constructed from `default_name` |
| `mro_item_number` | scraped |
| `mro_name` | scraped (h1) |
| `mro_description` | scraped |
| `mro_manufacturer_description` | scraped |
| `mro_short_description` | scraped |
| `mro_attrs` | scraped (JSON string of key/value spec table) |

### Resumability

All scraped results stored in SQLite (`data/scrape_cache.db`) with status `ok | not_found | error`.
Re-running the pipeline skips anything already cached. Safe to interrupt and restart.

---

## Phased Execution

### Phase 1 — MROStop (Tonight)
- Target: 66,826 sitemap-confirmed URLs with `render=True`
- Priority order: rows missing `mro_manufacturer_description` first (60,174 rows)
- Output: `data/mrostop_intermediate.csv`
- Credits used: ~668K of 1M

### Phase 2 — Fix Manufacturer Site Parsers (Next)
- Parker: 90,965 rows in catalog. Existing `scraper/parsers/parker.py` has outdated URLs — needs fixing.
- SMC: similar issue. Fix parser URL format.
- These may work without render (1 credit each) — need to verify with correct URLs.
- Parker alone could cover ~91K rows if accessible.

### Phase 3 — Extend MROStop Coverage (If Credits Remain)
- Use remaining ~332K credits to attempt fuzzy-matched or brand-prioritized rows not in the sitemap
- Or apply to other sites once Phase 2 parsers are validated

---

## Open Questions

1. **Do Parker/SMC sites work without render?** The existing parsers have outdated URLs and need testing with the correct endpoints before Phase 2 can begin.
2. **How many MROStop pages actually have `attribute_table`?** We only tested 2 pages (E3P: yes, MA6450: no). The proportion affects how much structured spec data we actually get.
3. **Fuzzy sitemap matching:** 225K catalog rows didn't exact-match the sitemap. Some of these may be on MROStop with slightly different slug formatting (special characters, abbreviations). A fuzzy match pass could recover more confirmed URLs before spending render credits.
4. **Merge strategy:** Once we have `mrostop_intermediate.csv`, how do we merge it back into `enriched_data.csv`? Key join: `manufacturer_part_number` + `brand_name`. Decide on conflict resolution (overwrite vs. fill-blank-only).
