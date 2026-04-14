#!/usr/bin/env python3
"""Clean raw MRO product catalog CSV.

Input:  data/raw_data.csv
Output: data/cleaned_data.csv
"""

import re
import sys
import numpy as np
import pandas as pd
from html import unescape
from html.parser import HTMLParser

RAW_PATH   = "data/raw_data.csv"
CLEAN_PATH = "data/cleaned_data.csv"

# ---------------------------------------------------------------------------
# Column selection — only these columns survive from the 87-column raw export
# ---------------------------------------------------------------------------

COLUMN_MAP = {
    "item key":                          "supplier_catalog_key",
    "price":                             "supplier_name",
    "sku":                               "sku",
    "attributefamily.code":              "attribute_family",
    "category.default.title":            "category_name",
    "category.id":                       "category_id",
    "brand.default.title":               "brand_name",
    "manufacturer_part_number":          "manufacturer_part_number",
    "last_sold_price":                   "last_sold_price",
    "itemweight":                        "item_weight",
    "attribute_table":                   "attribute_table",
    "downloads":                         "downloads",
    "manufacturer_description":          "manufacturer_description",
    "names.default.value":               "default_name",
    "names.livhaven.value":              "livhaven_name",
    "shortdescriptions.default.value":   "default_short_description",
    "shortdescriptions.livhaven.value":  "livhaven_short_description",
    "descriptions.mro.value":            "mro_description",
    "descriptions.livhaven.value":       "livhaven_description",
}

DTYPE_MAP = {
    "supplier_catalog_key":       "Float64",
    "supplier_name":              "string",
    "sku":                        "string",
    "attribute_family":           "string",
    "category_name":              "string",
    "category_id":                "Float64",
    "brand_name":                 "string",
    "manufacturer_part_number":   "string",
    "last_sold_price":            "Float64",
    "item_weight":                "Float64",
    "attribute_table":            "string",
    "downloads":                  "string",
    "manufacturer_description":   "string",
    "default_name":               "string",
    "livhaven_name":              "string",
    "default_short_description":  "string",
    "livhaven_short_description": "string",
    "mro_description":            "string",
    "livhaven_description":       "string",
}

# ---------------------------------------------------------------------------
# Brand normalization — same manufacturer appears under multiple names
# ---------------------------------------------------------------------------

BRAND_ALIASES = {
    "parker pneumatic division":    "Parker",
    "parker pneumatic":             "Parker",
    "parker frl":                   "Parker",
    "parker finite":                "Parker",
    "parker hose":                  "Parker",
    "parker hannifin":              "Parker",
    "parker-hannifin":              "Parker",
    "parker transair":              "Parker",
    "parker-commercial intertech":  "Parker",
    "parker":                       "Parker",
    "bosch rexroth":                "Bosch Rexroth",
    "rexroth":                      "Bosch Rexroth",
    "smc corporation":              "SMC",
    "smc corp":                     "SMC",
    "smc":                          "SMC",
    "versa products":               "Versa Products",
    "versa products co.":           "Versa Products",
    "aventics":                     "Aventics",
    "hydac":                        "Hydac",
    "balluff, inc.":                "Balluff",
    "balluff":                      "Balluff",
    "hengst filtration":            "Hengst Filtration",
    "schroeder industries":         "Schroeder Industries",
    "bijur delimon international":  "Bijur Delimon",
    "bijur delimon":                "Bijur Delimon",
}

# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

_EXTRA_ENTITIES = {
    "&helip;":  "...",
    "&mldr;":   "...",
    "&hellip;": "...",
    "&lsquo;":  "'",
    "&rsquo;":  "'",
    "&ldquo;":  '"',
    "&rdquo;":  '"',
    "&ndash;":  "-",
    "&mdash;":  "--",
    "&nbsp;":   " ",
}

_DESC_COLS = [
    "default_name",
    "default_short_description",
    "livhaven_short_description",
    "mro_description",
    "livhaven_description",
    "manufacturer_description",
    "livhaven_name",
    "downloads",
]


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_text(self):
        return " ".join(self.fed)


def _strip_html(text) -> str:
    if pd.isna(text) or str(text).strip() == "":
        return pd.NA
    t = str(text)
    for entity, replacement in _EXTRA_ENTITIES.items():
        t = t.replace(entity, replacement)
    if "<" in t:
        stripper = _HTMLStripper()
        stripper.feed(t)
        t = re.sub(r"\s+", " ", stripper.get_text()).strip()
    t = unescape(t)
    return t.strip() or pd.NA


# ---------------------------------------------------------------------------
# Attribute table parsing — pipe-delimited format
# ---------------------------------------------------------------------------

