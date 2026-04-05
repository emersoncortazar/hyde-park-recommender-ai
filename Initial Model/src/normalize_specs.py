"""
Normalize industrial component descriptions so that equivalent specs
use consistent tokens before TF-IDF vectorization.

Examples fixed:
  "three-way"  → "3-way"      (same as "3-way")
  "palm button" → "push-button"
  "1/4\""       → "0.25in"    (port size normalization)
  "differential pilot return" → "spring-return"  (both = auto-reset)
"""

import re
from typing import List, Tuple

# Each entry: (compiled regex, replacement string)
# Order matters — more specific patterns before general ones.
_RAW_RULES: List[Tuple[str, str]] = [
    # --- Directional valve ways ---
    (r"\bfive[- ]?way\b", "5-way"),
    (r"\bfour[- ]?way\b", "4-way"),
    (r"\bthree[- ]?way\b", "3-way"),
    (r"\btwo[- ]?way\b", "2-way"),

    # --- Positions ---
    (r"\bthree[- ]?position\b", "3-position"),
    (r"\btwo[- ]?position\b", "2-position"),

    # --- Normally open / closed ---
    (r"\bnormally[- ]?closed\b", "normally-closed"),
    (r"\bnormally[- ]?open\b", "normally-open"),
    (r"\b(?:n\.?c\.?)\b", "normally-closed"),
    (r"\b(?:n\.?o\.?)\b", "normally-open"),

    # --- Actuation type ---
    # "palm button" and "push button" are both manual hand actuation
    (r"\bpalm[- ]?button\b", "push-button"),
    (r"\bpush[- ]?button\b", "push-button"),
    # foot pedal variants
    (r"\bfoot[- ]?pedal\b", "foot-pedal"),
    (r"\bfoot[- ]?operated\b", "foot-pedal"),
    # lever / toggle
    (r"\btoggle[- ]?lever\b", "toggle"),
    (r"\bknob[- ]?operated\b", "knob"),
    (r"\broller[- ]?lever\b", "roller-lever"),

    # --- Return type ---
    # Differential pilot return and spring return both auto-reset
    (r"\bdifferential[- ]?pilot[- ]?return\b", "spring-return"),
    (r"\bspring[- ]?return\b", "spring-return"),
    (r"\bspring[- ]?offset\b", "spring-return"),
    # Detented / maintained
    (r"\bdetent(?:ed)?\b", "detent"),
    (r"\bmaintained\b", "detent"),

    # --- Acting type ---
    (r"\bdouble[- ]?acting\b", "double-acting"),
    (r"\bsingle[- ]?acting\b", "single-acting"),

    # --- Port / thread sizes: normalize fractions to decimal strings ---
    # 1/8 inch
    (r"\b1/8[\"']?\s*(?:npt|bsp|r|g|unf|unc|jic)?\b", "port-1-8-npt"),
    # 1/4 inch
    (r"\b1/4[\"']?\s*(?:npt|bsp|r|g|unf|unc|jic)?\b", "port-1-4-npt"),
    # 3/8 inch
    (r"\b3/8[\"']?\s*(?:npt|bsp|r|g|unf|unc|jic)?\b", "port-3-8-npt"),
    # 1/2 inch
    (r"\b1/2[\"']?\s*(?:npt|bsp|r|g|unf|unc|jic)?\b", "port-1-2-npt"),
    # 3/4 inch
    (r"\b3/4[\"']?\s*(?:npt|bsp|r|g|unf|unc|jic)?\b", "port-3-4-npt"),
    # Metric: M5, M6, M8, M10, M12
    (r"\bm5\s*x\s*[\d.]+\b", "port-m5"),
    (r"\bm6\s*x\s*[\d.]+\b", "port-m6"),
    (r"\bm8\s*x\s*[\d.]+\b", "port-m8"),
    # 10-32 UNF  (common miniature valve port)
    (r"\b10[- ]?32\s*unf\b", "port-10-32-unf"),

    # --- Body material ---
    (r"\baluminum(?:\s*(?:die[- ]?cast|body))?\b", "body-aluminum"),
    (r"\baluminium\b", "body-aluminum"),
    (r"\bbrass\s*body\b", "body-brass"),
    (r"\bstainless\s*(?:steel)?\s*body\b", "body-stainless"),
    (r"\bplastic\s*body\b", "body-plastic"),
    (r"\bnylon\s*body\b", "body-plastic"),

    # --- Seal material ---
    (r"\bnbr\s*seals?\b", "seal-nbr"),
    (r"\bnitrile\s*(?:rubber)?\s*seal\b", "seal-nbr"),
    (r"\bpolyurethane\s*seals?\b", "seal-polyurethane"),
    (r"\bpu\s*seals?\b", "seal-polyurethane"),
    (r"\bfkm\s*seals?\b", "seal-fkm"),
    (r"\bviton\s*seals?\b", "seal-fkm"),
    (r"\bepdm\s*seals?\b", "seal-epdm"),

    # --- Solenoid voltage (normalize to token) ---
    (r"\b24\s*v(?:dc|ac)?\b", "voltage-24v"),
    (r"\b12\s*v(?:dc|ac)?\b", "voltage-12v"),
    (r"\b110\s*v(?:ac)?\b", "voltage-110vac"),
    (r"\b120\s*v(?:ac)?\b", "voltage-120vac"),
    (r"\b220\s*v(?:ac)?\b", "voltage-220vac"),
    (r"\b240\s*v(?:ac)?\b", "voltage-240vac"),

    # --- Cylinder / actuator bore sizes (mm) ---
    # e.g. "12mm bore", "bore: 12 mm"
    (r"\bbore[:\s]*(\d+)\s*mm\b", r"bore-\1mm"),
    # Stroke
    (r"\bstroke[:\s]*(\d+)\s*mm\b", r"stroke-\1mm"),
    (r"\bstroke[:\s]*(\d+)\s*in\b", r"stroke-\1in"),

    # --- Filter micron ratings ---
    (r"\b(\d+)\s*micron\b", r"\1-micron"),
    (r"\b(\d+)\s*\u03bc\b", r"\1-micron"),

    # --- Pressure range normalization ---
    (r"\b(\d+)\s*(?:to|[-~])\s*(\d+)\s*(?:psi|bar)\b", r"press-\1-\2"),
]

# Compile once
RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), repl)
    for pat, repl in _RAW_RULES
]


def normalize_specs(text: str) -> str:
    """
    Apply all synonym/normalization rules to a product description string.
    Returns the modified string (lowercased).
    """
    t = text.lower()
    for pattern, replacement in RULES:
        t = pattern.sub(replacement, t)
    # Collapse extra whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t
