# Playbook: Train Part Alternative Recommender

## Goal
A trained TF-IDF recommender model is saved to `models/recommender.joblib` and
`models/catalog.parquet`, ready to answer part-alternative queries via
`scripts/query.py`.

## Prerequisites
- `cleaned_data.csv` exists in the project root
- Python 3.9+ installed
- Dependencies installed: `pip install -r requirements.txt`

## Steps

1. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

2. **Build the index** `scripts/build_index.py` — reads CSV, fits TF-IDF, saves model
   ```
   python scripts/build_index.py
   ```
   Expected output:
   - `models/recommender.joblib` (~140 MB compressed model)
   - `models/catalog.parquet` (~108 MB catalog with normalized text)

3. **Validate the model** `scripts/query.py` — spot-check a few known parts
   ```
   python scripts/query.py --brand "Humphrey Products" --part "E3P"
   python scripts/query.py --brand "Humphrey Products" --part "QE2"
   ```
   Verify: GREEN results share 3+ canonical attributes; YELLOW share 2;
   RED share 0-1 but are in the same product category.

4. **[Decision]** If results look wrong (too many RED with low similarity,
   or GREEN for clearly incompatible parts), update normalization rules in
   `src/normalize_specs.py` and rebuild the index.

## Decision Criteria

- If a category has only one brand represented → all results will be RED or
  YELLOW (no cross-brand spec matching possible). This is expected behavior;
  the system surfaces category-level alternatives, not spec-verified matches.

- If similarity scores are all < 0.05 for a queried category → the descriptions
  for that category are likely model-code-only with no readable specs. Consider
  manually enriching descriptions for that category.

- This flow executes linearly with the optional rebuild in step 4.

## Verification

After building the index, run the following and confirm results are sensible:

```bash
# 3-way NC push-button valve → should return Versa BIK-3208 as GREEN
python scripts/query.py --brand "Humphrey Products" --part "E3P"

# Quick exhaust valve → should return Parker/Aventics/Versa as YELLOW
python scripts/query.py --brand "Humphrey Products" --part "QE2"

# Search for a brand name
python scripts/query.py --search-brand "Parker"

# Fuzzy part search
python scripts/query.py --search-parts --brand "Humphrey Products" --part "E3"
```
