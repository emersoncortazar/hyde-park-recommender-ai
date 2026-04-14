"""
Grainger scraper — primary source for all brands.

Grainger carries most of the brands in this catalog and presents specs
in a consistent structured table. Strategy:
  1. Search Grainger for "{brand} {part_number}"
  2. Take the first result whose manufacturer part number matches exactly
  3. Parse the specs table from the product page

Grainger spec tables use JSON-LD structured data AND an HTML table —
we prefer JSON-LD when available as it's more reliable.
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
BASE_URL   = "https://www.grainger.com"


async def search_part(
    brand: str,
    part_number: str,
    client: httpx.AsyncClient,
) -> Optional[str]:
    """Search Grainger and return the product page URL for the best match."""
    query = f"{brand} {part_number}"
    resp = await get(SEARCH_URL, client, params={"searchQuery": query})
    if resp is None or resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Grainger embeds search results as JSON in a <script id="__NEXT_DATA__"> tag
    next_data = soup.find("script", {"id": "__NEXT_DATA__"})
    if next_data:
        try:
            data = json.loads(next_data.string)
            products = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("searchResults", {})
                    .get("products", [])
            )
            for product in products[:5]:
                mfr_pn = product.get("mfrPartNumber", "")
                if mfr_pn.upper() == part_number.upper():
                    path = product.get("productUrl") or product.get("pdpUrl", "")
                    if path:
                        return BASE_URL + path if path.startswith("/") else path
        except (json.JSONDecodeError, AttributeError):
            pass

    # Fallback: parse HTML product cards
    for card in soup.select("a[data-testid='product-card-link'], a.product-card"):
        href = card.get("href", "")
        # Check if MFR part number appears in nearby text
        text = card.get_text(" ", strip=True).upper()
        if part_number.upper() in text:
            return BASE_URL + href if href.startswith("/") else href

    return None


async def scrape_product_page(
    url: str,
    client: httpx.AsyncClient,
) -> tuple[Optional[str], Optional[dict]]:
    """
    Fetch a Grainger product page and extract:
      - description (str)
      - specs (dict of spec_name -> value)
    Returns (description, specs).
    """
    resp = await get(url, client)
    if resp is None or resp.status_code != 200:
        return None, None

    soup = BeautifulSoup(resp.text, "lxml")

    # --- Try JSON-LD first ---
    specs = {}
    description = None

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") in ("Product", "ItemPage"):
                description = data.get("description") or description
                # additionalProperty holds structured specs
                for prop in data.get("additionalProperty", []):
                    name  = prop.get("name", "").strip()
                    value = prop.get("value", "")
                    if name:
                        specs[name] = str(value).strip()
        except (json.JSONDecodeError, AttributeError):
            continue

    # --- Fallback: parse the HTML specs table ---
    if not specs:
        for table in soup.select("table.specs-table, [data-testid='specs-table'], .product-specs table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    val = cells[1].get_text(strip=True)
                    if key and val:
                        specs[key] = val

    # --- Description fallback ---
    if not description:
        for sel in [
            "[data-testid='product-description']",
            ".product-description",
            "#product-description",
            "meta[name='description']",
        ]:
            el = soup.select_one(sel)
            if el:
                description = el.get("content") or el.get_text(strip=True)
                break

    return description or None, specs or None


async def scrape(
    brand: str,
    part_number: str,
    client: httpx.AsyncClient,
) -> tuple[str, Optional[str], Optional[dict], str]:
    """
    Main entry point. Returns (status, description, specs, source_url).
    status: 'ok' | 'not_found' | 'error'
    """
    source = "grainger"
    try:
        product_url = await search_part(brand, part_number, client)
        if not product_url:
            return "not_found", None, None, source

        description, specs = await scrape_product_page(product_url, client)
        if not description and not specs:
            return "not_found", None, None, source

        return "ok", description, specs, f"grainger:{product_url}"

    except Exception as exc:
        logger.exception("Grainger scrape failed for %s %s: %s", brand, part_number, exc)
        return "error", None, None, source
