#!/usr/bin/env python3
"""
test_baltic.py - Unit Tests for NAVAREA Baltic Scraper & Deterministic Parser
Verifies all sample bulletins for the Baltic region.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from navareas.baltic.parser import parse_warning
from shared.coordinates import convert_to_decimal, parse_coordinates
from shared.classification import classify_hazard

class TestBalticParser(unittest.TestCase):

    def test_sample_1_skagerrak_detonations_polygon(self):
        header = "SWEDISH NAV WARN 168/26 [Skagerrak]"
        raw = """080056 UTC OCT
SKAGERRAK. LYSEKIL. BONDEN
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS
09 OCT 0600 LT - 14 OCT 2000 LT
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

    def test_sample_4_donso_svartskar_unlit(self):
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
        header = "SWEDISH NAV WARN 159/26 [Lake Väner and Trollhätte Canal]"
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

    def test_sample_7_gotland_military_exercise(self):
        header = "SWEDISH NAV WARN 123/25 [Gotland]"
        raw = """051200 UTC JUN
GOTLAND. SOUTH OF FARO.
MILITARY EXERCISE WILL TAKE PLACE.
06 JUN 0000 LT - 10 JUN 2359 LT.
PSN: 57-10.0N 018-30.0E
57-20.0N 018-40.0E
57-20.0N 018-30.0E
57-10.0N 018-30.0E
KEEP CLEAR OF THE AREA."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 123/25")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(spatial["type"], "Polygon")

    def test_sample_8_subsea_pipeline(self):
        header = "BALTIC SEA NAV WARN 012/25 [Central Baltic]"
        raw = """150800 UTC MAY
CENTRAL BALTIC.
PIPELINE LAYING OPERATIONS IN PROGRESS.
PSN: 58-00.0N 016-00.0E TO 58-10.0N 016-20.0E
MARINERS ADVISED TO KEEP CLEAR."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "BALTIC 012/25")
        self.assertEqual(nav_warn["category"], "subsea")
        self.assertEqual(spatial["type"], "LineString")

    def test_sample_9_drifting_container(self):
        header = "SWEDISH NAV WARN 045/25 [Skagerrak]"
        raw = """100600 UTC APR
SKAGERRAK.
CONTAINER ADRIFT.
APPROX PSN: 57-50.0N 011-30.0E
ALL SHIPS REQUESTED TO REPORT SIGHTINGS."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 045/25")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertEqual(spatial["type"], "Point")

    def test_sample_10_offshore_rig(self):
        header = "SWEDISH NAV WARN 001/25 [Western Baltic]"
        raw = """010000 UTC JAN
WESTERN BALTIC.
DRILLING RIG 'OCEAN PRIDE' ON LOCATION.
PSN: 56-00.0N 014-00.0E
SAFETY ZONE OF 500M ESTABLISHED AROUND THE RIG."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 001/25")
        self.assertEqual(nav_warn["category"], "offshore")
        self.assertEqual(spatial["type"], "Point")

class TestCoordinateParsing(unittest.TestCase):

    def test_parse_simple_coordinates(self):
        raw = "PSN: 58-10.2N 011-13.3E"
        coords, lat, lon, spatial = parse_coordinates(raw)
        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, 58.170000, places=4)
        self.assertAlmostEqual(lon, 11.221667, places=4)
        self.assertEqual(spatial["type"], "Point")

    def test_parse_multiple_coordinates(self):
        raw = """PSN:
58-10.2N 011-13.3E
58-13.3N 011-13.3E
58-13.3N 011-17.4E"""
        coords, lat, lon, spatial = parse_coordinates(raw)
        self.assertEqual(len(coords), 3)
        self.assertEqual(spatial["type"], "LineString")

    def test_parse_polygon_coordinates(self):
        raw = """PSN:
58-10.2N 011-13.3E
58-13.3N 011-13.3E
58-13.3N 011-17.4E
58-10.2N 011-13.3E"""
        coords, lat, lon, spatial = parse_coordinates(raw)
        self.assertEqual(len(coords), 4)
        self.assertEqual(spatial["type"], "Polygon")

    def test_convert_to_decimal(self):
        self.assertAlmostEqual(convert_to_decimal("58", "10.2", "N"), 58.170000, places=6)
        self.assertAlmostEqual(convert_to_decimal("58", "10.2", "S"), -58.170000, places=6)
        self.assertAlmostEqual(convert_to_decimal("011", "13.3", "E"), 11.221667, places=6)
        self.assertAlmostEqual(convert_to_decimal("011", "13.3", "W"), -11.221667, places=6)

class TestHazardClassification(unittest.TestCase):

    def test_electronic_gnss(self):
        self.assertEqual(classify_hazard("GNSS interference observed"), "electronic")
        self.assertEqual(classify_hazard("DGPS INTERFERENCE"), "electronic")
        self.assertEqual(classify_hazard("AIS interference"), "electronic")

    def test_military_detonations(self):
        self.assertEqual(classify_hazard("DETONATIONS will be performed"), "military")
        self.assertEqual(classify_hazard("FIRING exercise"), "military")
        self.assertEqual(classify_hazard("GUNNERY practice"), "military")
        self.assertEqual(classify_hazard("MISSILE test"), "military")

    def test_aton_lights(self):
        self.assertEqual(classify_hazard("LIGHT is unlit"), "aton")
        self.assertEqual(classify_hazard("BUOY missing"), "aton")
        self.assertEqual(classify_hazard("RACON not working"), "aton")
        self.assertEqual(classify_hazard("BEACON extinguished"), "aton")

    def test_subsea_cable(self):
        self.assertEqual(classify_hazard("CABLE laying operations"), "subsea")
        self.assertEqual(classify_hazard("PIPELINE inspection"), "subsea")
        self.assertEqual(classify_hazard("DREDGING in progress"), "subsea")

    def test_drifting_mine(self):
        self.assertEqual(classify_hazard("MINE drifting"), "drifting")
        self.assertEqual(classify_hazard("CONTAINER adrift"), "drifting")
        self.assertEqual(classify_hazard("DERELICT vessel"), "drifting")

    def test_offshore_rig(self):
        self.assertEqual(classify_hazard("RIG on location"), "offshore")
        self.assertEqual(classify_hazard("PLATFORM installation"), "offshore")

    def test_general_fallback(self):
        self.assertEqual(classify_hazard("General navigation warning"), "general")
        self.assertEqual(classify_hazard("Unknown hazard"), "general")

if __name__ == "__main__":
    unittest.main()
