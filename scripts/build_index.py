#!/usr/bin/env python3
"""
Purpose: Load catalog CSV, fit TF-IDF recommender, save model artifacts.
Parameters: None (paths are relative to project root)
Output: models/recommender.joblib, models/catalog.parquet
Exit codes: 0=success, 1=error
"""

import os
import sys
import time

# Allow running from project root or scripts/ dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import joblib
import pandas as pd

from src.data_loader import load
from src.recommender import PartRecommender

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(PROJECT_ROOT, "cleaned_data.csv")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "recommender.joblib")
CATALOG_PATH = os.path.join(MODEL_DIR, "catalog.parquet")


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)

    print(f"[1/4] Loading catalog from {CSV_PATH} ...")
    t0 = time.time()
    df = load(CSV_PATH)
    print(f"      {len(df):,} rows loaded in {time.time()-t0:.1f}s")

    print("[2/4] Fitting TF-IDF recommender ...")
    t0 = time.time()
    rec = PartRecommender(max_features=30_000, ngram_range=(1, 2), top_n=10)
    rec.fit(df)
    print(f"      Matrix shape: {rec._tfidf_matrix.shape}  ({time.time()-t0:.1f}s)")

    print(f"[3/4] Saving model to {MODEL_PATH} ...")
    joblib.dump(rec, MODEL_PATH, compress=3)
    print(f"      Saved ({os.path.getsize(MODEL_PATH)/1e6:.1f} MB)")

    print(f"[4/4] Saving catalog to {CATALOG_PATH} ...")
    df.to_parquet(CATALOG_PATH, index=True)
    print(f"      Saved ({os.path.getsize(CATALOG_PATH)/1e6:.1f} MB)")

    print("\nDone. Run scripts/query.py to test.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
