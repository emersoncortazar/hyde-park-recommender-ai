#!/usr/bin/env python3
"""
Run the web scraping pipeline to enrich the parts catalog with specs
from Grainger, Parker, SMC, and other manufacturer websites.

Output: data/enriched_data.csv  (cleaned_data.csv + web_* spec columns)
Cache:  data/scrape_cache.db    (SQLite — pipeline is resumable)

Usage:
  # Full run — scrape everything not yet cached (runs overnight for 292k parts)
  python scripts/run_scraper.py

  # Test with 100 parts first
  python scripts/run_scraper.py --limit 100

  # Re-scrape everything even if cached
  python scripts/run_scraper.py --force

  # Higher concurrency for a cloud instance (default 30)
  python scripts/run_scraper.py --concurrency 80

  # Check cache stats without running
  python scripts/run_scraper.py --stats
"""

import argparse
import asyncio
import logging
import sys

sys.path.insert(0, ".")

from scraper.cache import ScrapeCache
from scraper.pipeline import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


def show_stats():
    cache = ScrapeCache()
    stats = cache.stats()
    total = sum(stats.values())
    print(f"\nScrape cache stats ({total:,} total):")
    for status, count in sorted(stats.items()):
        print(f"  {status:<12} {count:,}")
    cache.close()


def main():
    parser = argparse.ArgumentParser(description="MRO parts web scraper")
    parser.add_argument("--limit",       type=int, default=None,  help="Only scrape N parts (for testing)")
    parser.add_argument("--concurrency", type=int, default=30,    help="Max concurrent requests (default 30; use 80+ on cloud)")
    parser.add_argument("--force",       action="store_true",     help="Re-scrape even if already cached")
    parser.add_argument("--stats",       action="store_true",     help="Show cache stats and exit")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    print(f"Concurrency: {args.concurrency}  |  Force: {args.force}  |  Limit: {args.limit or 'all'}")
    print()

    asyncio.run(run(
        concurrency=args.concurrency,
        force=args.force,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
