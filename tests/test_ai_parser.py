#!/usr/bin/env python3
"""tests/test_ai_parser.py — Unit Tests for AI & Deterministic Parser"""
import sys
import os
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.ai_parser import (
    parse_dms_to_decimal,
    parse_coordinate_pair,
    fallback_parse_warning,
    process_warning_with_ai,
    TriageRecord,
    CoordinateProvenance,
)


class TestAiParser(unittest.TestCase):
    def test_parse_dms_to_decimal_north_east(self):
        lat = parse_dms_to_decimal("52-45.1N")
        self.assertIsNotNone(lat)
        self.assertAlmostEqual(lat, 52.751667, places=5)

        lon = parse_dms_to_decimal("002-12.4E")
        self.assertIsNotNone(lon)
        self.assertAlmostEqual(lon, 2.206667, places=5)

    def test_parse_dms_to_decimal_south_west_and_formatting(self):
        # South should be negative
        lat_s = parse_dms_to_decimal("15-30.0S")
        self.assertIsNotNone(lat_s)
        self.assertAlmostEqual(lat_s, -15.5, places=5)

        # West should be negative
        lon_w = parse_dms_to_decimal("045°20.5'W")
        self.assertIsNotNone(lon_w)
        self.assertAlmostEqual(lon_w, -45.341667, places=5)

    def test_parse_dms_to_decimal_invalid(self):
        self.assertIsNone(parse_dms_to_decimal(None))
        self.assertIsNone(parse_dms_to_decimal(""))
        self.assertIsNone(parse_dms_to_decimal("INVALID_TEXT"))
        # Invalid minutes >= 60
        self.assertIsNone(parse_dms_to_decimal("52-75.0N"))

    def test_parse_coordinate_pair(self):
        pair = parse_coordinate_pair("52-45.1N 002-12.4E")
        self.assertIsNotNone(pair)
        lat, lon = pair
        self.assertAlmostEqual(lat, 52.751667, places=5)
        self.assertAlmostEqual(lon, 2.206667, places=5)

        # Incomplete pair
        self.assertIsNone(parse_coordinate_pair("52-45.1N"))
        self.assertIsNone(parse_coordinate_pair(None))

    def test_fallback_parse_warning_danger(self):
        text = "EXPLOSION HAZARD IN VICINITY 54-10.0N 010-20.0E. KEEP CLEAR."
        result = fallback_parse_warning(text)
        self.assertEqual(result["triage_tier"], 1)
        self.assertEqual(len(result["coordinates"]), 1)
        self.assertAlmostEqual(result["coordinates"][0]["repaired_lat"], 54.166667, places=4)
        self.assertAlmostEqual(result["coordinates"][0]["repaired_lon"], 10.333333, places=4)

    def test_fallback_parse_warning_default_hazard(self):
        text = "DRIFTING TIMBER REPORTED IN VICINITY 52-45.1N 002-12.4E."
        result = fallback_parse_warning(text)
        self.assertEqual(result["triage_tier"], 2)
        self.assertEqual(result["category"], "Drifting Hazard")

    def test_fallback_parse_warning_advisory(self):
        text = "GENERAL ADVISORY FOR NAVIGATORS IN AREA 20-00.0N 060-00.0E."
        result = fallback_parse_warning(text)
        self.assertEqual(result["triage_tier"], 3)

    def test_fallback_parse_no_coordinates_raises(self):
        with self.assertRaises(ValueError):
            fallback_parse_warning("NO COORDINATES IN THIS BULLETIN.")

    def test_process_warning_with_ai_fallback_execution(self):
        sample = """
        NAVAREA I 124/26
        ENGLAND EAST COAST.
        DRIFTING SHIPPING CONTAINER REPORTED IN VICINITY 52-45.1N 002-12.4E AT 181400Z OCT.
        VESSELS KEEP SHARP LOOKOUT.
        """
        result = process_warning_with_ai(sample)
        self.assertIsNotNone(result)
        self.assertEqual(result["triage_tier"], 2)
        self.assertEqual(result["category"], "Drifting Hazard")
        self.assertEqual(len(result["coordinates"]), 1)
        self.assertAlmostEqual(result["coordinates"][0]["repaired_lat"], 52.751667, places=5)
        self.assertAlmostEqual(result["coordinates"][0]["repaired_lon"], 2.206667, places=5)


if __name__ == "__main__":
    unittest.main()
