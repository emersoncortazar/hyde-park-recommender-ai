# Hyde Park MRO — AI Part Interchange Recommender
## Project Findings & Technical Process Documentation

*Prepared for internal distribution. Intended for both executive stakeholders and technical reviewers.*

---

## What We Are Building

We are building an **AI-powered part interchange recommender** — a tool that, given a specific industrial part (identified by brand and part number), automatically identifies equivalent substitute parts from other manufacturers in our catalog.

**Why this matters:** When a customer needs a part that is out of stock, discontinued, or simply wants a lower-cost alternative, today that search is done manually by sales and procurement teams. This tool automates that process and ranks alternatives by confidence.

**The output:** A ranked list of substitute candidates, each tagged with a confidence level — allowing the team to quickly validate the top suggestions rather than searching from scratch.

---

## The Dataset

We are working with a product catalog of **292,640 parts** exported from the MRO/Livingston & Haven product management system.

**Raw data:** 87 columns, most of which are CMS metadata (SEO slugs, storefront-specific flags, null fields). After cleaning, we retain 10 meaningful columns.

### What we kept and why

| Column | What it is | Why it matters |
|---|---|---|
| `sku` | Internal product identifier | Primary key |
| `brand_name` | Manufacturer name (normalized) | Critical for finding *cross-brand* substitutes |
| `manufacturer_part_number` | The part number as the manufacturer defines it | The primary lookup key |
| `attribute_family` | High-level product category group | Gates which extraction patterns apply |
| `category_name` | More specific product category | Narrows candidate pool for matching |
| `default_name` | Product name (100% filled) | Human-readable identifier |
| `default_short_description` | Comma-separated spec list | **Primary source for attribute extraction** |
| `manufacturer_description` | Technical prose from manufacturer | Supplements specs where filled (13% of rows) |
| `last_sold_price` | Most recent transaction price | Useful for cost comparison |
| `item_weight` | Part weight | Secondary matching signal |

### What we dropped and why

- **`mro_description` / `livhaven_description`**: These look like product descriptions but are actually distributor SEO copy. Every row begins with the part name followed by boilerplate marketing text ("MROStop is the Humphrey distributor you can trust..."). Zero extraction value.
- **`livhaven_short_description`**: A near-exact duplicate of `default_short_description`. Dropped to avoid redundancy.
- **`attribute_table`**: Present in the raw export column list but empty for all 292,640 rows. Confirmed useless.
- **65 other columns**: CMS metadata — slugs, no-index flags, hide-from-guest flags, tax codes, feature flags. None contain part specification data.

---

## Key Finding: The Dataset Is Not Uniform

This is the most important thing to understand about this data.

**292,640 parts across 20+ product families do not behave like one dataset.** They behave like 20 separate datasets that happen to share the same spreadsheet.

What a valve looks like in the data:
```
3-Way, Normally Closed, 2-Position, Push Button, Spring Return,
M5 X 0.8 Ports, Brass Body, NBR Seals, 0-125PSI Pressure Range
```

What a cylinder looks like:
```
Double-acting non-lube NFPA tie-rod pneumatic cylinder with piston magnet +
"LipSeal" piston - 2" bore (B2") - 5" stroke (S5") - 2 x 3/8" NPT ports
```

What a sensor looks like (varies):
```
0 to 200 psia, 0.25% Accuracy, 4 to 20 mA Output, 1/2" NPT Male
```
or just:
```
Part #: BNS023K  Model Code: BNS 813-B06-L12-72-12-06
```

**Attempting to apply the same extraction logic across all families would produce incorrect and misleading data.** Every attribute extractor in this project is scoped to a specific product family and validated against real samples before use.

---

## The Attribute Families (Product Groups)

The catalog breaks down into these major groups:

| Product Family | # Parts | Description |
|---|---|---|
| Valves & Accessories | 78,355 | Pneumatic/hydraulic directional control, check, flow control valves |
| Cylinders & Accessories | 63,929 | Pneumatic/hydraulic actuating cylinders |
| Hydraulic Filters | 31,692 | Filtration and fluid conditioning equipment |
| Fittings | 13,213 | Pipe, tube, and hose connectors |
| Air Preparation | 12,696 | Filters, regulators, lubricators |
| Sensors & Accessories | 12,540 | Pressure transmitters, switches, position sensors |
| Electrical Panel Components | 11,805 | Solenoid connectors, DIN plugs, electrical accessories |
| Lubrication Systems | 8,924 | Centralized lubrication system components |
| *Others (12 families)* | ~60,000 | Gauges, hose ends, pumps, servo drives, etc. |

---

## Phase 1: Cleaning the Data

**Goal:** Produce a reliable, consistent base dataset from the raw export.

### What was done

1. **Column selection** — Mapped 87 raw columns to 19 meaningful ones, dropping all CMS/SEO/null fields
2. **Type normalization** — Enforced consistent data types (strings, floats, nulls)
3. **HTML stripping** — Several description fields contained raw HTML tags (`<p>`, `&amp;`, `&hellip;`) that needed to be cleaned to plain text
4. **Brand name normalization** — The same manufacturer appears under multiple spellings. Examples:
   - `"parker pneumatic division"`, `"parker hannifin"`, `"parker-hannifin"` → all normalized to `"Parker"`
   - `"smc corporation"`, `"smc corp"` → `"SMC"`
   - This is critical: if Parker and "parker pneumatic" are treated as different brands, the recommender will miss valid substitutes
