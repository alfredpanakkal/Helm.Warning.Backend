#!/usr/bin/env python3
"""
test_navarea_1.py - Unit Tests for NAVAREA I Scraper & Parser
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from navareas.navarea_1.parser import parse_warning
from shared.coordinates import convert_to_decimal, parse_coordinates
from shared.classification import classify_hazard

class TestNavarea1Parser(unittest.TestCase):

    def test_parse_basic_warning(self):
        header = "NAVAREA I 123/26"
        raw = """010000 UTC JAN 2026
NORTH SEA. DOVER STRAIT.
DRIFTING CONTAINER REPORTED.
PSN: 51-00.0N 001-30.0E
ALL SHIPS ADVISED TO NAVIGATE WITH CAUTION."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)

        self.assertEqual(nav_warn["warning_id"], "123/26")
        self.assertEqual(nav_warn["source_id"], "ukho-navarea-1")
        self.assertEqual(nav_warn["navarea"], "I")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertEqual(nav_warn["status"], "active")
        self.assertIsNotNone(spatial)
        self.assertEqual(spatial["type"], "Point")

    def test_parse_with_date_in_title(self):
        header = "NAVAREA I 456/26"
        raw = """051200 UTC JUN 2026
ENGLISH CHANNEL.
SUBMARINE CABLE REPAIR OPERATIONS.
PSN: 50-30.0N 000-45.0W TO 50-35.0N 000-40.0W
MARINERS REQUESTED TO KEEP CLEAR."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)

        self.assertEqual(nav_warn["warning_id"], "456/26")
        self.assertEqual(nav_warn["issued_text"], "051200 UTC JUN 2026")
        self.assertEqual(nav_warn["category"], "subsea")
        self.assertEqual(spatial["type"], "LineString")

    def test_parse_military_warning(self):
        header = "NAVAREA I 789/26"
        raw = """100600 UTC OCT 2026
NORTH ATLANTIC.
NAVAL EXERCISE IN PROGRESS.
GUNNERY AND MISSILE FIRING.
AREA: 55-00N 010-00W TO 56-00N 009-00W
DANGER AREA ACTIVE."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)

        self.assertEqual(nav_warn["warning_id"], "789/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertIn("NAVAL EXERCISE", nav_warn["raw_text"])

    def test_parse_aton_warning(self):
        header = "NAVAREA I 012/26"
        raw = """150800 UTC AUG 2026
IRISH SEA.
LIGHT BUOY 'ALPHA' EXTINGUISHED.
PSN: 53-20.5N 005-30.2W
MARINERS ADVISED."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)

        self.assertEqual(nav_warn["warning_id"], "012/26")
        self.assertEqual(nav_warn["category"], "aton")
        self.assertAlmostEqual(nav_warn["latitude"], 53.341667, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], -5.503333, places=4)

class TestNavarea1CoordinateParsing(unittest.TestCase):

    def test_parse_single_point(self):
        raw = "PSN: 51-00.0N 001-30.0E"
        coords, lat, lon, spatial = parse_coordinates(raw)

        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, 51.0, places=4)
        self.assertAlmostEqual(lon, 1.5, places=4)
        self.assertEqual(spatial["type"], "Point")

    def test_parse_line_string(self):
        raw = "PSN: 50-30.0N 000-45.0W TO 50-35.0N 000-40.0W"
        coords, lat, lon, spatial = parse_coordinates(raw)

        self.assertEqual(len(coords), 2)
        self.assertEqual(spatial["type"], "LineString")

    def test_convert_to_decimal(self):
        self.assertAlmostEqual(
            convert_to_decimal("51", "00.0", "N"),
            51.0,
            places=6
        )
        self.assertAlmostEqual(
            convert_to_decimal("001", "30.0", "E"),
            1.5,
            places=6
        )
        self.assertAlmostEqual(
            convert_to_decimal("50", "30.0", "S"),
            -50.5,
            places=6
        )

class TestNavarea1HazardClassification(unittest.TestCase):

    def test_electronic_classification(self):
        self.assertEqual(
            classify_hazard("GNSS signal interference reported"),
            "electronic"
        )

    def test_military_classification(self):
        self.assertEqual(
            classify_hazard("NAVAL EXERCISE with live firing"),
            "military"
        )
        self.assertEqual(
            classify_hazard("WEAPON testing in area"),
            "military"
        )

    def test_aton_classification(self):
        self.assertEqual(
            classify_hazard("BUOY number 5 missing"),
            "aton"
        )
        self.assertEqual(
            classify_hazard("LIGHT not functioning"),
            "aton"
        )

    def test_subsea_classification(self):
        self.assertEqual(
            classify_hazard("CABLE repair operations"),
            "subsea"
        )
        self.assertEqual(
            classify_hazard("DREDGING in progress"),
            "subsea"
        )

    def test_drifting_classification(self):
        self.assertEqual(
            classify_hazard("DRIFTING CONTAINER"),
            "drifting"
        )
        self.assertEqual(
            classify_hazard("DERELICT vessel sighted"),
            "drifting"
        )

if __name__ == "__main__":
    unittest.main()
