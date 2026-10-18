#!/usr/bin/env python3
"""
test_baltic.py — Unit Tests for NAVAREA Baltic Scraper & Deterministic Parser
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from baltic_parser import parse_warning, convert_to_decimal, classify_hazard, parse_coordinates
from supabase_sync import compute_differential

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

    def test_sample_2_kattegat_stora_polsan_point(self):
        header = "SWEDISH NAV WARN 167/26 [Kattegat]"
        raw = """080035 UTC OCT
KATTEGAT. MARSTRAND. STORA PÖLSAN.
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS.
09 OCT 0600 LT - 14 OCT 2000 LT.
1 M CLEARANCE FROM THE AREA IS REQUESTED.
PSN: 57-47.0N 011-27.9E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 167/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080035 UTC OCT 2026")
        self.assertEqual(spatial["type"], "Point")
        self.assertAlmostEqual(nav_warn["latitude"], 57.783333, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 11.465000, places=4)

    def test_sample_3_falkenberg_dredging_buoy(self):
        header = "SWEDISH NAV WARN 166/26 [Kattegat]"
        raw = """070800 UTC OCT
KATTEGAT. FALKENBERG HARBOUR ENTRANCE.
DREDGING IN OPERATION. SPAR BUOYS MIGHT HAVE BEEN MOVED.
PSN 56-53.0N 012-28.0E
GREATE CAUTION ADVISED"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 166/26")
        self.assertIn(nav_warn["category"], ["aton", "subsea"])
        self.assertAlmostEqual(nav_warn["latitude"], 56.883333, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 12.466667, places=4)

    def test_sample_4_donso_svartskar_unlit_two_decimals(self):
        header = "SWEDISH NAV WARN 156/26 [Kattegat]"
        raw = """300051 UTC SEP
KATTEGAT. STYRSÖ. DONSÖ
LIGHT 'DONSÖ SVARTSKÅR' IS UNLIT.
PSN 57-35.15N 011-43.33E."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 156/26")
        self.assertEqual(nav_warn["category"], "aton")
        self.assertEqual(nav_warn["issued_text"], "300051 UTC SEP 2026")
        self.assertAlmostEqual(nav_warn["latitude"], 57.585833, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 11.722167, places=4)

    def test_sample_5_lake_vanern_leading_lights(self):
        header = "SWEDISH NAV WARN 159/26 [Lake Väern and Trollhätte Canal]"
        raw = """010929 UTC OCT
LAKE VÄNERN
THE LEADING LIGHTS ON DALBOLANDET ARE EXTINGUISHED FOR MAINTENANCE.
APPROX. PSN 58-23.6N 012-18.3E."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 159/26")
        self.assertEqual(nav_warn["category"], "aton")
        self.assertEqual(nav_warn["issued_text"], "010929 UTC OCT 2026")
        self.assertAlmostEqual(nav_warn["latitude"], 58.393333, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 12.305000, places=4)

    def test_sample_6_baltic_wide_gnss_interference(self):
        header = "BALTIC SEA NAV WARN 026/25 [Western Baltic, Central Baltic]"
        raw = """021100 UTC JUL
