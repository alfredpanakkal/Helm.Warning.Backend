#!/usr/bin/env python3
"""test_baltic.py — Unit Tests for NAVAREA Baltic Parser"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.baltic_parser import parse_warning
from shared.utils import compute_differential

import unittest

class TestBalticParser(unittest.TestCase):
    def test_sample_1_skagerrak_detonations_polygon(self):
        header = "SWEDISH NAV WARN 168/26 [Skagerrak]"
        raw = """080056 UTC OCT
SKAGERRAK. LYSEKIL. BONDEN
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS
09 OCT 0600 LT – 14 OCT 2000 LT
PSN:
58-10.2N 011-13.3E
58-13.3N 011-13.3E
58-13.3N 011-17.4E
58-10.2N 011-13.3E
500 MTR CLEARANCE FROM THE AREA IS REQUESTED."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 168/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080056 UTC OCT 2026")
        self.assertIsNotNone(spatial)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertAlmostEqual(nav_warn["latitude"], 58.195834, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 11.238750, places=4)

    def test_sample_2_kattegat_point(self):
        header = "SWEDISH NAV WARN 167/26 [Kattegat]"
        raw = """080035 UTC OCT
KATTEGAT. MARSTRAND. STORA PÖLSAN.
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS.
09 OCT 0600 LT - 14 OCT 2000 LT.
PSN: 57-47.0N 011-27.9E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 167/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080035 UTC OCT 2026")
        self.assertEqual(spatial["type"], "Point")

    def test_sample_3_gnss_interference(self):
        header = "BALTIC SEA NAV WARN 026/25 [Western Baltic, Central Baltic]"
        raw = """021100 UTC JUL
SOUTHERN, SOUTHEASTERN, CENTRAL AND NORTHERN BALTIC.
GNSS, AIS, RADAR AND DGPS INTERFERENCE OBSERVED."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "BALTIC 026/25")
        self.assertEqual(nav_warn["category"], "electronic")
        self.assertEqual(nav_warn["issued_text"], "021100 UTC JUL 2025")

    def test_coordinate_parsing(self):
        from shared.utils import parse_coordinates
        coords, lat, lon, spatial = parse_coordinates("PSN 58-10.2N 011-13.3E")
        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, 58.17, places=4)
        self.assertAlmostEqual(lon, 11.221667, places=4)


class TestDifferentialSync(unittest.TestCase):
    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "SWEDISH 168/26", "title": "Lysekil"},
            {"warning_id": "SWEDISH 167/26", "title": "Stora Polsan"},
            {"warning_id": "SWEDISH 999/26", "title": "New"}
        ]
        self.scraped_messages = [
            {"warning_id": "SWEDISH 168/26", "checksum_sha256": "hash_168_unchanged"},
            {"warning_id": "SWEDISH 167/26", "checksum_sha256": "hash_167_new"},
            {"warning_id": "SWEDISH 999/26", "checksum_sha256": "hash_999_new"}
        ]
        self.existing_warnings = {
            "SWEDISH 168/26": {"warning_id": "SWEDISH 168/26", "status": "active"},
            "SWEDISH 167/26": {"warning_id": "SWEDISH 167/26", "status": "active"},
            "SWEDISH 100/26": {"warning_id": "SWEDISH 100/26", "status": "active"}
        }
        self.existing_checksums = {
            ("SWEDISH 168/26", "hash_168_unchanged"),
            ("SWEDISH 167/26", "hash_167_old"),
            ("SWEDISH 100/26", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings, self.scraped_messages,
            self.existing_warnings, self.existing_checksums
        )
        self.assertIn("SWEDISH 168/26", diff["skip"])
        self.assertEqual(len(diff["skip"]), 1)
        new_ids = [w["warning_id"] for w, m in diff["new"]]
        self.assertIn("SWEDISH 999/26", new_ids)
        self.assertEqual(len(diff["new"]), 1)
        update_ids = [w["warning_id"] for w, m in diff["update"]]
        self.assertIn("SWEDISH 167/26", update_ids)
        self.assertEqual(len(diff["update"]), 1)
        self.assertIn("SWEDISH 100/26", diff["cancel"])
        self.assertEqual(len(diff["cancel"]), 1)


if __name__ == "__main__":
    unittest.main()