def _parse_pipe_attrs(raw) -> dict:
    if pd.isna(raw) or str(raw).strip() == "":
        return {}
    parts = [p.strip() for p in str(raw).split("|")]
    parts = [p for p in parts if p]
    result = {}
    i = 0
    while i < len(parts) - 1:
        key = parts[i].strip()
        val = parts[i + 1].strip()
        if key:
            result[key] = val if val else np.nan
        i += 2
    return result


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load(path: str) -> pd.DataFrame:
    print(f"[1/7] Loading {path} ...")
    df = pd.read_csv(path, dtype=str)
    df.columns = df.columns.str.lower().str.strip()
    df = df.rename(columns=COLUMN_MAP)
    keep = [c for c in COLUMN_MAP.values() if c in df.columns]
    df = df[keep]
    valid_dtypes = {k: v for k, v in DTYPE_MAP.items() if k in df.columns}
    df = df.astype(valid_dtypes)
    print(f"      {len(df):,} rows, {len(df.columns)} columns")
    return df


def normalize_brands(df: pd.DataFrame) -> pd.DataFrame:
    print("[2/7] Normalizing brand names ...")
    df["brand_name_raw"] = df["brand_name"].copy()
    df["brand_name"] = (
        df["brand_name"]
        .apply(lambda x: BRAND_ALIASES.get(str(x).strip().lower(), str(x).strip()) if pd.notna(x) else pd.NA)
        .astype("string")
    )
    changed = (df["brand_name"] != df["brand_name_raw"]).sum()
    print(f"      {changed:,} rows updated | {df['brand_name'].nunique()} unique brands")
    return df


def normalize_part_numbers(df: pd.DataFrame) -> pd.DataFrame:
    print("[3/7] Normalizing part numbers ...")
    df["manufacturer_part_number"] = (
        df["manufacturer_part_number"].astype("string").str.strip().str.upper()
    )
    pn_len = df["manufacturer_part_number"].str.len()
    df["pn_flag"] = pd.NA
    df.loc[pn_len < 4, "pn_flag"]  = "too_short"
    df.loc[pn_len > 30, "pn_flag"] = "too_long"
    df["missing_pn"] = df["manufacturer_part_number"].isna()
    flagged = df["pn_flag"].notna().sum()
    missing = df["missing_pn"].sum()
    print(f"      {flagged:,} flagged (too short/long) | {missing:,} missing")
    return df


def numeric_sanity(df: pd.DataFrame) -> pd.DataFrame:
    print("[4/7] Numeric sanity checks ...")
    for col in ["last_sold_price", "item_weight"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["last_sold_price"] = df["last_sold_price"].replace(0, np.nan)
    print(f"      price null: {df['last_sold_price'].isna().sum():,} | weight null: {df['item_weight'].isna().sum():,}")
    return df


def strip_html(df: pd.DataFrame) -> pd.DataFrame:
    print("[5/7] Stripping HTML from description columns ...")
    for col in _DESC_COLS:
        if col not in df.columns:
            continue
        df[col] = df[col].apply(_strip_html).astype("string")
    return df


def parse_attributes(df: pd.DataFrame) -> pd.DataFrame:
    print("[6/7] Parsing attribute_table (this takes ~60s) ...")
    parsed   = df["attribute_table"].apply(_parse_pipe_attrs)
    attr_df  = pd.DataFrame(parsed.tolist(), index=df.index)
    coverage = attr_df.notna().sum().sort_values(ascending=False)
    min_rows = max(1, int(len(df) * 0.01))
    keep     = coverage[coverage >= min_rows].index.tolist()
    df = pd.concat([df, attr_df[keep].add_prefix("attr_")], axis=1)
    df.drop(columns=["attribute_table"], inplace=True)
    print(f"      {len(keep)} attribute columns kept (>= {min_rows} rows)")
    return df


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    print("[7/7] Deduplicating on (brand, part_number) ...")
    before = len(df)
    real    = df[df["manufacturer_part_number"].notna()].copy()
    null_pn = df[df["manufacturer_part_number"].isna()].copy()
    real["_richness"] = real.notna().sum(axis=1)
    real = (
        real.sort_values("_richness", ascending=False)
        .drop_duplicates(subset=["manufacturer_part_number", "brand_name"], keep="first")
        .drop(columns=["_richness"])
    )
    df = pd.concat([real, null_pn], ignore_index=True)
    print(f"      {before - len(df):,} duplicate rows removed | {len(df):,} rows remain")
    return df


def main():
    df = load(RAW_PATH)
    df = normalize_brands(df)
    df = normalize_part_numbers(df)
    df = numeric_sanity(df)
    df = strip_html(df)
    df = parse_attributes(df)
    df = deduplicate(df)

    df.to_csv(CLEAN_PATH, index=False)
    print(f"\nSaved → {CLEAN_PATH}  ({len(df):,} rows, {len(df.columns)} columns)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
