"""
Grainger scraper — primary source for all brands.

Grainger carries most of the brands in this catalog. Strategy:
  1. Search Grainger for "{brand} {part_number}"
  2. Extract the top ranked SKUs from the embedded JSON payload
  3. Visit each candidate product page until we find one whose webParentItem
     or item name matches our MFR part number
  4. Parse the techSpecs table from the matched product page

Grainger's modern site embeds all data in a <script type="application/json">
blob at the top of the page. Both search and product pages use this format.
"""

import json
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from scraper.http import get

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.grainger.com/search"
BASE_URL = "https://www.grainger.com"
PRODUCT_URL_FMT = "https://www.grainger.com/product/{sku}"

# Max candidate product pages to visit per search (cost control)
MAX_CANDIDATES = 3


def _extract_json_blob(html: str) -> Optional[dict]:
    """Pull the primary application/json script blob out of a Grainger page."""
    scripts = re.findall(
        r'<script[^>]*type="application/json"[^>]*>([^<]+)</script>', html
    )
    for raw in scripts:
        try:
            data = json.loads(raw)
            # The search/product payload has either "category" or "product" at top
            if isinstance(data, dict) and (
                "category" in data or "product" in data or "gcomProducts" in data
            ):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _candidate_skus(search_data: dict, max_count: int = MAX_CANDIDATES) -> list[str]:
    """Extract the top-ranked Grainger SKUs from a search response payload."""
    category = search_data.get("category", {}).get("category", {})
    sort_map = category.get("hybrisProductSkuSortMap", {})
    if isinstance(sort_map, dict) and sort_map:
        return list(sort_map.keys())[:max_count]
    # Fallback: skuToProductMap (unordered but usable)
    sku_map = category.get("skuToProductMap", {})
    if isinstance(sku_map, dict):
        return list(sku_map.keys())[:max_count]
    return []


def _extract_product(product_data: dict, sku: str) -> tuple[Optional[str], Optional[str], Optional[dict]]:
    """From a product page JSON, return (mfr_part_number, description, specs)."""
    gcom = product_data.get("product", {}).get("gcomProducts", {})
    sku_entry = gcom.get(sku, {})
    if not sku_entry:
        return None, None, None

    hpi = sku_entry.get("hybrisProductInfo", {})
    name = hpi.get("name") or ""
    # Grainger embeds MFR PN in webParentItem sometimes; also try brand fields
    mfr_pn = (
        hpi.get("manufacturerPartNumber")
        or hpi.get("mfrPartNumber")
        or hpi.get("mfrModel")
        or ""
    )
    # Fallback: mfrPartNumber often lives in brand.mfrModelNumber
    brand = sku_entry.get("brand", {})
    if not mfr_pn and isinstance(brand, dict):
        mfr_pn = brand.get("mfrModelNumber") or brand.get("mfrPartNumber") or ""

    tech_specs = hpi.get("techSpecs") or []
    specs: dict[str, str] = {}
    for entry in tech_specs:
        if isinstance(entry, dict):
            key = (entry.get("name") or "").strip()
            val = entry.get("value")
            if key and val is not None:
                specs[key] = str(val).strip()

    # Pull Mfr Model No./Item from specs if top-level fields were empty
    if not mfr_pn:
        for key in ("Mfr. Model No.", "Mfr Model No.", "Manufacturer Model Number", "Item"):
            if key in specs:
                mfr_pn = specs[key]
                break

    return mfr_pn or None, name or None, specs or None


def _normalize(pn: Optional[str]) -> str:
    """Normalize a part number for comparison — upper, strip spaces & dashes."""
    if not pn:
        return ""
    return re.sub(r"[\s\-_]", "", pn.upper())


async def _fetch_product(sku: str, client: httpx.AsyncClient) -> Optional[dict]:
    resp = await get(PRODUCT_URL_FMT.format(sku=sku), client)
    if resp is None or resp.status_code != 200:
        return None
    return _extract_json_blob(resp.text)


async def scrape(
    brand: str,
    part_number: str,
    client: httpx.AsyncClient,
) -> tuple[str, Optional[str], Optional[dict], str]:
    """
    Main entry point. Returns (status, description, specs, source).
    status: 'ok' | 'not_found' | 'error'
    """
    source = "grainger"
    try:
        query = f"{brand} {part_number}"
        resp = await get(SEARCH_URL, client, params={"searchQuery": query})
        if resp is None or resp.status_code != 200:
            return "not_found", None, None, source

        search_data = _extract_json_blob(resp.text)
        if not search_data:
            return "not_found", None, None, source

        candidates = _candidate_skus(search_data)
        if not candidates:
            return "not_found", None, None, source

        target = _normalize(part_number)

        # Visit each candidate — only accept exact MFR part number matches.
        # The prior "approx" fallback produced garbage (e.g. "Stacking Tie-Rod
        # Kit" returned for every Humphrey Products query), so strict matching
        # is the only safe behavior. Treat non-matches as not_found.
        for sku in candidates:
            prod_data = await _fetch_product(sku, client)
            if not prod_data:
                continue
            mfr_pn, description, specs = _extract_product(prod_data, sku)
            if not specs or not mfr_pn:
                continue
            if _normalize(mfr_pn) == target:
                return (
                    "ok",
                    description,
                    specs,
                    f"grainger:{PRODUCT_URL_FMT.format(sku=sku)}",
                )

        return "not_found", None, None, source

    except Exception as exc:
        logger.exception("Grainger scrape failed for %s %s: %s", brand, part_number, exc)
        return "error", None, None, source
