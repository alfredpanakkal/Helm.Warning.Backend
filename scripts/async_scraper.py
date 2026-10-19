#!/usr/bin/env python3
"""
scripts/async_scraper.py — High-Throughput Asynchronous Scraper for NAVAREA Feeds
Provides concurrent fetching with rate limiting, timeouts, and fallback to synchronous threads.
"""

import asyncio
import urllib.request
import urllib.error
from typing import Dict, List, Optional
from shared.logging import get_logger
from shared.metrics import metrics
from shared.circuit_breaker import circuit_breaker

logger = get_logger("async_scraper")


class AsyncScraper:
    """Concurrent scraper using asyncio and non-blocking executors."""

    def __init__(self, timeout: int = 30, max_concurrent: int = 5, user_agent: str = "HelmWarningBot/1.0"):
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.user_agent = user_agent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _sync_fetch(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,text/plain,*/*"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            content_bytes = resp.read()
            # Attempt UTF-8, fall back to latin-1
            try:
                return content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return content_bytes.decode("latin-1", errors="replace")

    async def fetch_url(self, url: str) -> str:
        """Fetches a single URL asynchronously within the semaphore limit."""
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            start_t = loop.time()
            try:
                content = await loop.run_in_executor(None, self._sync_fetch, url)
                duration = loop.time() - start_t
                metrics.counter("http_requests_total", labels={"status": "200"}).increment()
                metrics.histogram("http_request_duration_seconds").observe(duration)
                logger.info(f"Successfully fetched {url} in {duration:.2f}s ({len(content)} chars)")
                return content
            except Exception as e:
                duration = loop.time() - start_t
                metrics.counter("http_requests_total", labels={"status": "error"}).increment()
                logger.error(f"Failed to fetch {url} after {duration:.2f}s: {e}")
                raise

    async def fetch_multiple(self, urls: Dict[str, str]) -> Dict[str, Optional[str]]:
        """
        Concurrently fetches multiple feeds.
        urls is a dict mapping region_name -> url.
        Returns dict mapping region_name -> content (or None on failure).
        """
        results: Dict[str, Optional[str]] = {}

        async def _fetch_task(region: str, target_url: str):
            try:
                results[region] = await self.fetch_url(target_url)
            except Exception as e:
                results[region] = None
                logger.warning(f"Error fetching {region} feed ({target_url}): {e}")

        tasks = [_fetch_task(reg, u) for reg, u in urls.items()]
        await asyncio.gather(*tasks)
        return results
