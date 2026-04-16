"""
Full-catalog enrichment.

Two-stage pipeline:
  1. Run the rule-based spec extractor (scraper.spec_extractor) over every
     row's existing description fields. This yields structured columns for
     ~85% of the catalog with zero network cost.
  2. Merge in any successfully-scraped rows from data/scrape_cache.db (Zoro
     or Grainger hits) as additional columns prefixed with `web_*`.

The output is data/enriched_data.csv — a superset of data/cleaned_data.csv.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from scraper.spec_extractor import extract_all

logger = logging.getLogger(__name__)

CLEAN_PATH = Path("data/cleaned_data.csv")
ENRICHED_PATH = Path("data/enriched_data.csv")
CACHE_PATH = Path("data/scrape_cache.db")


# Description fields, in priority order — we extract specs from the first
# non-null one for each row.
DESC_FIELDS = [
    "default_short_description",
    "livhaven_short_description",
    "manufacturer_description",
    "mro_description",
    "livhaven_description",
]


def _best_description(row: pd.Series) -> str | None:
    for field in DESC_FIELDS:
        val = row.get(field)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _extract_specs_row(row: pd.Series) -> dict[str, Any]:
    text = _best_description(row)
    return extract_all(text)


def extract_catalog_specs(df: pd.DataFrame) -> pd.DataFrame:
    """Add structured spec columns (prefix `spec_`) for every row."""
    extracted = df.apply(_extract_specs_row, axis=1)
    spec_df = pd.DataFrame.from_records(list(extracted.values))
    spec_df.columns = [f"spec_{c}" for c in spec_df.columns]
    return pd.concat([df.reset_index(drop=True), spec_df.reset_index(drop=True)], axis=1)


def _load_scraped(cache_path: Path) -> pd.DataFrame:
    if not cache_path.exists():
        return pd.DataFrame(columns=["brand", "part_number", "source", "scraped_description", "scraped_specs"])
    conn = sqlite3.connect(str(cache_path))
    try:
        results = pd.read_sql(
            "SELECT brand, part_number, source, scraped_description, scraped_specs "
            "FROM scrape_results WHERE status='ok'",
            conn,
        )
    finally:
        conn.close()
    return results


def merge_scraped(df: pd.DataFrame, scraped: pd.DataFrame) -> pd.DataFrame:
    """Left-join scraped columns onto df, prefixing spec keys with `web_`."""
    if scraped.empty:
        df["scraped_description"] = None
        df["scrape_source"] = None
        return df

    # Expand JSON specs into one dict per row
    def _parse(val: Any) -> dict[str, Any]:
        if not val:
            return {}
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    specs_series = scraped["scraped_specs"].apply(_parse)
    specs_df = pd.json_normalize(list(specs_series)).add_prefix("web_")
    specs_df.columns = [c.lower().replace(" ", "_").replace(".", "_") for c in specs_df.columns]

    merged_source = pd.concat(
        [scraped[["brand", "part_number", "source", "scraped_description"]].reset_index(drop=True),
         specs_df.reset_index(drop=True)],
        axis=1,
    ).rename(columns={"source": "scrape_source"})

    # Join on normalized keys (case insensitive)
    df["_brand_key"] = df["brand_name"].str.lower()
    df["_pn_key"] = df["manufacturer_part_number"].str.upper()
    merged_source["_brand_key"] = merged_source["brand"].str.lower()
    merged_source["_pn_key"] = merged_source["part_number"].str.upper()

    out = df.merge(
        merged_source.drop(columns=["brand", "part_number"]),
        on=["_brand_key", "_pn_key"],
        how="left",
    ).drop(columns=["_brand_key", "_pn_key"])
    return out


def run(
    clean_path: Path = CLEAN_PATH,
    cache_path: Path = CACHE_PATH,
    out_path: Path = ENRICHED_PATH,
) -> pd.DataFrame:
    """Full enrichment: extract + merge + save."""
    print(f"Loading catalog from {clean_path} ...")
    df = pd.read_csv(clean_path, dtype=str)
    print(f"  {len(df):,} rows, {len(df.columns)} columns")

    print("Extracting structured specs from descriptions ...")
    df_spec = extract_catalog_specs(df)
    spec_cols = [c for c in df_spec.columns if c.startswith("spec_")]
    print(f"  Added {len(spec_cols)} spec columns")
    for c in spec_cols:
        n = df_spec[c].notna().sum()
        print(f"    {c:<30} {n:>7,}  ({100*n/len(df_spec):5.1f}%)")

    print(f"Loading cached scrape results from {cache_path} ...")
    scraped = _load_scraped(cache_path)
    print(f"  {len(scraped):,} successful scrapes")

    enriched = merge_scraped(df_spec, scraped)
    filled = enriched["scraped_description"].notna().sum() if "scraped_description" in enriched else 0
    print(f"  Rows with web scrape data: {filled:,}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(enriched):,} rows, {len(enriched.columns)} columns)")
    return enriched


if __name__ == "__main__":
    run()
