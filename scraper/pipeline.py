"""
Async scraping pipeline — processes the full catalog.

Runs scrapers in priority order per brand:
  1. Brand-specific scraper (Parker, SMC, etc.)
  2. Grainger fallback (covers most brands)

Results are cached in SQLite so the pipeline is resumable.
Outputs data/enriched_data.csv with new scraped_* columns merged in.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
from tqdm.asyncio import tqdm

from scraper.cache import ScrapeCache
from scraper.http import make_client
from scraper.parsers import grainger

logger = logging.getLogger(__name__)

CLEAN_PATH    = Path("data/cleaned_data.csv")
ENRICHED_PATH = Path("data/enriched_data.csv")

# Brand name → scraper module (None = Grainger only)
BRAND_SCRAPERS = {
    "parker":        "scraper.parsers.parker",
    "smc":           "scraper.parsers.smc",
}

# Max concurrent scrape tasks — tune based on available bandwidth
# 30 is safe for a home/office connection; raise to 80+ on a cloud instance
DEFAULT_CONCURRENCY = 30


async def _scrape_one(
    brand: str,
    part_number: str,
    client: httpx.AsyncClient,
    cache: ScrapeCache,
    semaphore: asyncio.Semaphore,
):
    async with semaphore:
        # Check brand-specific scraper first
        brand_key = brand.lower()
        status = description = specs = source = None

        if brand_key in BRAND_SCRAPERS:
            import importlib
            mod = importlib.import_module(BRAND_SCRAPERS[brand_key])
            status, description, specs, source = await mod.scrape(part_number, client)

        # Grainger fallback if brand scraper missed or errored
        if status != "ok":
            status, description, specs, source = await grainger.scrape(
                brand, part_number, client
            )

        cache.set(
            brand=brand,
            part_number=part_number,
            source=source,
            scraped_description=description,
            scraped_specs=specs,
            status=status,
        )
        return status


async def run(
    concurrency: int = DEFAULT_CONCURRENCY,
    force: bool = False,
    limit: Optional[int] = None,
):
    """
    Main async pipeline.

    Parameters
    ----------
    concurrency : Max simultaneous requests.
    force       : Re-scrape even if already cached.
    limit       : If set, only scrape this many parts (useful for testing).
    """
    cache = ScrapeCache()
    df    = pd.read_csv(CLEAN_PATH, dtype=str)
    df    = df[df["manufacturer_part_number"].notna() & df["brand_name"].notna()]

    pending = cache.pending(df, force=force)
    if limit:
        pending = pending.head(limit)

    total = len(pending)
    print(f"Parts to scrape: {total:,}  (cached ok: {cache.stats().get('ok', 0):,})")

    if total == 0:
        print("Nothing to scrape.")
        _export(df, cache)
        return

    semaphore = asyncio.Semaphore(concurrency)
    counts = {"ok": 0, "not_found": 0, "error": 0}

    async with make_client() as client:
        tasks = [
            _scrape_one(
                row["brand_name"],
                row["manufacturer_part_number"],
                client,
                cache,
                semaphore,
            )
            for _, row in pending.iterrows()
        ]

        async for coro in tqdm(asyncio.as_completed(tasks), total=total, desc="Scraping"):
            status = await coro
            counts[status] = counts.get(status, 0) + 1

    print(f"\nDone: {counts}")
    _export(df, cache)
    cache.close()


def _export(df: pd.DataFrame, cache: ScrapeCache):
    """Merge scraped results back into the catalog and save enriched CSV."""
    import json
    import sqlite3

    conn = sqlite3.connect(str(cache._conn.execute("PRAGMA database_list").fetchone()[2] if hasattr(cache, '_conn') else "data/scrape_cache.db"))

    results = pd.read_sql(
        "SELECT brand, part_number, source, scraped_description, scraped_specs, status FROM scrape_results WHERE status='ok'",
        conn,
    )
    conn.close()

    if results.empty:
        print("No scraped results to merge yet.")
        df.to_csv(ENRICHED_PATH, index=False)
        return

    # Expand scraped_specs JSON into individual columns prefixed with 'web_'
    def _expand_specs(json_str):
        if not json_str:
            return {}
        try:
            return json.loads(json_str)
        except Exception:
            return {}

    specs_expanded = results["scraped_specs"].apply(_expand_specs)
    specs_df = pd.json_normalize(specs_expanded).add_prefix("web_")
    specs_df.columns = [c.lower().replace(" ", "_") for c in specs_df.columns]

    results = pd.concat(
        [results[["brand", "part_number", "source", "scraped_description"]], specs_df],
        axis=1,
    )

    # Join back to catalog
    df["_brand_key"] = df["brand_name"].str.lower()
    df["_pn_key"]    = df["manufacturer_part_number"].str.upper()
    results["_brand_key"] = results["brand"].str.lower()
    results["_pn_key"]    = results["part_number"].str.upper()

    enriched = df.merge(
        results.drop(columns=["brand", "part_number"]),
        on=["_brand_key", "_pn_key"],
        how="left",
    ).drop(columns=["_brand_key", "_pn_key"])

    enriched.to_csv(ENRICHED_PATH, index=False)

    filled = enriched["scraped_description"].notna().sum()
    web_cols = [c for c in enriched.columns if c.startswith("web_")]
    print(f"\nExported → {ENRICHED_PATH}")
    print(f"  Parts with scraped description : {filled:,}")
    print(f"  Web spec columns added         : {len(web_cols)}")
    if web_cols:
        print("  Top web spec columns:")
        for col in web_cols[:10]:
            n = enriched[col].notna().sum()
            print(f"    {col:<40} {n:,} filled")
