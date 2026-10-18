#!/usr/bin/env python3
"""test_navarea_xi.py — Unit Tests for NAVAREA XI Parser"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.navarea_xi_parser import parse_warning
from shared.utils import compute_differential

import unittest

class TestNavareaXiParser(unittest.TestCase):
    def test_sample_1_okinotori_shima(self):
        header = "NAVAREA XI NO.26-0451"
        raw = """NO.26-0451       Date:2026/10/09 07 UTC
NORTH PACIFIC, OKINOTORI SHIMA.
HATCH COVER ADRIFT IN 16-54.1N 134-39.5E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0451/26")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertEqual(nav_warn["issued_text"], "2026/10/09 07 UTC")

    def test_sample_2_military(self):
        header = "NAVAREA XI NO.26-0450"
        raw = """NO.26-0450       Date:2026/10/08 12 UTC
MARSHALL ISLANDS. GUNNERY EXERCISES."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0450/26")
        self.assertEqual(nav_warn["category"], "military")


class TestNavareaXiDifferentialSync(unittest.TestCase):
    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "NAVAREA XI 0451/26", "title": "OKINOTORI"},
            {"warning_id": "NAVAREA XI 0450/26", "title": "MARSHALLS"},
            {"warning_id": "NAVAREA XI 0999/26", "title": "New"}
        ]
        self.scraped_messages = [
            {"warning_id": "NAVAREA XI 0451/26", "checksum_sha256": "hash_451_unchanged"},
            {"warning_id": "NAVAREA XI 0450/26", "checksum_sha256": "hash_450_new"},
            {"warning_id": "NAVAREA XI 0999/26", "checksum_sha256": "hash_999_new"}
        ]
        self.existing_warnings = {
            "NAVAREA XI 0451/26": {"warning_id": "NAVAREA XI 0451/26", "status": "active"},
            "NAVAREA XI 0450/26": {"warning_id": "NAVAREA XI 0450/26", "status": "active"},
            "NAVAREA XI 0100/26": {"warning_id": "NAVAREA XI 0100/26", "status": "active"}
        }
        self.existing_checksums = {
            ("NAVAREA XI 0451/26", "hash_451_unchanged"),
            ("NAVAREA XI 0450/26", "hash_450_old"),
            ("NAVAREA XI 0100/26", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings, self.scraped_messages,
            self.existing_warnings, self.existing_checksums
        )
        self.assertIn("NAVAREA XI 0451/26", diff["skip"])
        self.assertEqual(len(diff["skip"]), 1)
        new_ids = [w["warning_id"] for w, m in diff["new"]]
        self.assertIn("NAVAREA XI 0999/26", new_ids)
        self.assertEqual(len(diff["new"]), 1)
        update_ids = [w["warning_id"] for w, m in diff["update"]]
        self.assertIn("NAVAREA XI 0450/26", update_ids)
        self.assertEqual(len(diff["update"]), 1)
        self.assertIn("NAVAREA XI 0100/26", diff["cancel"])
        self.assertEqual(len(diff["cancel"]), 1)


if __name__ == "__main__":
    unittest.main()