SOUTHERN, SOUTHEASTERN, CENTRAL AND NORTHERN BALTIC, GULF OF FINLAND, GULF OF RIGA AND SEA OF AALAND.
GNSS, AIS, RADAR AND DGPS INTERFERENCE OBSERVED IN AREA.
MARINERS ADVISED TO EXERCISE CAUTION
AND BE PREPARED FOR NAVIGATION IMPACTS."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "BALTIC 026/25")
        self.assertEqual(nav_warn["category"], "electronic")
        self.assertEqual(nav_warn["issued_text"], "021100 UTC JUL 2025")
        self.assertIsNone(nav_warn["latitude"])
        self.assertIsNone(nav_warn["longitude"])
        self.assertIsNone(spatial)

    def test_sample_7_central_baltic_naval_exercises_bounding_box(self):
        header = "BALTIC SEA NAV WARN 029/26 [Central Baltic]"
        raw = """280548 UTC SEP
NAVAL EXERCISES (WITHOUT FIRINGS) 022100 TO 102100 OCT UTC
IN AREA DANGEROUS TO NAVIGATION BOUNDED BY
57-37.5N 020-05.6E 57-27.1N 020-35.5E
56-54.0N 019-56.1E 57-04.9N 019-25.9E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "BALTIC 029/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "280548 UTC SEP 2026")
        self.assertIsNotNone(spatial)
        self.assertEqual(spatial["type"], "Polygon")

    def test_sample_8_lake_malaren_pipeline(self):
        header = "SWEDISH NAV WARN 160/26 [Lake Mälaren and Södertälje Canal]"
        raw = """021834 UTC OCT
LAKE MÄLAREN AND SÖDERTÄLJE CANAL. KÄRSÖN.
UNMARKED PIPELINE EXIST CLOSE UNDER THE WATER SURFACE
IN VICINITY OF PSN 59-19.6N 017-54.4E
AT 021834 UTC OCT.
CAUTION ADVISED."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 160/26")
        self.assertEqual(nav_warn["category"], "subsea")
        self.assertAlmostEqual(nav_warn["latitude"], 59.326667, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 17.906667, places=4)

    def test_sample_9_bay_of_bothnia_anchor_lost(self):
        header = "SWEDISH NAV WARN 165/26 [Bay of Bothnia]"
        raw = """070521 UTC OCT
BAY OF BOTHNIA. LULEÅ. LARSGRUNDET. SÖRBRÄNDÖFJÄRDEN.
ANCHOR AND 280 MERTERS CHAIN LOST.
PSN 65-27.1N 022-30.0E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 165/26")
        self.assertEqual(nav_warn["category"], "subsea")
        self.assertAlmostEqual(nav_warn["latitude"], 65.451667, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 22.500000, places=4)

    def test_sample_10_bay_of_bothnia_kopparudden_unlit(self):
        header = "SWEDISH NAV WARN 155/26 [Bay of Bothnia]"
        raw = """280753 UTC SEP
BAY OF BOTHNIA. SKELLEFTEHAMN. ARMBÅGEN - RÖNNSKÅR
LIGHT 'KOPPARUDDEN' FL WRG 3S 9M. UNLIT.
PSN 64-39.71N 021-16.82E."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 155/26")
        self.assertEqual(nav_warn["category"], "aton")
        self.assertAlmostEqual(nav_warn["latitude"], 64.661833, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 21.280333, places=4)

class TestDifferentialSync(unittest.TestCase):

    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "SWEDISH 168/26", "title": "Lysekil"},
            {"warning_id": "SWEDISH 167/26", "title": "Stora Polsan"},
            {"warning_id": "SWEDISH 999/26", "title": "Brand New Warning"}
        ]
        self.scraped_messages = [
            {"warning_id": "SWEDISH 168/26", "checksum_sha256": "hash_168_unchanged"},
            {"warning_id": "SWEDISH 167/26", "checksum_sha256": "hash_167_new_revision"},
            {"warning_id": "SWEDISH 999/26", "checksum_sha256": "hash_999_brand_new"}
        ]
        self.existing_warnings = {
            "SWEDISH 168/26": {"warning_id": "SWEDISH 168/26", "status": "active"},
            "SWEDISH 167/26": {"warning_id": "SWEDISH 167/26", "status": "active"},
            "SWEDISH 100/26": {"warning_id": "SWEDISH 100/26", "status": "active"}
        }
        self.existing_checksums = {
            ("SWEDISH 168/26", "hash_168_unchanged"),
            ("SWEDISH 167/26", "hash_167_old_version"),
            ("SWEDISH 100/26", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings,
            self.scraped_messages,
            self.existing_warnings,
            self.existing_checksums
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
