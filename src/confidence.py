"""
Confidence tier computation for industrial part alternatives.

Problem context
---------------
Different brands use widely varying description lengths and vocabularies
for the same type of component.  Pure cosine-similarity thresholds produce
misleading tiers (e.g., a valid 3-way NC push-button valve from Brand B
may only score 0.20 against Brand A's well-described part — not because
it's a bad match, but because Brand B writes terse descriptions).

Solution: hybrid scoring
------------------------
1. Count how many *canonical technical attributes* appear in BOTH the query
   description and the candidate description (after spec normalization).
   These are the tokens that actually encode functional compatibility.
2. Use cosine similarity as a secondary signal within the same attribute-
   match count bucket.
3. Fall back to cosine-only tiering when no structured attributes are found.

Confidence tiers
----------------
  GREEN  : high confidence the part is a compatible alternative
  YELLOW : moderate confidence — likely compatible, verify before ordering
  RED    : same product category, partial spec match — use with caution

The tier strings intentionally stay simple so the caller (CLI, API) can
substitute emojis, CSS classes, or plain text as needed.
"""

from __future__ import annotations

import re
from typing import Set

# ---------------------------------------------------------------------------
# Canonical attribute tokens — the "key spec words" after normalization
# ---------------------------------------------------------------------------
# These are the normalised tokens produced by normalize_specs.py that carry
# the most functional-compatibility signal.

_ATTRIBUTE_PATTERN = re.compile(
    r"""
    (
      \d+-way               |   # 2-way, 3-way, 4-way, 5-way
      \d+-position          |   # 2-position, 3-position
      normally-closed       |
      normally-open         |
      push-button           |
      foot-pedal            |
      roller-lever          |
      toggle                |
      solenoid              |
      spring-return         |
      detent                |
      double-acting         |
      single-acting         |
      port-\S+              |   # port-1-4-npt, port-m5, port-10-32-unf …
      body-aluminum         |
      body-brass            |
      body-stainless        |
      body-plastic          |
      seal-nbr              |
      seal-polyurethane     |
      seal-fkm              |
      seal-epdm             |
      voltage-\S+           |   # voltage-24v, voltage-120vac …
      bore-\d+mm            |
      stroke-\d+(?:mm|in)   |
      \d+-micron            |
      press-\d+-\d+           # press-0-125, press-3-150 …
    )
    """,
    re.VERBOSE,
)


def extract_attributes(normalized_text: str) -> Set[str]:
    """Return the set of canonical attribute tokens in a normalized description."""
    return set(_ATTRIBUTE_PATTERN.findall(normalized_text))


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------

def _get_way_count(attrs: Set[str]) -> str | None:
    """Return the way-count token (e.g. '3-way') if present, else None."""
    for a in attrs:
        if a.endswith("-way"):
            return a
    return None


def compute_tier(
    query_text: str,
    candidate_text: str,
    cosine_sim: float,
    same_category: bool,
) -> str:
    """
    Return a confidence tier string: "green" | "yellow" | "red" | "below_threshold".

    Logic
    -----
    Primary signal  : count of shared canonical attributes (structural match).
    Secondary signal: cosine similarity (overall text similarity).
    Hard gate       : same_category must be True for green or yellow;
                      red is still available for same-family cross-category.
    """
    q_attrs = extract_attributes(query_text)
    c_attrs = extract_attributes(candidate_text)
    shared = q_attrs & c_attrs
    shared_count = len(shared)

    if same_category:
        # Rich description path — both sides have structured attributes
        if len(q_attrs) >= 2 and len(c_attrs) >= 2:
            # Hard gate: if both parts specify a way-count and they differ,
            # cap at YELLOW (different valve topology — not drop-in compatible)
            q_ways = _get_way_count(q_attrs)
            c_ways = _get_way_count(c_attrs)
            way_mismatch = (q_ways and c_ways and q_ways != c_ways)

            if shared_count >= 3:
                return "yellow" if way_mismatch else "green"
            if shared_count >= 2:
                return "red" if way_mismatch else "yellow"
            if shared_count >= 1 or cosine_sim >= 0.10:
                return "red"
            return "below_threshold"

        # Sparse description path — at least one side lacks structured attrs
        # Use cosine similarity as the only signal, with lower thresholds
        if cosine_sim >= 0.25:
            return "yellow"
        if cosine_sim >= 0.08:
            return "red"
        return "below_threshold"

    else:
        # Cross-category (same attribute family only)
        if shared_count >= 3 and cosine_sim >= 0.15:
            return "red"
        if cosine_sim >= 0.20:
            return "red"
        return "below_threshold"
