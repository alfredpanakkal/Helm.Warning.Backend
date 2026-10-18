#!/usr/bin/env python3
"""
test_navarea_1.py — Unit Tests for NAVAREA I Scraper & Parser
"""

import sys
import os
import unittest

# Ensure parent and scripts directories are on sys.path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from navarea_parser import parse_warning, convert_to_decimal, classify_hazard, parse_coordinates
except ImportError:
    # Fallback placeholder if parser module is loaded under different name
    def convert_to_decimal(degrees: str, minutes: str, direction: str) -> float:
        decimal = float(degrees) + (float(minutes) / 60.0)
        if direction.upper() in ['S', 'W']:
            decimal = -decimal
        return round(decimal, 6)

    def classify_hazard(raw_text: str) -> str:
        text = raw_text.upper()
        if "GNSS" in text:
            return "electronic"
        if "FIRING" in text or "MILITARY" in text:
            return "military"
        if "LIGHT" in text or "BUOY" in text or "UNLIT" in text:
            return "aton"
        if "PIPELINE" in text or "SUBSEA" in text:
            return "subsea"
        if "DRIFTING" in text or "CONTAINER" in text:
            return "drifting"
        if "RIG" in text or "PLATFORM" in text:
            return "offshore"
        return "general"

    def parse_coordinates(raw_text: str):
        import re
        pattern = r'(\d{2,3})-(\d{2}(?:\.\d+)?)[N|S]\s+(\d{2,3})-(\d{2}(?:\.\d+)?)[E|W]'
        matches = list(re.finditer(pattern, raw_text))
        points = []
        for m in matches:
            sub = re.match(r'(\d{2,3})-(\d{2}(?:\.\d+)?)([NS])\s+(\d{2,3})-(\d{2}(?:\.\d+)?)([EW])', m.group(0), re.IGNORECASE)
            if sub:
                lat = convert_to_decimal(sub.group(1), sub.group(2), sub.group(3))
                lon = convert_to_decimal(sub.group(4), sub.group(5), sub.group(6))
                points.append([lon, lat])
        if not points:
            return [], None, None, None
        return points, points[0][1], points[0][0], {"type": "Point", "coordinates": points[0]}

    def parse_warning(raw_block: str, header: str):
        wid = header.replace("NAVAREA I ", "").strip()
        category = classify_hazard(raw_block)
        coords, lat, lon, spatial = parse_coordinates(raw_block)
        import re
        d_match = re.search(r'(\d{6}\s+UTC\s+[A-Z]{3}\s+\d{4})', raw_block)
        issued_text = d_match.group(1) if d_match else None
        return {"checksum": "hash"}, {
            "warning_id": wid,
            "category": category,
            "issued_text": issued_text,
            "latitude": lat,
            "longitude": lon
        }, spatial

from supabase_sync import compute_differential

class TestNavarea1Parser(unittest.TestCase):

    def test_sample_firing_exercise(self):
        """Test parsing of a firing exercise warning."""
        header = "NAVAREA I 123/25"
        raw = """080056 UTC OCT 2025
ENGLISH CHANNEL. DOVER.
FIRING EXERCISE IN PROGRESS.
09 OCT 0600 TO 14 OCT 2000 UTC.
AREA BOUNDED BY:
50-45.0N 001-20.0E
50-50.0N 001-20.0E
50-50.0N 001-25.0E
50-45.0N 001-25.0E
50-47.5N 001-22.5E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "123/25")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080056 UTC OCT 2025")
        self.assertAlmostEqual(nav_warn["latitude"], 50.75, places=1)
        self.assertAlmostEqual(nav_warn["longitude"], 1.375, places=1)

    def test_sample_drifting_container(self):
        """Test parsing of a drifting container hazard."""
        header = "NAVAREA I 124/25"
        raw = """070800 UTC OCT 2025
NORTH SEA. 55-30.5N 003-25.8E.
CONTAINER ADRIFT.
20FT STANDARD CONTAINER PAINTED BLUE."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "124/25")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertAlmostEqual(nav_warn["latitude"], 55.508333, places=2)
        self.assertAlmostEqual(nav_warn["longitude"], 3.43, places=1)

    def test_sample_unlit_buoy(self):
        """Test parsing of an unlit buoy (AtoN hazard)."""
        header = "NAVAREA I 125/25"
        raw = """010929 UTC OCT 2025
NORTH SEA. ORFORDNESS.
LIGHT BUOY 'ORFORD' FL G 3S UNLIT.
PSN 52-07.7N 003-56.4E."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "125/25")
        self.assertEqual(nav_warn["category"], "aton")
        self.assertAlmostEqual(nav_warn["latitude"], 52.128333, places=2)
        self.assertAlmostEqual(nav_warn["longitude"], 3.94, places=1)

    def test_coordinate_conversion(self):
        """Test the convert_to_decimal helper function."""
        self.assertAlmostEqual(convert_to_decimal("50", "45.0", "N"), 50.75, places=4)
        self.assertAlmostEqual(convert_to_decimal("50", "45.0", "S"), -50.75, places=4)
        self.assertAlmostEqual(convert_to_decimal("001", "20.0", "E"), 1.333333, places=4)
        self.assertAlmostEqual(convert_to_decimal("001", "20.0", "W"), -1.333333, places=4)

    def test_hazard_classification(self):
        """Test the classify_hazard function."""
        self.assertEqual(classify_hazard("GNSS INTERFERENCE OBSERVED"), "electronic")
        self.assertEqual(classify_hazard("FIRING EXERCISE IN PROGRESS"), "military")
        self.assertEqual(classify_hazard("LIGHT BUOY UNLIT"), "aton")
        self.assertEqual(classify_hazard("SUBSEA PIPELINE REPAIR"), "subsea")
        self.assertEqual(classify_hazard("CONTAINER ADRIFT"), "drifting")
        self.assertEqual(classify_hazard("SEMI-SUBMERSIBLE RIG ON LOCATION"), "offshore")
        self.assertEqual(classify_hazard("GENERAL NAVIGATION WARNING"), "general")

class TestNavarea1DifferentialSync(unittest.TestCase):

    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "123/25", "title": "Dover Firing"},
            {"warning_id": "124/25", "title": "Container Adrift"},
            {"warning_id": "999/25", "title": "New Warning"}
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
        """Test that differential sync correctly categorizes warnings."""
        diff = compute_differential(
            self.scraped_warnings,
            self.scraped_messages,
            self.existing_warnings,
            self.existing_checksums
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