5. **Part number flags** — Added quality flags: `pn_flag` (part numbers that appear suspicious), `missing_pn`

### Output
`data/cleaned_data.csv` — 292,640 rows × 22 columns

---

## Phase 2: Attribute Extraction

**Goal:** Extract structured, machine-comparable attributes from free-text descriptions so the recommender can do precise matching (not just word similarity).

### The problem

A recommender that only matches on text similarity would equate a "3-Way valve" with a "3-Way coupler" — technically both 3-way, but completely different product types. We need structured attributes — the actual specs — to make accurate comparisons.

### Where the specs live

The `default_short_description` column contains comma-separated spec lists for most parts:
```
Quick Exhaust Valve, 1/4" NPT IN & OUT Ports, 3/8" NPT EXH Port,
2.00 Cv, NBR Seals, Aluminum Diecast Body, 3-150PSI Pressure Range
```

These are the attributes we parse. There is no pre-existing structured column for "port size" or "pressure rating" — it lives inside these strings.

### Our extraction approach

We use **pattern matching (regex)** targeted at each product family. The process for each family:

1. **Diagnose** — Sample 50-100 descriptions and understand what information is actually present and what format it takes
2. **Write patterns** — Create targeted extractors for the attributes we observed
3. **Audit** — Spot-check extracted values against the source text, report coverage

We never assume a pattern from one family works in another.

### Attributes we can extract per family

**Valves (78k rows):**
- Port thread size (e.g., `1/4" NPT`, `M5 X 0.8`)
- Number of ways / positions (e.g., `3-Way, 2-Position`)
- Solenoid type (`Single`, `Double`)
- Return mechanism (`Spring Return`, `Detent`)
- Seal material (`NBR`, `FKM`, `PTFE`)
- Body material (`Brass`, `Aluminum Diecast`, `Zinc`)
- Voltage (`12VDC`, `24VDC`, `120VAC`)
- Pressure range (e.g., `0-125PSI`)
- Cv flow coefficient

*Coverage caveat:* Only ~35% of valve rows have structured spec text. ~42% are model-code references (Bosch Rexroth part numbers, manifold designations) that contain no parseable specs.

**Cylinders (64k rows):**
- Bore diameter (e.g., `2"`)
- Stroke length (e.g., `5"`)
- Port size (e.g., `3/8" NPT`)
- Acting type (`Double-acting`, `Single-acting`)
- Construction type (`NFPA tie-rod`, `compact`, `stainless steel`)
- Piston magnet (yes/no)
- Cushion location (`Both Ends`, `Head End Only`)
- Rod end thread

*Coverage:* 93% of cylinder rows have parseable bore and stroke specs — the most consistently structured family in the dataset.

### Output
`data/processed/parts_with_attrs.csv` — same 292k rows, with new structured attribute columns added per family.

---

## Phase 3: The Recommender (Planned)

With structured attributes in hand, the recommender works in two stages:

### Stage 1 — Candidate Retrieval (Semantic Search)
We embed each part's description into a vector using a pre-trained language model (`all-MiniLM-L6-v2`). Given a query part, we retrieve the top-K most semantically similar parts using FAISS (a vector similarity index). This handles cases where specs are worded differently but mean the same thing.

This is done **locally** — no API calls, no ongoing cost.

### Stage 2 — Attribute Re-ranking
From the top-K candidates, we filter same-brand results (substitutes must be from a different manufacturer) and re-rank by attribute overlap:
- Same port size → higher score
- Same pressure range → higher score
- Same seal material → higher score
- Different category → penalized

### Confidence Tiers (Future)
The final score maps to a traffic-light confidence level:
- **Green** — High text similarity + strong attribute match → likely a direct substitute
- **Yellow** — Good similarity, partial attribute match → possible substitute, verify specs
- **Red** — Weak signal → requires human review

Human review and sign-off by the technical team is the intended validation path. We do not have ground-truth interchange tables, so the system is designed to support — not replace — expert judgment.

---

## Technical Stack

| Component | Tool | Why |
|---|---|---|
| Data cleaning | Python / pandas | Standard data manipulation |
| Attribute extraction | Python / regex | Precise, auditable, no external dependencies |
| Embeddings | `sentence-transformers` (local) | Free, runs on CPU, no API costs |
| Vector search | FAISS | Industry standard for large-scale nearest-neighbor search |
| Notebooks | Jupyter | Reproducible, shareable, step-by-step audit trail |
| Environment | Conda (`mro-recommender`) | Isolated, reproducible environment |

---

## Current Status

| Phase | Status |
|---|---|
| Raw data exploration (EDA) | Complete |
| Data cleaning pipeline | Complete |
| Attribute extraction — Valves | In progress |
| Attribute extraction — Cylinders | In progress |
| Attribute extraction — Other families | Scaffolded, pending |
| Embedding pipeline | Planned |
| FAISS index + candidate retrieval | Planned |
| Re-ranking + confidence scoring | Planned |
| UI / delivery mechanism | TBD |

---

*This document will be updated as each phase completes.*
