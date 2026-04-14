# Web Scraper — Session Findings & Path Forward

*Last updated: 2026-04-14*

---

## What Was Built

A fully async scraping pipeline (`scraper/`) with:
- SQLite cache (`data/scrape_cache.db`) — pipeline is resumable, never re-scrapes already-cached parts
- Per-domain rate limiting (`scraper/http.py`)
- Grainger as primary source (`scraper/parsers/grainger.py`)
- Parker and SMC direct scrapers (`scraper/parsers/parker.py`, `smc.py`)
- Orchestrator with configurable concurrency (`scraper/pipeline.py`)
- CLI (`scripts/run_scraper.py`)

---

## What We Discovered

### The blocking problem

All major distributor and manufacturer sites use **Akamai Bot Manager**. Every approach we tried was blocked:

| Site | Approach | Result |
|---|---|---|
| grainger.com | httpx | Akamai error page (200 but junk HTML) |
| grainger.com | Playwright headless | Akamai block ("technical difficulty") |
| grainger.com | Playwright + playwright-stealth | Akamai block |
| ph.parker.com | httpx | 403 Forbidden |
| parker.com | Playwright | "Access Denied" |
| mscdirect.com | Playwright | Empty page (0 bytes) |

### What IS accessible

| Site | Status | Notes |
|---|---|---|
| versa-valves.com | ✅ Works | Returned content, no bot protection |
| smcusa.com | ⚠️ Partial | Wrong URL format used — needs investigation |
| humphreyproducts.com | ❌ Connection refused | Site may be down or offline |

---

## Why This Matters

The missing specs that hurt the model most:
- **PSI / pressure rating** — differentiates high-pressure from low-pressure valves
- **Voltage** — 12VDC vs 24VDC vs 120VAC are completely different products
- **Port size** — 1/4" NPT vs 3/8" NPT, incompatible fittings
- **Bore / stroke** — cylinders — defines actuator force and travel
- **Flow rate (Cv)** — determines if a valve can handle the required flow

~42% of valve rows are model-code-only with no parseable specs. These are the rows hurting accuracy most.

---

## Paths Forward (Ranked by Effort vs. Value)

### Option 1 — ScraperAPI or BrightData proxy ⭐ Recommended

Use a residential proxy service that handles Akamai bypass automatically. You send a normal HTTP request to their API endpoint, they handle rotating IPs and bot bypass.

- **ScraperAPI**: $49/month for 100k requests. Straightforward.
  ```python
  url = f"http://api.scraperapi.com?api_key={KEY}&url={target_url}"
  ```
- **BrightData**: More powerful, more expensive (~$500/month for 150GB).

This requires the least code change — just wrap the URL and add the API key.

### Option 2 — Focus on accessible manufacturer sites

Smaller manufacturers don't use Akamai. These brands have accessible sites worth building scrapers for:
- **Versa Products** (versa-valves.com) — confirmed working
- **SMC USA** — needs correct URL format (`/products/search/?partNumber=X`)
- **Aventics** (aventics.com) — not yet tested
- **Hydac** (hydac.com) — not yet tested
- **Bijur Delimon** (bijurdelimon.com) — not yet tested
- **Balluff** (balluff.com) — not yet tested
- **Schroeder Industries** — not yet tested

These cover ~60-80k rows in the catalog.

### Option 3 — Octopart API

Octopart aggregates specs from many distributors. Has a GraphQL API.
- Free: 1,000 queries/month (too low for 292k parts)
- Paid: contact for pricing

Best suited for the electrical/sensor families (Phoenix Contact, Balluff) since Octopart skews toward electronics.

### Option 4 — Automation Direct (automationdirect.com)

Large US automation distributor. Carries SMC, Parker accessories, sensors.
Not yet tested for bot protection — worth trying.

---

## Immediate Next Steps

1. **Test remaining accessible sites** — run the diagnostic script against Aventics, Hydac, Balluff, Bijur Delimon, Schroeder Industries
2. **Fix SMC URL format** — `https://www.smcusa.com/products/?q={part_number}` may be the correct endpoint
3. **Build Versa Products scraper** — confirmed accessible, 2nd largest brand in catalog after Parker
4. **Decision on proxy service** — if budget allows, ScraperAPI at $49/month would unblock Grainger and cover all brands

---

## Technical Notes

### How to run once scrapers are fixed
```bash
# Test 100 parts
python scripts/run_scraper.py --limit 100

# Check progress without running
python scripts/run_scraper.py --stats

# Full run (overnight — 292k parts at ~1.5s each)
python scripts/run_scraper.py --concurrency 30

# With ScraperAPI (faster, needs API key in .env)
python scripts/run_scraper.py --concurrency 80
```

### Cache structure
Results land in `data/scrape_cache.db` (SQLite). The pipeline skips `status='ok'` rows automatically — safe to kill and resume at any time.

### What happens after scraping
`data/enriched_data.csv` gets `web_*` columns merged in. Re-run `build_index.py` to rebuild the model with the enriched data. The `data_loader.py` will need to be updated to use `enriched_data.csv` instead of `cleaned_data.csv` (or the description column list updated to include `scraped_description`).
