"""
Async HTTP client with per-domain rate limiting and retry logic.

When SCRAPERAPI_KEY is set in .env, requests are routed through ScraperAPI's
proxy to bypass Akamai and other bot protection. Otherwise, requests go direct.
"""

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCRAPERAPI_KEY: Optional[str] = os.environ.get("SCRAPERAPI_KEY")
SCRAPERAPI_BASE = "https://api.scraperapi.com"

# Seconds between requests to the same domain — avoids getting blocked
# When using ScraperAPI, rate limits apply to the proxy endpoint instead
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

# ScraperAPI handles rate limiting on their end, so we can be less aggressive
RATE_LIMITS_PROXY = {
    "default": 0.3,
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
        limits = RATE_LIMITS_PROXY if SCRAPERAPI_KEY else RATE_LIMITS
        async with self._locks[domain]:
            gap = limits.get(domain, limits["default"])
            elapsed = time.monotonic() - self._last[domain]
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
            self._last[domain] = time.monotonic()


_rate_limiter = RateLimiter()


def _proxy_url(url: str, params: Optional[dict] = None, render: bool = False) -> str:
    """Build a ScraperAPI proxy URL for the given target URL."""
    # If the original request has query params, bake them into the target URL
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urlencode(params)
    proxy_params = {"api_key": SCRAPERAPI_KEY, "url": url}
    if render:
        proxy_params["render"] = "true"
    return f"{SCRAPERAPI_BASE}?{urlencode(proxy_params)}"


async def get(
    url: str,
    client: httpx.AsyncClient,
    params: Optional[dict] = None,
    retries: int = 3,
    timeout: float = 90.0,
    render: bool = False,
) -> Optional[httpx.Response]:
    """
    Fetch a URL with rate limiting and exponential-backoff retry.
    Routes through ScraperAPI when SCRAPERAPI_KEY is set.
    Pass render=True for JS-heavy pages (costs more API credits).
    Returns None on permanent failure.
    """
    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    for attempt in range(retries):
        await _rate_limiter.wait(domain)
        try:
            if SCRAPERAPI_KEY:
                fetch_url = _proxy_url(url, params, render=render)
                resp = await client.get(fetch_url, timeout=timeout)
            else:
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
        timeout=60.0,
    )
