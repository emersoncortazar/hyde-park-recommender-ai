"""
Extract structured specification fields from the catalog's description text.

The catalog already carries spec-dense descriptions in `default_short_description`
and `livhaven_short_description` — e.g.:

    "TAC Valve, 3-Way, Normally Closed, 2-Position, Push Button,
     Spring Return, M5 X 0.8 Ports, Brass Body, NBR Seals ... 0-125PSI Pressure Range"

This module parses those sentences into typed columns the recommender can use
directly (pressure_psi_min, pressure_psi_max, voltage_v, port_size, body_material,
valve_positions, valve_ways, etc.).

The extractors are intentionally conservative — they emit None rather than a
best-guess so that downstream models don't learn from noise.
"""

from __future__ import annotations

import re
from typing import Optional


# ---- Pressure (PSI / bar / MPa) -----------------------------------------

_PSI_RANGE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)\s*(?:to|-|–|~)\s*(?P<hi>\d+(?:\.\d+)?)\s*(?:psi|psig)\b",
    re.IGNORECASE,
)
_PSI_SINGLE = re.compile(
    r"(?<![\d.])(?P<val>\d+(?:\.\d+)?)\s*(?:psi|psig)\b",
    re.IGNORECASE,
)
_BAR_RANGE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)\s*(?:to|-|–|~)\s*(?P<hi>\d+(?:\.\d+)?)\s*bar\b",
    re.IGNORECASE,
)
_BAR_SINGLE = re.compile(
    r"(?<![\d.])(?P<val>\d+(?:\.\d+)?)\s*bar\b",
    re.IGNORECASE,
)


