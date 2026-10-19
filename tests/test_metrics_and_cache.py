#!/usr/bin/env python3
"""
tests/test_metrics_and_cache.py — Unit Tests for Metrics Collection & Caching Layer
"""

import unittest
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.metrics import Metrics
from shared.cache import InMemoryCache, cached


class TestMetricsAndCache(unittest.TestCase):

    def test_metrics_counters_and_gauges(self):
        m = Metrics()
        c = m.counter("warnings_scraped_total", description="Total scraped warnings", labels={"region": "Baltic"})
        c.increment(5)
        self.assertEqual(c.get(), 5)

        g = m.gauge("active_warnings_count", description="Current active count")
        g.set(42)
        g.increment(3)
        self.assertEqual(g.get(), 45)

        h = m.histogram("parse_latency_seconds", description="Latency", buckets=[0.1, 0.5, 1.0])
        h.observe(0.05)
        h.observe(0.3)
        h.observe(1.2)
        summary = h.get_summary()
        self.assertEqual(summary["count"], 3)

        prom_text = m.to_prometheus()
        self.assertIn("warnings_scraped_total", prom_text)
        self.assertIn("active_warnings_count", prom_text)
        self.assertIn("parse_latency_seconds_count", prom_text)

    def test_in_memory_cache_ttl_and_expiry(self):
        cache = InMemoryCache(default_ttl=0.05, max_size=10)
        cache.set("key1", "val1")
        self.assertEqual(cache.get("key1"), "val1")

        # Wait for TTL to expire
        time.sleep(0.06)
        self.assertIsNone(cache.get("key1"))

    def test_in_memory_cache_max_size_eviction(self):
        cache = InMemoryCache(default_ttl=60.0, max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        self.assertEqual(cache.size(), 3)

        # Adding 4th item triggers eviction of oldest
        cache.set("d", 4)
        self.assertLessEqual(cache.size(), 3)
        self.assertEqual(cache.get("d"), 4)

    def test_cached_decorator(self):
        call_count = 0

        @cached(ttl=60.0)
        def compute_expensive(x, y):
            nonlocal call_count
            call_count += 1
            return x * y

        res1 = compute_expensive(4, 5)
        res2 = compute_expensive(4, 5)
        self.assertEqual(res1, 20)
        self.assertEqual(res2, 20)
        self.assertEqual(call_count, 1)  # Cached


if __name__ == "__main__":
    unittest.main()
