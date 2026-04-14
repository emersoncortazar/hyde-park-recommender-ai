"""
Parker Hannifin direct scraper.

Parker's product catalog is at ph.parker.com. Part numbers can be looked up
directly via their search API which returns JSON.
"""

import json
import logging
from typing import Optional

import httpx

from scraper.http import get

logger = logging.getLogger(__name__)

SEARCH_API = "https://ph.parker.com/us/en/search-results"
PRODUCT_BASE = "https://ph.parker.com"


async def scrape(
    part_number: str,
    client: httpx.AsyncClient,
) -> tuple[str, Optional[str], Optional[dict], str]:
    """
    Returns (status, description, specs, source).
    """
    source = "parker"

    try:
        # Parker's search takes a 'q' param and returns HTML with embedded JSON
        resp = await get(
            SEARCH_API,
            client,
            params={"q": part_number, "divisionCode": "PD"},
        )
        if resp is None or resp.status_code != 200:
            return "error", None, None, source

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")

        # Find exact part number match in results
        product_url = None
        for link in soup.select("a.product-link, a[data-part-number]"):
            pn = link.get("data-part-number", "") or link.get_text(strip=True)
            if pn.upper() == part_number.upper():
                href = link.get("href", "")
                product_url = PRODUCT_BASE + href if href.startswith("/") else href
                break

        # Try JSON embedded in page
        if not product_url:
            script = soup.find("script", {"type": "application/json", "id": re.compile(r"product")})
            if script:
                try:
                    data = json.loads(script.string)
                    for item in data.get("results", []):
                        if item.get("partNumber", "").upper() == part_number.upper():
                            product_url = item.get("productUrl")
                            break
                except (json.JSONDecodeError, AttributeError):
                    pass

        if not product_url:
            return "not_found", None, None, source

        # Fetch product page
        prod_resp = await get(product_url, client)
        if prod_resp is None or prod_resp.status_code != 200:
            return "error", None, None, source

        prod_soup = BeautifulSoup(prod_resp.text, "lxml")

        specs = {}
        description = None

        # Parker product pages have a JSON-LD block
        for script in prod_soup.find_all("script", {"type": "application/ld+json"}):
            try:
                import re
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if data.get("@type") == "Product":
                    description = data.get("description")
                    for prop in data.get("additionalProperty", []):
                        name = prop.get("name", "").strip()
                        value = prop.get("value", "")
                        if name:
                            specs[name] = str(value).strip()
            except (json.JSONDecodeError, AttributeError):
                continue

        # Fallback: spec table
        if not specs:
            for row in prod_soup.select(".specs-table tr, .product-attributes tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    val = cells[1].get_text(strip=True)
                    if key and val:
                        specs[key] = val

        if not description:
            meta = prod_soup.find("meta", {"name": "description"})
            if meta:
                description = meta.get("content", "").strip()

        if not specs and not description:
            return "not_found", None, None, source

        return "ok", description, specs, f"parker:{product_url}"

    except Exception as exc:
        logger.exception("Parker scrape failed for %s: %s", part_number, exc)
        return "error", None, None, source


import re  # noqa: E402 — needed inside nested try blocks above
