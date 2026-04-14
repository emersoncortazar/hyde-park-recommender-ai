# Hyde Park MRO — AI Part Interchange Recommender
## Complete Project Documentation

*Last updated: 2026-04-14 — covers all work completed to date*

---

## Table of Contents

1. [What We Are Building](#1-what-we-are-building)
2. [The Dataset](#2-the-dataset)
3. [Repository Structure](#3-repository-structure)
4. [Phase 1 — Data Cleaning](#4-phase-1--data-cleaning)
5. [Phase 2 — Attribute Extraction](#5-phase-2--attribute-extraction)
6. [Phase 3 — The Recommender Model](#6-phase-3--the-recommender-model)
7. [Phase 4 — Web Scraping Pipeline](#7-phase-4--web-scraping-pipeline)
8. [How to Run Everything](#8-how-to-run-everything)
9. [Current Status & What's Left](#9-current-status--whats-left)
10. [Key Technical Decisions & Why](#10-key-technical-decisions--why)
11. [Known Problems & Limitations](#11-known-problems--limitations)

---

## 1. What We Are Building

An **AI-powered part interchange recommender** for Hyde Park / Livingston & Haven's MRO product catalog.

### The business problem

When a customer needs an industrial part that is out of stock, discontinued, or too expensive, someone on the sales or procurement team currently searches for alternatives manually. That search involves knowing what specs actually matter for a given part type, understanding which competing brands make compatible versions, and comparing across 292,000 products. It is slow, inconsistent, and dependent on individual expertise.

### What we are building to solve it

A system that, given a specific part (identified by brand + part number), automatically returns a ranked list of substitute parts from other manufacturers, each tagged with a confidence level:

- **Green** — strong structural spec match, high confidence this is a drop-in substitute
- **Yellow** — partial spec match, likely compatible but worth verifying one or two specs
- **Red** — same product category, specs partially overlap, requires human review

The output is designed to support — not replace — the technical team. It narrows a 292k-product search to 5–10 ranked candidates. A human reviews the top suggestions rather than searching from scratch.

### What makes this hard

This catalog spans 20+ product families that have nothing in common with each other. A valve, a cylinder, a hydraulic filter, and a proximity sensor each have completely different specs that define compatibility. A simple text similarity search would conflate a "3-way valve" with a "3-way coupler." Getting this right requires structured attribute matching — knowing that for valves, port size, way-count, and seal material are what define compatibility, while for cylinders it is bore diameter, stroke length, and acting type.

---

## 2. The Dataset

### Source

Exported from the MRO/Livingston & Haven product management system. Provided as `data/raw_data.csv`.

### Scale

- **292,640 parts** across **53 unique brands** (after normalization)
- **87 raw columns** — reduced to 22 meaningful columns after cleaning
- **20+ product families** (attribute families)

### Top brands by part count

| Brand | Parts |
|---|---|
| Parker | 90,965 |
| Bosch Rexroth | 37,420 |
| Versa Products | 22,880 |
| Hydac | 22,877 |
| Aventics | 15,087 |
| Hengli | 15,052 |
| Balluff | 14,543 |
| Schroeder Industries | 9,491 |
| Daman Products | 7,253 |
| Graco | 7,065 |
| SMC | ~5,000 |
| Humphrey Products | ~3,000 |

### Top product families by part count

| Family | Parts | Notes |
|---|---|---|
| Valves & Accessories | 78,355 | Largest — most complex matching problem |
| Cylinders & Accessories | 63,929 | Best structured data (93% have bore/stroke) |
| Hydraulic Filters & Fluid Conditioning | 31,692 | |
| Fittings | 13,213 | |
| Air Preparation | 12,696 | |
| Sensors & Accessories | 12,540 | Highly variable format |
| Electrical Panel Components | 11,805 | |
| Lubrication Systems | 8,924 | |
| Mechanicals | 6,771 | |
| Servo Motors, Drives & Accessories | 5,185 | |
| *(others — 10 families)* | ~48,000 | |

### The key data quality problem

The `default_short_description` column is the primary source of specs. It is filled 84.9% of the time, but what is inside it varies dramatically:

**Type 1 — Structured spec list (~29% of valves, ~93% of cylinders):**
```
3-Way, Normally Closed, 2-Position, Push Button, Spring Return,
M5 X 0.8 Ports, Brass Body, NBR Seals, 0-125PSI Pressure Range
```

**Type 2 — Model code / reference only (~71% of valves):**
```
Similar To: 4WE10Y3X/EG24N9K4/V  Model Code: 4WE...
```
No extractable specs whatsoever.

**Type 3 — Plain name only:**
```
Pneumatic Directional Valve
```

This distribution means the model has excellent data for cylinders, partial data for valves, and near-zero structured data for the model-code-only rows. The web scraping pipeline (Phase 4) was started specifically to fill this gap.

Other fill rates:
- `manufacturer_description`: 13.0% — highest quality but sparsest
- `mro_description`: 30.2% — marketing copy, low extraction value

---

## 3. Repository Structure

```
hyde-park-recommender-ai/
│
├── data/                           ← gitignored — not committed
│   ├── raw_data.csv                  Input: 292,640 rows × 87 columns
│   ├── cleaned_data.csv              Output of clean_data.py: 292,640 rows × 22 columns
│   ├── processed/
│   │   └── parts_with_attrs.csv      Output of attribute_extraction.ipynb (partial)
│   └── scrape_cache.db               SQLite cache for web scraper results
│
├── models/                         ← gitignored — generated artifacts
│   ├── recommender.joblib            Trained TF-IDF model (~140 MB)
│   └── catalog.parquet               Processed catalog with normalized text (~108 MB)
│
├── notebooks/
│   ├── cleaning_pipeline.ipynb       Original iterative cleaning notebook (reference)
│   ├── attribute_extraction.ipynb    Attribute extraction work in progress
│   ├── eda.ipynb                     Exploratory data analysis (Python)
│   └── data_analysis_products.qmd   Exploratory data analysis (R / Quarto)
│
├── scripts/
│   ├── clean_data.py                 Phase 1: Raw → cleaned CSV (runs in ~60s)
│   ├── build_index.py                Phase 3: Cleaned CSV → trained model
│   ├── query.py                      Phase 3: CLI to query the trained model
│   └── run_scraper.py                Phase 4: Web scraper CLI
│
├── src/
│   ├── data_loader.py                Loads catalog CSV, builds normalized text field
│   ├── normalize_specs.py            Synonym normalization rules for TF-IDF
│   ├── recommender.py                Core TF-IDF recommender class
│   ├── confidence.py                 Confidence tier logic (Green/Yellow/Red)
│   └── __init__.py
│
├── scraper/
│   ├── cache.py                      SQLite-based result cache
│   ├── http.py                       Async HTTP client with rate limiting & retry
│   ├── pipeline.py                   Async orchestrator — batch-processes full catalog
│   └── parsers/
│       ├── grainger.py               Grainger scraper (primary — blocked by Akamai)
│       ├── parker.py                 Parker direct (blocked by Akamai)
│       └── smc.py                    SMC direct (URL format needs fixing)
│
├── playbooks/
│   └── train-recommender.md          Step-by-step guide with validation criteria
│
├── environment.yml                   Conda environment (Python 3.12)
├── README.md                         Quick-start guide
├── FINDINGS.md                       Business-facing technical summary
├── SCRAPER_FINDINGS.md               Scraper session findings & next steps
└── PROJECT_OVERVIEW.md               This file
```

---

## 4. Phase 1 — Data Cleaning

**Script:** `scripts/clean_data.py`
**Input:** `data/raw_data.csv` (292,640 rows, 87 columns)
**Output:** `data/cleaned_data.csv` (292,640 rows, 22 columns)
**Run time:** ~60–90 seconds

### What it does (7 stages)

#### Stage 1: Column selection
The raw export contains 87 columns. Most are CMS/SEO metadata: no-index flags, slugs, storefront-specific feature flags, tax codes, all-null fields. We keep 20 columns that contain actual part information.

Key columns kept:
- `sku` — internal product identifier
- `brand_name` — manufacturer name
- `manufacturer_part_number` — the part number as the manufacturer defines it
- `attribute_family` — high-level product category group
- `category_name` — specific product category
- `default_name` — product name
- `default_short_description` — comma-separated spec list (primary extraction source)
- `manufacturer_description` — technical prose from manufacturer
- `mro_description` / `livhaven_description` — storefront marketing copy
- `last_sold_price` — most recent transaction price
- `item_weight` — part weight

Columns explicitly dropped and why:
- `mro_description` / `livhaven_description` — These look like product descriptions but every row starts with boilerplate: *"MROStop is the Humphrey distributor you can trust..."*. No spec value.
- `livhaven_short_description` — Near-exact duplicate of `default_short_description`.
- `attribute_table` — Present in column list, empty for all 292,640 rows.
- 65 other CMS columns — Slugs, no-index flags, guest-hide flags, tax codes, feature flags.

#### Stage 2: Brand name normalization
The same manufacturer appears under multiple spellings. Parker alone had 9 variants in the raw data:

```
"parker pneumatic division" → "Parker"
"parker pneumatic"          → "Parker"
"parker frl"                → "Parker"
"parker finite"             → "Parker"
"parker hose"               → "Parker"
"parker hannifin"           → "Parker"
"parker-hannifin"           → "Parker"
"parker transair"           → "Parker"
"parker-commercial intertech" → "Parker"
```

This normalization is **critical** — if `"Parker"` and `"parker pneumatic division"` are treated as different brands, the recommender will miss valid cross-brand substitutes and incorrectly identify same-brand matches as cross-brand.

The original raw value is preserved in `brand_name_raw` for audit purposes. The `BRAND_ALIASES` dictionary in `clean_data.py` covers all 53 brands.

#### Stage 3: Part number normalization
- Uppercased and whitespace-stripped
- Quality flags added: `pn_flag = 'too_short'` (< 4 chars) or `'too_long'` (> 30 chars)
- Missing part numbers flagged with `missing_pn = True`

#### Stage 4: Numeric sanity checks
- `last_sold_price` and `item_weight` coerced to float
- Zero prices set to NaN (zero price = bad data, not a free product)
- Negative values flagged

#### Stage 5: HTML stripping
Multiple description columns contained raw HTML and HTML entities from the CMS export:
```html
<p>3-Way Valve &amp; Accessories &mdash; Push Button&hellip;</p>
```
A custom `HTMLParser` subclass strips tags and decodes entities (`&amp;` → `&`, `&hellip;` → `...`, `&mdash;` → `--`, etc.). Two-pass approach: strip tags first, then decode entities.

#### Stage 6: Attribute table parsing
The `attribute_table` column (when populated) contains pipe-delimited key-value pairs:
```
Label | | | | Value | | | | Label | | | | Value ...
```
We parse this into individual `attr_*` columns, keeping only keys present in ≥ 1% of rows (to avoid creating hundreds of near-empty sparse columns).

#### Stage 7: Deduplication
For rows sharing the same `(brand_name, manufacturer_part_number)` — which represents genuine duplicates across storefronts — we keep the row with the most non-null values (richest record). Rows with missing part numbers are kept separately for human review.

---

## 5. Phase 2 — Attribute Extraction

**Notebook:** `notebooks/attribute_extraction.ipynb`
**Input:** `data/cleaned_data.csv`
**Output:** `data/processed/parts_with_attrs.csv`
**Status:** In progress — 2 of 8+ families complete

### Why this phase exists

A text-similarity recommender that only looks at raw description text would equate a "3-Way valve" with a "3-Way coupler." We need to extract structured, machine-comparable attributes so the recommender can do precise matching — not just word proximity.

### Architecture: FamilyExtractor

Each product family gets its own `FamilyExtractor` class. Patterns are written **only** for observed data — no pattern is assumed to generalize across families. The workflow for each family is:

1. **Diagnose** — sample 50-100 descriptions, understand what formats exist
2. **Extract** — write regex patterns targeting what was observed
3. **Audit** — spot-check extracted values against source text, report coverage

A null extraction is always preferable to an incorrect one.

### Family 1: Valves and Accessories (78,355 rows)

Coverage reality: only **29%** of valve rows have structured spec text. 71% are model-code-only (Bosch Rexroth, Parker manifold codes, etc.) with no parseable specs.

Attributes extracted from the 29% that do have specs:

| Attribute | Example | Pattern Target |
|---|---|---|
| `has_structured_specs` | True/False | Flag — gates downstream logic |
| `ways` | `3` | "3-Way" |
| `positions` | `2` | "2-Position" |
| `solenoid_type` | `Single` | "Single Solenoid" |
| `return_type` | `Spring Return` | "Spring Return", "Detent" |
| `port_thread` | `1/4" NPT` | Fractional sizes + metric (M5 X 0.8) |
| `seal_material` | `NBR` | "NBR Seals", "FKM Seals", etc. |
| `body_material` | `Brass` | "Brass Body", "Aluminum Diecast Body" |
| `voltage` | `24VDC` | "24VDC", "120VAC" |
| `pressure_max_psi` | `3-150PSI` | Pressure ranges |
| `cv_flow` | `2.00` | "2.00 Cv" |
| `mounting_type` | `Manifold` | "Manifold Mount", "Inline" |

### Family 2: Cylinders and Accessories (63,929 rows)

Coverage reality: **93%** of cylinder rows have parseable bore and stroke specs — the most consistently structured family in the dataset.

Attributes extracted:

| Attribute | Example | Pattern Target |
|---|---|---|
| `acting_type` | `Double` | "Double-acting", "Single-acting" |
| `construction_type` | `Nfpa Tie-Rod` | "NFPA tie-rod", "compact", "stainless steel" |
| `bore_inch` | `2` | `2" bore`, `(B2")` |
| `stroke_inch` | `5` | `5" stroke`, `(S5")` |
| `port_size_npt` | `3/8` | `3/8" NPT` |
| `rod_thread` | `3/4"-16 UNF` | UNC/UNF and metric rod threads |
| `has_piston_magnet` | `Yes` | "piston magnet" presence |
| `cushion` | `Both Ends` | Cushion location |
| `piston_seal` | `Lipseal` | "LipSeal", "O-Ring", etc. |

### Families still to build

Listed in priority order by row count, all scaffolded in the notebook:

| Family | Rows | Notes |
|---|---|---|
| Hydraulic Filters & Fluid Conditioning | 31,692 | |
| Fittings | 13,213 | |
| Air Preparation (FRLs) | 12,696 | |
| Sensors & Accessories | 12,540 | Highly variable — diagnose carefully |
| Electrical Panel Components | 11,805 | |
| Lubrication Systems | 8,924 | |
| *(others)* | ~48,000 | |

---

## 6. Phase 3 — The Recommender Model

**Files:** `src/`, `scripts/build_index.py`, `scripts/query.py`
**Input:** `data/cleaned_data.csv`
**Output:** `models/recommender.joblib`, `models/catalog.parquet`
**Contributed by:** evelindsayyy (teammate, commit `1436f76`)

This is the working v1 model. It runs today and produces validated results.

### Architecture overview

```
Query part (brand + part number)
         ↓
   Lookup in catalog DataFrame
         ↓
   Filter candidates:
     - Tier 1: same category_name (Green/Yellow candidates)
     - Tier 2: same attribute_family, excluding parts/accessories (Red candidates)
         ↓
   Compute cosine similarity against candidate subset only
   (not the full 292k — fast even at scale)
         ↓
   Score and rank by confidence tier
         ↓
   Return top-N results
```

### Stage 1: Text normalization (`src/normalize_specs.py`)

Before TF-IDF vectorization, descriptions are normalized so equivalent specs use consistent tokens. This is what allows cross-brand matching to work — Parker says "palm button," Humphrey says "push button," Versa says "push-button" — all become `push-button` after normalization.

Key rules:
```
"three-way"     → "3-way"
"palm button"   → "push-button"
"push button"   → "push-button"
"foot pedal"    → "foot-pedal"
"differential pilot return" → "spring-return"
"spring return"  → "spring-return"
"maintained"    → "detent"
"NBR seals"     → "seal-nbr"
"viton seals"   → "seal-fkm"
"1/4\" NPT"     → "port-1-4-npt"
"3/8\" NPT"     → "port-3-8-npt"
"M5 x 0.8"     → "port-m5"
"aluminum body" → "body-aluminum"
"brass body"    → "body-brass"
"24VDC"        → "voltage-24v"
"120VAC"       → "voltage-120vac"
"2\" bore"     → "bore-2mm" (for cylinders)
```

### Stage 2: TF-IDF indexing (`src/recommender.py`)

One TF-IDF matrix built over all 292k parts at fit time:
- `max_features=30,000`
- `ngram_range=(1, 2)` — captures two-word phrases like "spring return"
- `sublinear_tf=True` — prevents very common words from dominating
- `min_df=2` — ignores terms appearing in only one product

Matrix is L2-normalized so dot product equals cosine similarity. At query time, similarity is computed **only against the candidate subset** (same category or same family), not the full 292k. This keeps query time fast.

### Stage 3: Confidence scoring (`src/confidence.py`)

Hybrid scoring — primary signal is structural attribute matching, secondary is cosine similarity.

The key insight: **pure cosine similarity produces misleading tiers for cross-brand matching.** A Versa Products valve with terse descriptions may score only 0.20 against a well-described Humphrey valve — not because it's a bad match, but because Versa writes shorter specs. Counting shared canonical spec tokens (the normalized tokens from `normalize_specs.py`) is a more reliable compatibility signal than raw text similarity.

**Tier logic:**

```
Same category AND both sides have structured attributes (2+ canonical tokens):
  shared_attrs >= 3  →  GREEN  (unless way-count mismatch → YELLOW)
  shared_attrs >= 2  →  YELLOW (unless way-count mismatch → RED)
  shared_attrs >= 1 OR cosine >= 0.10  →  RED
  otherwise  →  below_threshold (not returned)

Same category, sparse description (either side has < 2 canonical tokens):
  cosine >= 0.25  →  YELLOW
  cosine >= 0.08  →  RED

Cross-category (same attribute family only):
  shared_attrs >= 3 AND cosine >= 0.15  →  RED
  cosine >= 0.20  →  RED
```

**Hard gate:** If both the query part and candidate specify a way-count (e.g., 3-way vs 4-way) and they differ, the tier is capped at YELLOW. A 3-way and 4-way valve have different port configurations — they are not drop-in compatible.

### Validated test result

Per the playbook validation case:

**Query:** Humphrey Products `E3P`
*(TAC Valve, 3-Way, Normally Closed, Push Button, Spring Return, M5 X 0.8, Brass, NBR Seals)*

**Results:**
```
GREEN   20%  4 attrs  Versa Products  BIK-3208-25B-67   ↳ matched: 3-way, normally-closed, push-button, spring-return
GREEN   20%  4 attrs  Versa Products  BIK-3208-25BR     ↳ matched: 3-way, normally-closed, push-button, spring-return
GREEN   20%  4 attrs  Versa Products  BIK-3209-P-S-25BG ↳ matched: 3-way, normally-closed, push-button, spring-return
YELLOW  20%  3 attrs  Versa Products  BIK-2208-25BR     ↳ matched: normally-closed, push-button, spring-return
...
10 alternatives (5 green / 5 yellow / 0 red)
```

This matches the expected result in the playbook exactly.

### Known limitation at this stage

The 20% cosine similarity for all results reveals the data quality problem directly. Even the correct GREEN matches only score 20% text similarity because:
- Humphrey descriptions are verbose (full spec sentences)
- Versa descriptions are terse (shorter spec lists)
- 71% of valve rows have no structured specs at all — those rows produce only RED or below-threshold results

This is the core reason the web scraping pipeline (Phase 4) was initiated.

### How to run

```bash
# Build the model (reads data/cleaned_data.csv)
python scripts/build_index.py

# Query — exact lookup
python scripts/query.py --brand "Humphrey Products" --part "E3P"
python scripts/query.py --brand Parker --part "P32EA4510AABW" --top-n 5

# Query — more results including same brand
python scripts/query.py --brand "Humphrey Products" --part "E3P" --same-brand

# Fuzzy search — find brand names
python scripts/query.py --search-brand "Parker"

# Fuzzy search — find parts with prefix
python scripts/query.py --search-parts --brand "Humphrey Products" --part "E3"
```

---

## 7. Phase 4 — Web Scraping Pipeline

**Files:** `scraper/`, `scripts/run_scraper.py`
**Status:** Built, blocked by bot protection on major sites
**Full details:** `SCRAPER_FINDINGS.md`

### Why this phase is needed

The model accuracy problem is fundamentally a data density problem. Specs like PSI rating, voltage, exact port size, and bore diameter are absent for most parts because:
- 71% of valve rows are model-code-only with no parseable specs
- `manufacturer_description` is only 13% filled
- The existing descriptions don't encode the key differentiating specs

The solution is to fetch structured spec tables from distributor/manufacturer websites and merge them back as `web_*` columns in `data/enriched_data.csv`. Rebuilding the model on enriched data would dramatically improve match accuracy.

### Architecture

```
cleaned_data.csv
       ↓
   pipeline.py reads pending rows (not yet in SQLite cache)
       ↓
   For each (brand, part_number):
     1. Try brand-specific scraper (Parker, SMC)
     2. If miss/error → try Grainger fallback
       ↓
   Cache result in data/scrape_cache.db (SQLite)
       ↓
   Export: cleaned_data.csv + web_* spec columns → enriched_data.csv
```

**Key design decisions:**
- **SQLite cache** — every result cached immediately. Kill the process at any point, resume later with `--stats` to check progress. Never re-scrapes `status='ok'` rows.
- **Per-domain rate limiting** — configurable gaps between requests (1.0-1.5s per domain) to avoid triggering rate limits
- **Concurrency** — default 30 simultaneous requests; raise to 80+ on a cloud instance

### What we hit: Akamai Bot Manager

Every major MRO distributor uses Akamai Bot Manager:

| Site | Approach | Result |
|---|---|---|
| grainger.com | httpx | Error page (returns 200 but junk HTML) |
| grainger.com | Playwright headless | Blocked ("technical difficulty") |
| grainger.com | Playwright + stealth | Blocked |
| ph.parker.com | httpx | 403 Forbidden |
| parker.com | Playwright | "Access Denied" |
| mscdirect.com | Playwright | 0 bytes response |

What IS accessible:
- **versa-valves.com** — confirmed returns product data
- **smcusa.com** — needs correct URL format, likely accessible

### Path forward

**Option A — ScraperAPI ($49/month):** One-line change wraps all URLs through their proxy which handles Akamai bypass. Immediately unblocks Grainger, covering most brands.

**Option B — Build scrapers for accessible sites:** Focus on smaller manufacturer sites (Versa, SMC, Aventics, Hydac, Balluff, Bijur Delimon, Schroeder). These have no Akamai. Covers ~60-80k rows for free.

**Option C — Both:** ScraperAPI for Parker/Grainger (bulk of the catalog), direct scrapers for accessible smaller brands.

### How to run once unblocked

```bash
# Test run — 100 parts
python scripts/run_scraper.py --limit 100

# Full run (overnight at concurrency 30)
python scripts/run_scraper.py

# Check progress without running
python scripts/run_scraper.py --stats

# Force re-scrape everything
python scripts/run_scraper.py --force

# Cloud instance (higher concurrency)
python scripts/run_scraper.py --concurrency 80
```

---

## 8. How to Run Everything

### First-time setup

```bash
# Create and activate the conda environment
conda env create -f environment.yml
conda activate mro-recommender
```

### Full pipeline from scratch

```bash
# Phase 1 — clean the raw catalog
python scripts/clean_data.py
# Output: data/cleaned_data.csv (292,640 rows, 22 columns, ~60s)

# Phase 3 — build the recommendation model
python scripts/build_index.py
# Output: models/recommender.joblib (~140 MB), models/catalog.parquet (~108 MB)
# Runtime: 2-3 minutes

# Query the model
python scripts/query.py --brand "Humphrey Products" --part "E3P"
python scripts/query.py --brand "Versa Products" --part "BIK-3208-25BR"
```

### Phase 4 — web scraping (once unblocked)

```bash
# Test with 100 parts first
python scripts/run_scraper.py --limit 100

# Check what the cache contains
python scripts/run_scraper.py --stats

# Full run
python scripts/run_scraper.py

# After scraping completes, rebuild model on enriched data
# (requires updating data_loader.py to use enriched_data.csv)
python scripts/build_index.py
```

### Notebook work (attribute extraction)

```bash
jupyter lab
# Open notebooks/attribute_extraction.ipynb
# Run all cells to re-generate data/processed/parts_with_attrs.csv
```

---

## 9. Current Status & What's Left

### Completed

| Task | Status | Output |
|---|---|---|
| Initial EDA (Python + R) | ✅ Done | `notebooks/eda.ipynb`, `data_analysis_products.qmd` |
| Data cleaning pipeline | ✅ Done | `scripts/clean_data.py` → `cleaned_data.csv` |
| Brand normalization | ✅ Done | 53 unique brands, all aliases resolved |
| Recommender model v1 | ✅ Done | `models/recommender.joblib` |
| Confidence scoring | ✅ Done | Green/Yellow/Red tiers with attribute matching |
| Spec normalization | ✅ Done | 40+ synonym rules in `normalize_specs.py` |
| End-to-end validation | ✅ Done | E3P → Versa BIK-3208 confirmed GREEN |
| Repo cleanup | ✅ Done | Clean folder structure, single cleaning script |
| Web scraper framework | ✅ Done | Async pipeline with SQLite cache |
| Attribute extraction — Valves | ⚠️ Partial | 12 attributes, but only 29% of rows have parseable specs |
| Attribute extraction — Cylinders | ⚠️ Partial | 9 attributes, 93% coverage — good |

### In progress / blocked

| Task | Status | Blocker |
|---|---|---|
| Web scraper — Grainger, Parker, MSC | 🔴 Blocked | Akamai Bot Manager |
| Web scraper — Versa, SMC, others | 🟡 Needs build | No scraper written yet for accessible sites |

### Not yet started

| Task | Notes |
|---|---|
| Attribute extraction — 6 remaining families | Hydraulic Filters, Fittings, Air Prep, Sensors, Electrical, Lubrication |
| data_loader.py update | Needs to use `enriched_data.csv` once scraping produces data |
| Model evaluation framework | No systematic way to measure accuracy yet — only manual spot-checks |
| API / UI layer | How will sales/procurement actually query this? Web app, CSV upload, Slack bot? |
| Confidence threshold tuning | Green/Yellow/Red thresholds set by engineering judgment, not data |

---

## 10. Key Technical Decisions & Why

### TF-IDF over embeddings (for now)

The planned architecture in `FINDINGS.md` called for `sentence-transformers` + FAISS vector search. The teammate's v1 used TF-IDF instead. **This was the right call for v1** because:

1. TF-IDF is fully explainable — you can see exactly which tokens drove a match
2. No GPU or API costs
3. Fits in RAM (292k rows, 30k features → manageable sparse matrix)
4. Fast to rebuild when data changes (scraping will change data frequently during development)

The `sentence-transformers` + FAISS path is still in `environment.yml` for when the data quality is good enough to warrant it. Embeddings reward rich descriptions — building them on sparse/incomplete data would not improve results much over TF-IDF.

### Per-family attribute extraction over universal parsing

We explicitly scope every extraction pattern to a specific product family. This was a deliberate choice made after observing that the same words mean completely different things across families. "3-way" in a valve context means three flow paths. In a fitting context it means a tee connector. These are incompatible products. Universal patterns would produce false positives.

### SQLite cache for the scraper

The scraper processes 292k parts. Any run will take hours. The SQLite cache means the process can be killed and resumed at any point without losing work. This also means we can inspect partial results mid-run with `--stats` without stopping the scraper.

### Keeping `brand_name_raw`

The original brand name is preserved as `brand_name_raw` in the cleaned CSV. This is an audit trail — if a normalization rule is wrong (e.g., two different companies whose names both start with "Parker" getting incorrectly merged), we can identify and fix it without having to re-read the raw file.

---

## 11. Known Problems & Limitations

### Data quality

- **71% of valve rows have no structured specs** — model-code-only descriptions produce no extractable attributes. The web scraping pipeline was started specifically to address this.
- **13% manufacturer_description fill rate** — the highest-quality column is also the sparsest.
- **No ground truth interchange table** — we have no validated list of "Part A is confirmed interchangeable with Part B." Confidence tiers are calibrated by engineering judgment and manual spot-checking only. There is no automated accuracy metric.

### Model limitations

- **Cosine similarity scores are low (20% for confirmed good matches)** — this reflects the sparse data problem, not a model failure. The attribute matching layer compensates for this, but the underlying problem remains until scraping fills the gaps.
- **Same-category filter is strict** — if Grainger categorizes a part slightly differently than MRO, it won't be a candidate at all. This could cause false negatives for valid substitutes.
- **No handling of superseded part numbers** — if a manufacturer discontinued a part and replaced it with a new part number, the model has no way to know about that relationship.

### Scraping

- **Akamai blocks all major sites** — Grainger, Parker, MSC are inaccessible with current approach. ScraperAPI ($49/month) is the cleanest solution.
- **Scraping 292k parts at 1.5s/request = ~120 hours single-threaded** — at concurrency 30 this becomes ~4 hours. Needs to run overnight. A cloud instance with higher bandwidth and concurrency 80+ could bring it under 2 hours.
- **After scraping, model must be rebuilt** — `build_index.py` needs to be pointed at `enriched_data.csv` instead of `cleaned_data.csv`, and `data_loader.py` needs to include `scraped_description` in its column priority list.

### Infrastructure

- **No API layer yet** — the model is only queryable via command line. The delivery mechanism for end users (web app, CSV batch upload, internal API) has not been decided or built.
- **Model file is ~140 MB** — not easily deployable without artifact storage (S3, etc.)
- **No CI/CD** — tests exist only as manual spot-checks in the playbook

---

*For session-by-session notes on specific discoveries, see `FINDINGS.md` (business-facing) and `SCRAPER_FINDINGS.md` (scraper technical findings).*
