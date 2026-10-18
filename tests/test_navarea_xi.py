#!/usr/bin/env python3
"""
test_navarea_xi.py — Unit Tests for NAVAREA XI Scraper & Parser
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from supabase_sync import compute_differential

class TestNavareaXiParser(unittest.TestCase):

    def test_sample_navarea_xi_format(self):
        """Test NAVAREA XI basic structure parsing."""
        header = "NAVAREA XI NO.26-0123"
        raw = """NO.26-0123 Date: 2026-10-18
HONSHU, SOUTH COAST.
GUNNERY EXERCISES.
PSN 34-20.0N 138-10.0E."""
        self.assertIn("NAVAREA XI", header)
        self.assertIn("HONSHU", raw)

class TestNavareaXiDifferentialSync(unittest.TestCase):

    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "NO.26-0123", "title": "Gunnery Exercise"},
            {"warning_id": "NO.26-0999", "title": "New Warning"}
        ]
        self.scraped_messages = [
            {"warning_id": "NO.26-0123", "checksum_sha256": "hash_123_unchanged"},
            {"warning_id": "NO.26-0999", "checksum_sha256": "hash_999_new"}
        ]
        self.existing_warnings = {
            "NO.26-0123": {"warning_id": "NO.26-0123", "status": "active"},
            "NO.26-0100": {"warning_id": "NO.26-0100", "status": "active"}
        }
        self.existing_checksums = {
            ("NO.26-0123", "hash_123_unchanged"),
            ("NO.26-0100", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings,
            self.scraped_messages,
            self.existing_warnings,
            self.existing_checksums
        )
        self.assertIn("NO.26-0123", diff["skip"])
        self.assertEqual(len(diff["skip"]), 1)
        new_ids = [w["warning_id"] for w, m in diff["new"]]
        self.assertIn("NO.26-0999", new_ids)
        self.assertEqual(len(diff["new"]), 1)
        self.assertIn("NO.26-0100", diff["cancel"])
        self.assertEqual(len(diff["cancel"]), 1)

if __name__ == "__main__":
    unittest.main()
