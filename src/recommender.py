"""
Core TF-IDF recommender for industrial part alternatives.

Architecture
------------
- One TF-IDF matrix built over ALL products (sparse, ~300 MB peak).
- At query time, candidates are filtered to the same category_name first
  (Green / Yellow tier), then same attribute_family (Red tier).
- Cosine similarity is computed only within the candidate subset, keeping
  query time fast even at 292 K items.

Confidence tiers
----------------
  Green  : strong structural attribute match (3+ canonical spec tokens shared)
  Yellow : moderate attribute match (2 canonical spec tokens shared)
  Red    : same category, partial or no spec info
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from src.confidence import compute_tier, extract_attributes


@dataclass
class Alternative:
    brand: str
    part_number: str
    category: str
    description: str
    similarity: float
    confidence: str        # "green" | "yellow" | "red"
    same_brand: bool
    matched_attrs: int = 0  # number of shared canonical spec attributes
    shared_attr_list: str = ""  # comma-separated matched attributes


@dataclass
class RecommenderResult:
    query_brand: str
    query_part_number: str
    query_category: str
    query_description: str
    alternatives: List[Alternative] = field(default_factory=list)
    error: Optional[str] = None


class PartRecommender:
    """
    Build once (fit), query many times (recommend).
    """

    def __init__(
        self,
        max_features: int = 30_000,
        ngram_range: tuple = (1, 2),
        top_n: int = 10,
    ):
        self.max_features = max_features
        self.ngram_range = ngram_range
        self.top_n = top_n

        self._df: Optional[pd.DataFrame] = None
        self._tfidf_matrix = None
        self._vectorizer: Optional[TfidfVectorizer] = None

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, df: pd.DataFrame) -> "PartRecommender":
        """
        Build the TF-IDF index over the full catalog.

        Parameters
        ----------
        df : DataFrame produced by data_loader.load()
        """
        self._df = df.reset_index(drop=True)

        self._vectorizer = TfidfVectorizer(
            max_features=self.max_features,
            ngram_range=self.ngram_range,
            sublinear_tf=True,
            min_df=2,
        )

        raw_texts = self._df["text_normalized"].fillna("").tolist()
        self._tfidf_matrix = self._vectorizer.fit_transform(raw_texts)
        # L2-normalize rows so dot product == cosine similarity
        self._tfidf_matrix = normalize(self._tfidf_matrix, norm="l2", copy=False)

        return self

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _lookup_product(
        self, brand: str, part_number: str
    ) -> Optional[int]:
        """Return the DataFrame row index for a brand + part_number pair."""
        brand_lower = brand.strip().lower()
        pn_lower = part_number.strip().lower()

        mask = (
            self._df["brand_name"].str.lower() == brand_lower
        ) & (
            self._df["manufacturer_part_number"].str.lower() == pn_lower
        )
        hits = self._df[mask]
        if hits.empty:
            return None
        return int(hits.index[0])

    def _tier(
        self,
        query_text: str,
        candidate_text: str,
        similarity: float,
        same_category: bool,
    ) -> str:
        return compute_tier(query_text, candidate_text, similarity, same_category)

    # ------------------------------------------------------------------
    # Recommend
    # ------------------------------------------------------------------

    def recommend(
        self,
        brand: str,
        part_number: str,
        include_same_brand: bool = False,
    ) -> RecommenderResult:
        """
        Return top alternatives for the given brand + part number.

        Parameters
        ----------
        brand            : Manufacturer / brand name (case-insensitive).
        part_number      : Manufacturer part number (case-insensitive).
        include_same_brand : Whether to include same-brand alternatives.
                            Default False (cross-reference focus).
        """
        if self._df is None or self._tfidf_matrix is None:
            raise RuntimeError("Call fit() before recommend().")

        idx = self._lookup_product(brand, part_number)

        if idx is None:
            return RecommenderResult(
                query_brand=brand,
                query_part_number=part_number,
                query_category="",
                query_description="",
                error=f"Part not found: brand='{brand}', part_number='{part_number}'",
            )

        query_row = self._df.iloc[idx]
        query_category = query_row["category_name"]
        query_family = query_row["attribute_family"]
        query_brand_lower = query_row["brand_name"].lower()

        # --- Candidate selection ---
        # Tier 1: same category (primary filter)
        same_cat_mask = self._df["category_name"] == query_category
        # Tier 2: same attribute family, excluding "parts/accessories/kits"
        # categories which are sub-components, not functional alternatives.
        _PARTS_PATTERN = r"\bparts\b|\baccessories\b|\brepair kits\b|\bkits\b|\bcomponents\b"
        same_fam_mask = (
            (self._df["attribute_family"] == query_family)
            & (~self._df["category_name"].str.contains(_PARTS_PATTERN, case=False, regex=True, na=False))
        )
        candidate_mask = same_cat_mask | same_fam_mask
        # Exclude the query item itself
        candidate_mask.iloc[idx] = False

        candidate_indices = np.where(candidate_mask.values)[0]

        if len(candidate_indices) == 0:
            return RecommenderResult(
                query_brand=brand,
                query_part_number=part_number,
                query_category=query_category,
                query_description=query_row["description_text"],
                error="No candidate products found in the same category/family.",
            )

        # --- Similarity computation ---
        query_vec = self._tfidf_matrix[idx]  # (1, vocab)
        candidate_mat = self._tfidf_matrix[candidate_indices]  # (N, vocab)
        sims = cosine_similarity(query_vec, candidate_mat).flatten()

        # Sort descending
        sorted_order = np.argsort(sims)[::-1]
        sorted_global_idx = candidate_indices[sorted_order]
        sorted_sims = sims[sorted_order]

        # --- Build result list ---
        alternatives: List[Alternative] = []
        seen_pn: set = set()

        for g_idx, sim in zip(sorted_global_idx, sorted_sims):
            row = self._df.iloc[g_idx]

            pn_key = (row["brand_name"].lower(), row["manufacturer_part_number"].lower())
            if pn_key in seen_pn:
                continue
            seen_pn.add(pn_key)

            is_same_brand = row["brand_name"].lower() == query_brand_lower
            if not include_same_brand and is_same_brand:
                continue

            is_same_cat = row["category_name"] == query_category
            tier = self._tier(
                query_row["text_normalized"],
                row["text_normalized"],
                float(sim),
                is_same_cat,
            )
            if tier == "below_threshold":
                continue

            q_attrs = extract_attributes(query_row["text_normalized"])
            c_attrs = extract_attributes(row["text_normalized"])
            shared = sorted(q_attrs & c_attrs)

            alternatives.append(
                Alternative(
                    brand=row["brand_name"],
                    part_number=row["manufacturer_part_number"],
                    category=row["category_name"],
                    description=row["description_text"],
                    similarity=round(float(sim), 4),
                    confidence=tier,
                    same_brand=is_same_brand,
                    matched_attrs=len(shared),
                    shared_attr_list=", ".join(shared),
                )
            )

            if len(alternatives) >= self.top_n:
                break

        return RecommenderResult(
            query_brand=brand,
            query_part_number=part_number,
            query_category=query_category,
            query_description=query_row["description_text"],
            alternatives=alternatives,
        )

    # ------------------------------------------------------------------
    # Fuzzy brand / part search (for partial input)
    # ------------------------------------------------------------------

    def search_brand(self, partial: str, limit: int = 10) -> List[str]:
        """Return brands whose name contains `partial` (case-insensitive)."""
        p = partial.lower()
        return (
            self._df[self._df["brand_name"].str.lower().str.contains(p, regex=False)]
            ["brand_name"]
            .drop_duplicates()
            .head(limit)
            .tolist()
        )

    def search_parts(
        self, brand: str, partial_pn: str, limit: int = 20
    ) -> pd.DataFrame:
        """Return part rows whose part number contains `partial_pn`."""
        brand_mask = self._df["brand_name"].str.lower() == brand.lower()
        pn_mask = self._df["manufacturer_part_number"].str.lower().str.contains(
            partial_pn.lower(), regex=False
        )
        return self._df[brand_mask & pn_mask][
            ["brand_name", "manufacturer_part_number", "category_name", "description_text"]
        ].head(limit)
