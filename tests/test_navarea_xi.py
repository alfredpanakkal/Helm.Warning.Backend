#!/usr/bin/env python3
"""
test_navarea_xi.py - Unit Tests for NAVAREA XI Scraper & Parser
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from navareas.navarea_xi.parser import parse_warning
from shared.coordinates import convert_to_decimal, parse_coordinates
from shared.classification import classify_hazard
from shared.sync import compute_differential

class TestNavareaXIParser(unittest.TestCase):

    def test_sample_1_okinotori_shima(self):
        header = "NAVAREA XI NO.26-0451"
        raw = """NO.26-0451       Date:2026/10/09 07 UTC
NORTH PACIFIC, OKINOTORI SHIMA.
HATCH COVER, ABOUT 20 METRE IN SQUARE,
ADRIFT IN
16-54.1N 134-39.5E AT 090625Z OCT.
CANCEL 0450/26.
CANCEL THIS MSG 120625Z OCT."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0451/26")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertEqual(nav_warn["issued_text"], "2026/10/09 07 UTC")
        self.assertIsNotNone(spatial)
        self.assertEqual(spatial["type"], "Point")
        self.assertAlmostEqual(nav_warn["latitude"], 16.901667, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 134.658333, places=4)

    def test_sample_2_with_decimal_minutes(self):
        header = "NAVAREA XI NO.26-0123"
        raw = """NO.26-0123       Date:2026/05/15 10 UTC
NORTH PACIFIC.
DRIFTING OBJECT.
PSN: 24-04.12N 118-46.48E
REPORT SIGHTINGS TO AUTHORITIES."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0123/26")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertAlmostEqual(nav_warn["latitude"], 24.068667, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 118.774667, places=4)

    def test_sample_3_military_exercise(self):
        header = "NAVAREA XI NO.26-0500"
        raw = """NO.26-0500       Date:2026/06/20 08 UTC
EAST CHINA SEA.
NAVAL EXERCISE WILL BE CONDUCTED.
FIRING AND GUNNERY PRACTICE.
AREA: 30-00N 125-00E TO 31-00N 126-00E
DANGER PERIOD: 22 JUN TO 25 JUN."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0500/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertIn("NAVAL EXERCISE", nav_warn["raw_text"])

    def test_sample_4_gnss_interference(self):
        header = "NAVAREA XI NO.26-0750"
        raw = """NO.26-0750       Date:2026/07/01 12 UTC
PHILIPPINE SEA.
GNSS INTERFERENCE OBSERVED.
MARINERS ADVISED TO USE ALTERNATIVE NAVIGATION METHODS.
PSN: 15-00N 120-00E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0750/26")
        self.assertEqual(nav_warn["category"], "electronic")

class TestNavareaXICoordinateParsing(unittest.TestCase):

    def test_parse_with_decimal_minutes(self):
        raw = "PSN: 16-54.1N 134-39.5E"
        coords, lat, lon, spatial = parse_coordinates(raw)

        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, 16.901667, places=4)
        self.assertAlmostEqual(lon, 134.658333, places=4)
        self.assertEqual(spatial["type"], "Point")

    def test_parse_with_decimal_seconds(self):
        raw = "PSN: 24-04.12N 118-46.48E"
        coords, lat, lon, spatial = parse_coordinates(raw)

        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, 24.068667, places=4)
        self.assertAlmostEqual(lon, 118.774667, places=4)

    def test_parse_polygon(self):
        raw = """AREA:
16-54.1N 134-39.5E
17-00.0N 134-45.0E
17-00.0N 134-39.5E
16-54.1N 134-39.5E"""
        coords, lat, lon, spatial = parse_coordinates(raw)

        self.assertEqual(len(coords), 4)
        self.assertEqual(spatial["type"], "Polygon")

    def test_convert_with_seconds(self):
        result = convert_to_decimal("24", "04.12", "00", "N")
        self.assertAlmostEqual(result, 24.068667, places=6)

        result = convert_to_decimal("118", "46.48", "00", "E")
        self.assertAlmostEqual(result, 118.774667, places=6)

class TestDifferentialSync(unittest.TestCase):

    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "NAVAREA XI 0451/26", "title": "OKINOTORI SHIMA"},
            {"warning_id": "NAVAREA XI 0450/26", "title": "MARSHALLS"},
            {"warning_id": "NAVAREA XI 0999/26", "title": "Brand New Warning"}
        ]
        self.scraped_messages = [
            {"warning_id": "NAVAREA XI 0451/26", "checksum_sha256": "hash_451_unchanged"},
            {"warning_id": "NAVAREA XI 0450/26", "checksum_sha256": "hash_450_new_revision"},
            {"warning_id": "NAVAREA XI 0999/26", "checksum_sha256": "hash_999_brand_new"}
        ]
        self.existing_warnings = {
            "NAVAREA XI 0451/26": {"warning_id": "NAVAREA XI 0451/26", "status": "active"},
            "NAVAREA XI 0450/26": {"warning_id": "NAVAREA XI 0450/26", "status": "active"},
            "NAVAREA XI 0100/26": {"warning_id": "NAVAREA XI 0100/26", "status": "active"}
        }
        self.existing_checksums = {
            ("NAVAREA XI 0451/26", "hash_451_unchanged"),
            ("NAVAREA XI 0450/26", "hash_450_old_version"),
            ("NAVAREA XI 0100/26", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings,
            self.scraped_messages,
            self.existing_warnings,
            self.existing_checksums
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

class TestNavareaXIHazardClassification(unittest.TestCase):

    def test_electronic_gnss(self):
        self.assertEqual(
            classify_hazard("GNSS INTERFERENCE OBSERVED"),
            "electronic"
        )

    def test_military_naval_exercise(self):
        self.assertEqual(
            classify_hazard("NAVAL EXERCISE WILL BE CONDUCTED"),
            "military"
        )

    def test_drifting_hatch_cover(self):
        self.assertEqual(
            classify_hazard("HATCH COVER ADRIFT"),
            "drifting"
        )

    def test_subsea_pipeline(self):
        self.assertEqual(
            classify_hazard("PIPELINE LAYING OPERATIONS"),
            "subsea"
        )

if __name__ == "__main__":
    unittest.main()
