"""
Load and preprocess the product catalog CSV.

Output: a cleaned DataFrame ready for indexing.
"""

import re
import pandas as pd

from src.normalize_specs import normalize_specs


DESCRIPTION_COLS = [
    "livhaven_short_description",
    "default_short_description",
    "mro_description",
    "default_name",
]


def _best_description(row: pd.Series) -> str:
    """Return the first non-empty description for a row."""
    for col in DESCRIPTION_COLS:
        val = row.get(col)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, keep alphanumeric + units."""
    text = text.lower()
    # Keep numbers, letters, common unit chars and punctuation useful for specs
    text = re.sub(r"[^a-z0-9\s/\-\.\"']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load(csv_path: str) -> pd.DataFrame:
    """
    Read the catalog CSV, fill in a combined text field, and return a
    DataFrame with a stable integer index.

    Added columns:
      - description_text : raw best description
      - text_normalized  : lowercased / cleaned version for TF-IDF
    """
    df = pd.read_csv(csv_path, low_memory=False)

    # Normalise key string columns
    for col in ["brand_name", "manufacturer_part_number", "category_name", "attribute_family"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # Build best available description
    df["description_text"] = df.apply(_best_description, axis=1)
    # Two-stage normalization: basic cleanup → spec synonym expansion
    df["text_normalized"] = (
        df["description_text"]
        .apply(_normalize_text)
        .apply(normalize_specs)
    )

    # Drop rows where we have nothing useful to compare on
    df = df[df["text_normalized"].str.len() > 10].reset_index(drop=True)

    return df
