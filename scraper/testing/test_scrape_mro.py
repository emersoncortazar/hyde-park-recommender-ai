import os
import re
import json
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("SCRAPERAPI_KEY")
TARGET_URL = "https://www.mrostop.com/e3p-humphrey-products-pneumatic-directional-valve"

if not API_KEY:
    raise EnvironmentError("SCRAPERAPI_KEY not found in .env")


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def get_scraped_html(url: str, api_key: str) -> str:
    payload = {
        "api_key": api_key,
        "url": url,
        "render": "true",
        "premium": "true",
        "country_code": "us",
        "device_type": "desktop",
    }

    response = requests.get("https://api.scraperapi.com", params=payload, timeout=120)
    response.raise_for_status()
    return response.text


def extract_attribute_table(soup: BeautifulSoup) -> dict[str, str]:
    """
    Extract key/value pairs from the product attribute table.
    Handles generic table rows like:
      <tr><td>Manufacturer PartNumber</td><td>E3P</td></tr>
    """
    attributes: dict[str, str] = {}

    wrapper = soup.select_one("div.tab-content__wrapper.attribute_table")
    if not wrapper:
        return attributes

    table = wrapper.find("table")
    if not table:
        return attributes

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            key = clean_text(cells[0].get_text(" ", strip=True))
            value = clean_text(cells[1].get_text(" ", strip=True))
            if key and value:
                attributes[key] = value

    return attributes


def extract_text_block(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if not node:
        return None
    return clean_text(node.get_text(" ", strip=True))


def parse_item_number(main_text: str | None) -> str | None:
    if not main_text:
        return None
    match = re.search(r"Item\s*#:\s*([A-Za-z0-9\-]+)", main_text, re.I)
    return match.group(1).strip() if match else None


def scrape_mrostop_product(url: str, api_key: str) -> dict:
    html = get_scraped_html(url, api_key)
    soup = BeautifulSoup(html, "html.parser")

    product: dict = {
        "url": url,
        "title_tag": None,
        "name": None,
        "item_number": None,
        "short_description": None,
        "description": None,
        "manufacturer_description": None,
        "attributes": {},
        "manufacturer": None,
        "manufacturer_part_number": None,
    }

    if soup.title:
        product["title_tag"] = clean_text(soup.title.get_text(" ", strip=True))

    h1 = soup.find("h1")
    if h1:
        product["name"] = clean_text(h1.get_text(" ", strip=True))

    main_content = soup.select_one("div.product-view__content.price-on")
    if main_content:
        main_text = clean_text(main_content.get_text(" ", strip=True))
        product["item_number"] = parse_item_number(main_text)

    product["short_description"] = extract_text_block(
        soup, "div.product-view__short-description"
    )
    product["description"] = extract_text_block(
        soup, "div.tab-content__wrapper.descriptions"
    )
    product["manufacturer_description"] = extract_text_block(
        soup, "div.tab-content__wrapper.manufacturer_description"
    )

    attributes = extract_attribute_table(soup)
    product["attributes"] = attributes

    # Map common fields out of the attributes table
    product["manufacturer"] = attributes.get("Manufacturer") or attributes.get("Brand")
    product["manufacturer_part_number"] = (
        attributes.get("Manufacturer PartNumber")
        or attributes.get("Manufacturer Part Number")
        or attributes.get("Part Number")
        or attributes.get("MPN")
    )

    return product


if __name__ == "__main__":
    data = scrape_mrostop_product(TARGET_URL, API_KEY)
    print(json.dumps(data, indent=2, ensure_ascii=False))