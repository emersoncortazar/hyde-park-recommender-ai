"""
Site comparison tester — fetches a handful of sample parts across multiple sites
to find the best source of structured spec data before committing API tokens.

Tests three sites:
  - MROStop    : URL constructed from default_name slug (no search needed)
  - Grainger   : search by "brand part_number", parse first matching product page
  - McMaster   : direct URL by part number (works for some catalogs)

Each site is tried twice: direct HTTP first, then ScraperAPI (no render).
Prints a summary table of attribute counts and sample keys so you can
pick the best source before running the full pipeline.

Usage:
    python -m scraper.testing.test_sites
    python -m scraper.testing.test_sites --render    # also test with JS rendering
    python -m scraper.testing.test_sites --parts 10  # test more parts
"""

import argparse
import json
import os
import re
import sys
import textwrap

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

API_KEY = os.getenv("SCRAPERAPI_KEY")
if not API_KEY:
    sys.exit("SCRAPERAPI_KEY not found in .env")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT_DIRECT = 15
TIMEOUT_SCRAPER = 90


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_direct(url: str) -> tuple[str | None, int | None]:
    """Plain HTTP GET — no ScraperAPI."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_DIRECT)
        return (r.text if r.status_code == 200 else None), r.status_code
    except Exception as exc:
        return None, str(exc)


def fetch_scraperapi(url: str, render: bool = False) -> tuple[str | None, int | None]:
    """Fetch via ScraperAPI. render=True costs 5x more credits."""
    params = {
        "api_key": API_KEY,
        "url": url,
        "country_code": "us",
        "device_type": "desktop",
    }
    if render:
        params["render"] = "true"
    try:
        r = requests.get(
            "https://api.scraperapi.com", params=params, timeout=TIMEOUT_SCRAPER
        )
        return (r.text if r.status_code == 200 else None), r.status_code
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

def mrostop_url(default_name: str) -> str:
    slug = default_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"https://www.mrostop.com/{slug}"


def grainger_search_url(brand: str, part_number: str) -> str:
    query = f"{brand} {part_number}".replace(" ", "+")
    return f"https://www.grainger.com/search?searchQuery={query}"


def mcmaster_url(part_number: str) -> str:
    return f"https://www.mcmaster.com/{part_number}/"


# ---------------------------------------------------------------------------
# Parsers — return dict of {attr_name: value}
# ---------------------------------------------------------------------------

def parse_mrostop(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    attrs = {}
    wrapper = soup.select_one("div.tab-content__wrapper.attribute_table")
    if wrapper:
        table = wrapper.find("table")
        if table:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    k = cells[0].get_text(" ", strip=True).strip()
                    v = cells[1].get_text(" ", strip=True).strip()
                    if k and v:
                        attrs[k] = v
    return attrs


def _parse_jsonld_specs(html: str) -> dict:
    """Extract additionalProperty specs from any JSON-LD Product block."""
    soup = BeautifulSoup(html, "html.parser")
    specs = {}
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Product"), data[0])
            if data.get("@type") in ("Product", "ItemPage"):
                for prop in data.get("additionalProperty", []):
                    name = prop.get("name", "").strip()
                    value = prop.get("value", "")
                    if name:
                        specs[name] = str(value).strip()
        except Exception:
            continue
    return specs


def _parse_html_table_specs(html: str, selectors: list[str]) -> dict:
    """Generic HTML table parser given a list of CSS selectors to try."""
    soup = BeautifulSoup(html, "html.parser")
    specs = {}
    for sel in selectors:
        for table in soup.select(sel):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    k = cells[0].get_text(strip=True)
                    v = cells[1].get_text(strip=True)
                    if k and v:
                        specs[k] = v
            if specs:
                return specs
    return specs


def parse_grainger(html: str) -> dict:
    specs = _parse_jsonld_specs(html)
    if not specs:
        specs = _parse_html_table_specs(
            html,
            [
                "table.specs-table",
                "[data-testid='specs-table']",
                ".product-specs table",
            ],
        )
    return specs


def parse_mcmaster(html: str) -> dict:
    specs = _parse_jsonld_specs(html)
    if not specs:
        specs = _parse_html_table_specs(
            html,
            [
                "table.SpecsTable",
                "table[data-specs]",
                ".ProductSpecs table",
                "table",  # broad fallback
            ],
        )
    return specs


# ---------------------------------------------------------------------------
# Per-site test logic
# ---------------------------------------------------------------------------

DEBUG = False  # set by --debug flag


def _result_row(site: str, mode: str, url: str, attrs: dict, status, html: str | None = None) -> dict:
    sample_keys = list(attrs.keys())[:5]
    if DEBUG and html is not None:
        snippet = html[:300].replace("\n", " ")
        print(f"    [{mode}] URL: {url}")
        print(f"    [{mode}] HTML snippet: {snippet[:200]}")
    return {
        "site": site,
        "mode": mode,
        "url": url,
        "status": status,
        "attr_count": len(attrs),
        "sample_keys": ", ".join(sample_keys) if sample_keys else "-",
    }


def test_mrostop(part: dict, render: bool) -> list[dict]:
    url = mrostop_url(part["default_name"])
    rows = []

    html, status = fetch_direct(url)
    attrs = parse_mrostop(html) if html else {}
    rows.append(_result_row("MROStop", "direct", url, attrs, status, html))

    html, status = fetch_scraperapi(url, render=False)
    attrs = parse_mrostop(html) if html else {}
    rows.append(_result_row("MROStop", "scraperapi", url, attrs, status, html))

    if render:
        html, status = fetch_scraperapi(url, render=True)
        attrs = parse_mrostop(html) if html else {}
        rows.append(_result_row("MROStop", "scraperapi+render", url, attrs, status, html))

    return rows


def test_grainger(part: dict, render: bool) -> list[dict]:
    url = grainger_search_url(part["brand_name"], part["manufacturer_part_number"])
    rows = []

    # Direct fetch of search page — likely blocked, but worth checking
    html, status = fetch_direct(url)
    # If we got the search results, try to find product URL and fetch it
    product_url = url  # fallback: report search URL stats
    attrs = {}
    if html:
        soup = BeautifulSoup(html, "html.parser")
        nd = soup.find("script", {"id": "__NEXT_DATA__"})
        if nd:
            try:
                data = json.loads(nd.string)
                products = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("searchResults", {})
                        .get("products", [])
                )
                for p in products[:5]:
                    if p.get("mfrPartNumber", "").upper() == part["manufacturer_part_number"].upper():
                        path = p.get("productUrl") or p.get("pdpUrl", "")
                        if path:
                            product_url = "https://www.grainger.com" + path if path.startswith("/") else path
                            ph, ps = fetch_direct(product_url)
                            attrs = parse_grainger(ph) if ph else {}
                            break
            except Exception:
                pass
    rows.append(_result_row("Grainger", "direct", product_url, attrs, status))

    # ScraperAPI on search page → follow to product
    html, status = fetch_scraperapi(url, render=False)
    attrs = {}
    product_url = url
    if html:
        attrs = parse_grainger(html)  # sometimes specs are on search page
        if not attrs:
            soup = BeautifulSoup(html, "html.parser")
            nd = soup.find("script", {"id": "__NEXT_DATA__"})
            if nd:
                try:
                    data = json.loads(nd.string)
                    products = (
                        data.get("props", {})
                            .get("pageProps", {})
                            .get("searchResults", {})
                            .get("products", [])
                    )
                    for p in products[:5]:
                        if p.get("mfrPartNumber", "").upper() == part["manufacturer_part_number"].upper():
                            path = p.get("productUrl") or p.get("pdpUrl", "")
                            if path:
                                product_url = "https://www.grainger.com" + path if path.startswith("/") else path
                                ph, _ = fetch_scraperapi(product_url, render=False)
                                attrs = parse_grainger(ph) if ph else {}
                                break
                except Exception:
                    pass
    rows.append(_result_row("Grainger", "scraperapi", product_url, attrs, status))

    if render:
        html, status = fetch_scraperapi(url, render=True)
        attrs = parse_grainger(html) if html else {}
        rows.append(_result_row("Grainger", "scraperapi+render", url, attrs, status))

    return rows


def test_mcmaster(part: dict, render: bool) -> list[dict]:
    url = mcmaster_url(part["manufacturer_part_number"])
    rows = []

    html, status = fetch_direct(url)
    attrs = parse_mcmaster(html) if html else {}
    rows.append(_result_row("McMaster", "direct", url, attrs, status))

    html, status = fetch_scraperapi(url, render=False)
    attrs = parse_mcmaster(html) if html else {}
    rows.append(_result_row("McMaster", "scraperapi", url, attrs, status))

    if render:
        html, status = fetch_scraperapi(url, render=True)
        attrs = parse_mcmaster(html) if html else {}
        rows.append(_result_row("McMaster", "scraperapi+render", url, attrs, status))

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_sample_parts(n: int) -> list[dict]:
    df = pd.read_csv("data/cleaned_data.csv", dtype=str)
    df = df.dropna(subset=["default_name", "brand_name", "manufacturer_part_number"])

    # Prefer parts we know are on MROStop (have mro_description) — one per brand
    has_mro = df[df["mro_description"].notna()]
    sample = (
        has_mro.groupby("brand_name")
        .first()
        .reset_index()
        .head(n)
        [["brand_name", "manufacturer_part_number", "default_name"]]
        .to_dict("records")
    )
    return sample


def print_results(all_rows: list[dict]):
    # Group by part for readability
    col_widths = {"site": 8, "mode": 18, "attr_count": 6, "status": 6, "sample_keys": 60}
    header = (
        f"{'Site':<{col_widths['site']}} "
        f"{'Mode':<{col_widths['mode']}} "
        f"{'Attrs':>{col_widths['attr_count']}} "
        f"{'HTTP':<{col_widths['status']}} "
        f"{'Sample attribute keys':<{col_widths['sample_keys']}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)
    for row in all_rows:
        keys = textwrap.shorten(row["sample_keys"], width=col_widths["sample_keys"])
        print(
            f"{row['site']:<{col_widths['site']}} "
            f"{row['mode']:<{col_widths['mode']}} "
            f"{row['attr_count']:>{col_widths['attr_count']}} "
            f"{str(row['status']):<{col_widths['status']}} "
            f"{keys}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", type=int, default=5, help="Number of sample parts to test (default: 5)")
    parser.add_argument("--render", action="store_true", help="Also test ScraperAPI with JS rendering (costs 5x credits)")
    parser.add_argument("--sites", nargs="+", choices=["mrostop", "grainger", "mcmaster"], default=["mrostop", "grainger", "mcmaster"])
    parser.add_argument("--debug", action="store_true", help="Print URL and HTML snippet for each fetch")
    args = parser.parse_args()

    global DEBUG
    DEBUG = args.debug
    parts = load_sample_parts(args.parts)
    print(f"\nTesting {len(parts)} parts across sites: {', '.join(args.sites)}")
    print(f"Render mode: {'ON (5x credits)' if args.render else 'OFF (1 credit each)'}\n")

    site_fns = {
        "mrostop": test_mrostop,
        "grainger": test_grainger,
        "mcmaster": test_mcmaster,
    }

    for i, part in enumerate(parts, 1):
        print(f"\n{'='*80}")
        print(f"Part {i}/{len(parts)}: {part['manufacturer_part_number']} | {part['brand_name']}")
        print(f"  Name: {part['default_name']}")
        print(f"{'='*80}")

        all_rows = []
        for site in args.sites:
            print(f"  Fetching {site}...", flush=True)
            rows = site_fns[site](part, args.render)
            all_rows.extend(rows)

        print()
        print_results(all_rows)

    print("\nDone.")


if __name__ == "__main__":
    main()
