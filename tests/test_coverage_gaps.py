#!/usr/bin/env python3
"""
tests/test_coverage_gaps.py — Phase 2 coverage fixes: pair syntaxes and
area wordings the live corpus uses but the shared patterns previously
refused. Failures of these shapes are visible (no geometry plotted),
but the positions are real and must parse.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils import parse_coordinates, parse_coordinates_detailed


class TestPairSyntaxes(unittest.TestCase):

    def test_decimal_comma_minutes_iii_0086(self):
        # NAVAREA III 0086/26: European decimal comma in the minutes
        _, lat, lon, spatial = parse_coordinates("44-05,12N 013-45,27E")
        self.assertEqual(spatial["type"], "Point")
        self.assertAlmostEqual(lat, 44 + 5.12 / 60, places=5)
        self.assertAlmostEqual(lon, 13 + 45.27 / 60, places=5)

    def test_space_separated_dms_ix_118(self):
        # NAVAREA IX 118/26: degrees/minutes/seconds separated by spaces
        _, lat, lon, spatial = parse_coordinates("25 02 37.67N 054 59 18.27E")
        self.assertEqual(spatial["type"], "Point")
        self.assertAlmostEqual(lat, 25 + 2 / 60 + 37.67 / 3600, places=5)
        self.assertAlmostEqual(lon, 54 + 59 / 60 + 18.27 / 3600, places=5)

    def test_mixed_separators_ix_489(self):
        # NAVAREA IX 489/22: space-separated lat, hyphen-separated lon
        _, lat, lon, spatial = parse_coordinates("23 59.10N, 038-01.70E")
        self.assertEqual(spatial["type"], "Point")
        self.assertAlmostEqual(lat, 23 + 59.10 / 60, places=5)
        self.assertAlmostEqual(lon, 38 + 1.70 / 60, places=5)

    def test_dash_between_lat_and_lon_iii_0122(self):
        # NAVAREA III 0122/26 shape: 'N - E' separates the two values
        raw = ("DRILLING OPERATIONS IN AREA BOUNDED BY 18-00N - 071-00E, "
               "18-00N - 072-00E, 19-00N - 072-00E, 19-00N - 071-00E")
        coords, _, _, spatial = parse_coordinates(raw)
        self.assertEqual(len(coords), 4)
        self.assertEqual(spatial["type"], "Polygon")

    def test_single_digit_minutes_swedish_175(self):
        # SWEDISH 175/26 '018-4.7E': one-digit minutes (synthetic lat)
        _, lat, lon, spatial = parse_coordinates(
            "OBSTRUCTION AT 59-19.7N 018-4.7E")
        self.assertEqual(spatial["type"], "Point")
        self.assertAlmostEqual(lat, 59 + 19.7 / 60, places=5)
        self.assertAlmostEqual(lon, 18 + 4.7 / 60, places=5)


class TestAreaWordings(unittest.TestCase):

    def test_areas_bounded_by_plural_routes_to_bounded_area(self):
        # 'AREAS BOUNDED BY' / 'IN AREAS BOUND BY' preambles: the plural
        # previously missed RE_BOUNDED and fell to the legacy fallback.
        raw = ("SUBMARINE EXERCISE IN AREAS BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["basis"], "keyword:area_bounded")
        self.assertNotIn("AMBIGUOUS_FALLBACK", report["flags"])


if __name__ == '__main__':
    unittest.main()
