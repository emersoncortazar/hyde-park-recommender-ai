"""
Zoro scraper — primary fallback source for all brands.

Zoro.com (sister site of Grainger) has different indexing and carries many
specialized industrial parts that Grainger's search misses. Its pages expose
a clean JSON-LD Product schema which is easy to parse.

Strategy:
  1. Search "{brand} {part_number}" on Zoro.
  2. If the search page serves a Product JSON-LD whose MPN matches, use it.
  3. Otherwise, follow the top product link (if any) and re-check.
  4. Strict MPN matching — only return 'ok' on an exact (normalized) match.

The JSON-LD payload gives us: name, mpn, brand, description. We also parse
the on-page "Specifications" block for additional key/value details.
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from scraper.http import get

logger = logging.getLogger(__name__)

SEARCH_URL_FMT = "https://www.zoro.com/search?q={q}"
BASE_URL = "https://www.zoro.com"


def _normalize(pn: Optional[str]) -> str:
    """Normalize a part number for comparison — upper, strip whitespace/dashes/slashes."""
    if not pn:
        return ""
    return re.sub(r"[\s\-_/.]", "", pn.upper())


def _extract_product_jsonld(soup: BeautifulSoup) -> Optional[dict]:
    """Return the first ld+json block whose @type is Product."""
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        # Sometimes Zoro wraps multiple schemas in a list
        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if isinstance(entry, dict) and entry.get("@type") == "Product":
                return entry
    return None


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Parse the Specifications block into a key-value dict.

    Zoro's spec area is a flex of pairs inside a <div class*="spec">. We find
    <dl>/<dt>/<dd> and generic labeled rows.
    """
    specs: dict[str, str] = {}

    # 1) Any <dl><dt>...<dd>...</dl>
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            key = dt.get_text(" ", strip=True)
            val = dd.get_text(" ", strip=True)
            if key and val and len(key) < 80 and len(val) < 400:
                specs[key] = val

    # 2) Tables with two cells per row
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) == 2:
                key = cells[0].get_text(" ", strip=True)
                val = cells[1].get_text(" ", strip=True)
                if key and val and len(key) < 80 and len(val) < 400:
                    specs[key] = val

    return specs


def _extract_product(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], dict[str, str]]:
    """Return (mfr_pn, name, description, specs) from a Zoro product page."""
    ld = _extract_product_jsonld(soup)
    mfr_pn = name = description = None
    if ld:
        mfr_pn = ld.get("mpn") or None
        name = ld.get("name") or None
        description = ld.get("description") or None
    specs = _extract_specs(soup)
    return mfr_pn, name, description, specs


def _find_candidate_links(soup: BeautifulSoup, limit: int = 3) -> list[str]:
    """Pick top product links from a Zoro search page."""
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.select('a[href*="/i/"]'):
        href = a.get("href") or ""
        if not href or href in seen:
            continue
        seen.add(href)
        links.append(urljoin(BASE_URL, href))
        if len(links) >= limit:
            break
    return links


async def scrape(
    brand: str,
    part_number: str,
    client: httpx.AsyncClient,
) -> tuple[str, Optional[str], Optional[dict], str]:
    """
    Main entry point. Returns (status, description, specs, source).
    status: 'ok' | 'not_found' | 'error'
    """
    source = "zoro"
    try:
        query = f"{brand} {part_number}".strip()
        search_url = SEARCH_URL_FMT.format(q=quote_plus(query))

        resp = await get(search_url, client, retries=2, timeout=60)
        if resp is None or resp.status_code != 200:
            return "not_found", None, None, source

        soup = BeautifulSoup(resp.text, "lxml")
        target = _normalize(part_number)

        # Case 1: Zoro redirected to a product page (search returned a direct hit).
        mfr_pn, name, description, specs = _extract_product(soup)
        if mfr_pn and _normalize(mfr_pn) == target:
            combined_specs = dict(specs)
            # Always include name/description in specs dict as well for convenience
            return "ok", name or description, combined_specs or None, f"zoro:{search_url}"

        # Case 2: Follow top candidate product links if there are any.
        candidates = _find_candidate_links(soup, limit=3)
        for url in candidates:
            prod_resp = await get(url, client, retries=1, timeout=60)
            if prod_resp is None or prod_resp.status_code != 200:
                continue
            prod_soup = BeautifulSoup(prod_resp.text, "lxml")
            mfr_pn, name, description, specs = _extract_product(prod_soup)
            if mfr_pn and _normalize(mfr_pn) == target:
                return "ok", name or description, specs or None, f"zoro:{url}"

        return "not_found", None, None, source

    except Exception as exc:
        logger.exception("Zoro scrape failed for %s %s: %s", brand, part_number, exc)
        return "error", None, None, source
