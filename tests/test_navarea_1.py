#!/usr/bin/env python3
"""test_navarea_1.py — Unit Tests for NAVAREA I Parser"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.navarea_1_parser import parse_warning
from shared.utils import compute_differential

import unittest

class TestNavarea1Parser(unittest.TestCase):
    def test_sample_firing_exercise(self):
        header = "NAVAREA I 123/25"
        raw = """080056 UTC OCT 2025
ENGLISH CHANNEL. DOVER.
FIRING EXERCISE IN PROGRESS.
09 OCT 0600 TO 14 OCT 2000 UTC.
PSN 50-45.0N 001-20.0E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "123/25")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080056 UTC OCT 2025")
        self.assertAlmostEqual(nav_warn["latitude"], 50.75, places=2)

    def test_sample_drifting_container(self):
        header = "NAVAREA I 124/25"
        raw = """070800 UTC OCT 2025
NORTH SEA. 55-30.5N 003-25.8E.
CONTAINER ADRIFT."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "124/25")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertAlmostEqual(nav_warn["latitude"], 55.508333, places=4)

    def test_sample_unlit_buoy(self):
        header = "NAVAREA I 125/25"
        raw = """010929 UTC OCT 2025
NORTH SEA. ORFORDNESS.
LIGHT BUOY 'ORFORD' FL G 3S UNLIT.
PSN 52-07.7N 003-56.4E."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "125/25")
        self.assertEqual(nav_warn["category"], "aton")

    def test_coordinate_conversion(self):
        from shared.utils import convert_to_decimal
        self.assertAlmostEqual(convert_to_decimal("50", "45.0", "N"), 50.75, places=4)
        self.assertAlmostEqual(convert_to_decimal("001", "20.0", "W"), -1.333333, places=4)


class TestNavarea1DifferentialSync(unittest.TestCase):
    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "123/25", "title": "Dover"},
            {"warning_id": "124/25", "title": "Container"},
            {"warning_id": "999/25", "title": "New"}
        ]
        self.scraped_messages = [
            {"warning_id": "123/25", "checksum_sha256": "hash_123_unchanged"},
            {"warning_id": "124/25", "checksum_sha256": "hash_124_new"},
            {"warning_id": "999/25", "checksum_sha256": "hash_999_new"}
        ]
        self.existing_warnings = {
            "123/25": {"warning_id": "123/25", "status": "active"},
            "124/25": {"warning_id": "124/25", "status": "active"},
            "100/25": {"warning_id": "100/25", "status": "active"}
        }
        self.existing_checksums = {
            ("123/25", "hash_123_unchanged"),
            ("124/25", "hash_124_old"),
            ("100/25", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings, self.scraped_messages,
            self.existing_warnings, self.existing_checksums
        )
        self.assertIn("123/25", diff["skip"])
        self.assertEqual(len(diff["skip"]), 1)
        new_ids = [w["warning_id"] for w, m in diff["new"]]
        self.assertIn("999/25", new_ids)
        self.assertEqual(len(diff["new"]), 1)
        update_ids = [w["warning_id"] for w, m in diff["update"]]
        self.assertIn("124/25", update_ids)
        self.assertEqual(len(diff["update"]), 1)
        self.assertIn("100/25", diff["cancel"])
        self.assertEqual(len(diff["cancel"]), 1)


if __name__ == "__main__":
    unittest.main()
