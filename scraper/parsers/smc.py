"""
SMC Corporation direct scraper.

SMC USA's website has a part number lookup at smcusa.com.
Their product pages include a downloadable spec sheet link and
an HTML spec table.
"""

import json
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from scraper.http import get

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.smcusa.com/products/search/"
BASE_URL   = "https://www.smcusa.com"


async def scrape(
    part_number: str,
    client: httpx.AsyncClient,
) -> tuple[str, Optional[str], Optional[dict], str]:
    source = "smc"
    try:
        resp = await get(SEARCH_URL, client, params={"partNumber": part_number})
        if resp is None or resp.status_code != 200:
            return "error", None, None, source

        soup = BeautifulSoup(resp.text, "lxml")

        # SMC search returns a list — find exact part number match
        product_url = None
        for link in soup.select("a.part-number-link, a[href*='/products/']"):
            text = link.get_text(strip=True).upper()
            href = link.get("href", "")
            if text == part_number.upper() or part_number.upper() in href.upper():
                product_url = BASE_URL + href if href.startswith("/") else href
                break

        if not product_url:
            return "not_found", None, None, source

        prod_resp = await get(product_url, client)
        if prod_resp is None or prod_resp.status_code != 200:
            return "error", None, None, source

        prod_soup = BeautifulSoup(prod_resp.text, "lxml")

        specs = {}
        description = None

        # SMC product pages have a specs section
        for row in prod_soup.select(".product-specs tr, .specs-table tr, table.specifications tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True)
                val = cells[1].get_text(strip=True)
                if key and val and key.lower() != "specification":
                    specs[key] = val

        # Try JSON-LD
        for script in prod_soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if data.get("@type") == "Product":
                    description = description or data.get("description")
                    for prop in data.get("additionalProperty", []):
                        name = prop.get("name", "").strip()
                        value = prop.get("value", "")
                        if name and name not in specs:
                            specs[name] = str(value).strip()
            except (json.JSONDecodeError, AttributeError):
                continue

        if not description:
            meta = prod_soup.find("meta", {"name": "description"})
            if meta:
                description = meta.get("content", "").strip()

        if not specs and not description:
            return "not_found", None, None, source

        return "ok", description, specs, f"smc:{product_url}"

    except Exception as exc:
        logger.exception("SMC scrape failed for %s: %s", part_number, exc)
        return "error", None, None, source