def extract_pressure_psi(text: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """Return (min_psi, max_psi). Accepts 'PSI', 'PSIG', or 'bar' (converted)."""
    if not text:
        return None, None
    m = _PSI_RANGE.search(text)
    if m:
        return float(m.group("lo")), float(m.group("hi"))
    m = _BAR_RANGE.search(text)
    if m:
        bar_to_psi = 14.5038
        return float(m.group("lo")) * bar_to_psi, float(m.group("hi")) * bar_to_psi
    m = _PSI_SINGLE.search(text)
    if m:
        v = float(m.group("val"))
        return 0.0, v  # interpret bare "125 PSI" as 0-125 range
    m = _BAR_SINGLE.search(text)
    if m:
        bar_to_psi = 14.5038
        v = float(m.group("val")) * bar_to_psi
        return 0.0, v
    return None, None


# ---- Voltage ------------------------------------------------------------

_VOLT = re.compile(
    r"(?<![\w.])(?P<val>\d+(?:\.\d+)?)\s*(?:V|VAC|VDC|volts?)\b",
    re.IGNORECASE,
)
_VOLT_CURRENT = re.compile(r"\b(?P<val>\d+)(?:V|VAC|VDC)\s*/\s*\d+Hz\b", re.IGNORECASE)


def extract_voltage_v(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = _VOLT.search(text)
    if m:
        return float(m.group("val"))
    m = _VOLT_CURRENT.search(text)
    if m:
        return float(m.group("val"))
    return None


# ---- Valve ways / positions --------------------------------------------

_WAYS = re.compile(r"\b(?P<n>\d)\s*-?\s*way\b", re.IGNORECASE)
_POS = re.compile(r"\b(?P<n>\d)\s*-?\s*position\b", re.IGNORECASE)


def extract_valve_ways(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = _WAYS.search(text)
    return int(m.group("n")) if m else None


def extract_valve_positions(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = _POS.search(text)
    return int(m.group("n")) if m else None


# ---- Port / thread size -------------------------------------------------

_PORT_PATTERNS = [
    re.compile(r"\b(?:with\s+)?(?P<size>\d+/\d+)\s*[-]?\s*(?:inch|in\.?|\")\s+(?:NPT|NPTF|BSPP|BSPT|ORB|SAE)\b", re.IGNORECASE),
    re.compile(r"\b(?P<size>\d+/\d+|\d+(?:\.\d+)?|\d+[-\s]?\d+/\d+)\s*(?:inch|in\.?|\")\s+ports?\b", re.IGNORECASE),
    re.compile(r"\b(?P<size>M\d+\s*[Xx]\s*\d+(?:\.\d+)?)\s+ports?\b"),
    re.compile(r"\b(?P<size>\d+/\d+|\d+)\s*[-]?\s*(?:NPT|NPTF|BSPP|BSPT|ORB|SAE)\b", re.IGNORECASE),
    re.compile(r"\b(?P<size>#\d+\s*SAE|SAE\s*#?\d+)\b", re.IGNORECASE),
    re.compile(r"\b(?P<size>\d+-\d+\s*UNF)\b", re.IGNORECASE),
]


def extract_port_size(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for pat in _PORT_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group("size").strip().upper().replace("  ", " ")
    return None


# ---- Bore / stroke (pneumatic/hydraulic cylinders) ---------------------

_BORE = re.compile(
    r"\b(?P<val>\d+(?:\-\d+/\d+|\s\d+/\d+|/\d+|\.\d+)?)\s*(?:inch|in\.?|\")\s*bore\b",
    re.IGNORECASE,
)
_BORE_PREFIX = re.compile(
    r"\b(?P<val>\d+(?:\-\d+/\d+|\s\d+/\d+|/\d+|\.\d+)?)\"\s*bore\b", re.IGNORECASE
)
_STROKE = re.compile(
    r"\b(?P<val>\d+(?:\-\d+/\d+|\s\d+/\d+|/\d+|\.\d+)?)\s*(?:inch|in\.?|\")\s*stroke\b",
    re.IGNORECASE,
)
_BORE_MM = re.compile(r"\b(?P<val>\d+(?:\.\d+)?)\s*mm\s*bore\b", re.IGNORECASE)


def extract_bore(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for pat in (_BORE_PREFIX, _BORE, _BORE_MM):
        m = pat.search(text)
        if m:
            return m.group("val").strip()
    return None


def extract_stroke(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _STROKE.search(text)
    return m.group("val").strip() if m else None


# ---- Flow / Cv ---------------------------------------------------------

_FLOW_GPM = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*GPM\b", re.IGNORECASE)
_FLOW_CFM = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*(?:SCFM|CFM)\b", re.IGNORECASE)
_CV = re.compile(r"\bCv\s*(?:=|of)?\s*(?P<val>\d+(?:\.\d+)?)", re.IGNORECASE)


def extract_flow(text: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """Return (flow_value, unit). Unit is 'gpm', 'cfm', or 'cv'."""
    if not text:
        return None, None
    m = _FLOW_GPM.search(text)
    if m:
        return float(m.group("val")), "gpm"
    m = _FLOW_CFM.search(text)
    if m:
        return float(m.group("val")), "cfm"
    m = _CV.search(text)
    if m:
        return float(m.group("val")), "cv"
    return None, None


# ---- Material / seals --------------------------------------------------

_BODY_MATERIALS = [
    "stainless steel", "carbon steel", "brass", "aluminum", "cast iron",
    "bronze", "zinc", "nickel plated", "nickel-plated", "steel",
    "polyurethane", "plastic", "nylon",
]
_SEAL_MATERIALS = ["NBR", "FKM", "Viton", "EPDM", "Buna-N", "Buna N", "PTFE", "Teflon", "Silicone"]


def _find_first(text: str, options: list[str]) -> Optional[str]:
    low = text.lower()
    best = None
    best_idx = len(text) + 1
    for opt in options:
        idx = low.find(opt.lower())
        if idx >= 0 and idx < best_idx:
            best = opt.title() if opt.islower() else opt
            best_idx = idx
    return best


def extract_body_material(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return _find_first(text, _BODY_MATERIALS)


def extract_seal_material(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return _find_first(text, _SEAL_MATERIALS)


# ---- Temperature range -------------------------------------------------

_TEMP_RANGE = re.compile(
    r"(?P<lo>-?\d+)\s*(?:to|–|~|-)\s*(?P<hi>-?\d+)\s*(?:°?\s*F|°?\s*C)\b",
    re.IGNORECASE,
)


def extract_temperature_f(text: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None
    m = _TEMP_RANGE.search(text)
    if not m:
        return None, None
    lo, hi = float(m.group("lo")), float(m.group("hi"))
    # If the unit was C, convert
    unit_chunk = text[m.start():m.end()]
    if re.search(r"°?\s*C\b", unit_chunk, re.IGNORECASE):
        lo, hi = lo * 9 / 5 + 32, hi * 9 / 5 + 32
    return lo, hi


# ---- Top-level extractor -----------------------------------------------

def extract_all(text: Optional[str]) -> dict:
    """Return all structured features for the given description text."""
    psi_lo, psi_hi = extract_pressure_psi(text)
    flow_val, flow_unit = extract_flow(text)
    temp_lo, temp_hi = extract_temperature_f(text)
    return {
        "pressure_psi_min": psi_lo,
        "pressure_psi_max": psi_hi,
        "voltage_v":        extract_voltage_v(text),
        "valve_ways":       extract_valve_ways(text),
        "valve_positions":  extract_valve_positions(text),
        "port_size":        extract_port_size(text),
        "bore":             extract_bore(text),
        "stroke":           extract_stroke(text),
        "flow_value":       flow_val,
        "flow_unit":        flow_unit,
        "body_material":    extract_body_material(text),
        "seal_material":    extract_seal_material(text),
        "temperature_f_min": temp_lo,
        "temperature_f_max": temp_hi,
    }
