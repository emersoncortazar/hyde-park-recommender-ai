"""
Async HTTP client with per-domain rate limiting and retry logic.
"""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Seconds between requests to the same domain — avoids getting blocked
RATE_LIMITS = {
    "www.grainger.com":         1.5,
    "ph.parker.com":            1.0,
    "www.smcusa.com":           1.0,
    "www.boschrexroth.com":     1.0,
    "www.aventics.com":         1.0,
    "www.hydac.com":            1.5,
    "www.balluff.com":          1.0,
    "default":                  1.0,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class RateLimiter:
    """Per-domain rate limiter — enforces minimum gap between requests."""

    def __init__(self):
        self._last: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, domain: str):
        async with self._locks[domain]:
            gap = RATE_LIMITS.get(domain, RATE_LIMITS["default"])
            elapsed = time.monotonic() - self._last[domain]
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
            self._last[domain] = time.monotonic()


_rate_limiter = RateLimiter()


async def get(
    url: str,
    client: httpx.AsyncClient,
    params: Optional[dict] = None,
    retries: int = 3,
    timeout: float = 15.0,
) -> Optional[httpx.Response]:
    """
    Fetch a URL with rate limiting and exponential-backoff retry.
    Returns None on permanent failure.
    """
    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    for attempt in range(retries):
        await _rate_limiter.wait(domain)
        try:
            resp = await client.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 404, 410):
                logger.debug("HTTP %s for %s — not retrying", resp.status_code, url)
                return resp
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                logger.warning("Rate limited on %s — waiting %ss", domain, wait)
                await asyncio.sleep(wait)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            wait = 2 ** attempt
            logger.warning("Request error (%s) for %s — retry in %ss", exc, url, wait)
            await asyncio.sleep(wait)

    logger.error("All retries exhausted for %s", url)
    return None


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=15.0,
    )
