#!/usr/bin/env python3
"""
tests/test_geometry_classifier.py — Geometry archetype classification regression suite.

Covers the tangled-polygon bug (NAVAREA VIII 961/26, 1096/26): scattered
'vicinity' lists and survey tracks must not be rendered as auto-closed
polygons. Exercises the REAL shared parser (no second parser) and the
MultiPoint -> per-point POINT geometry-row explosion in shared/models.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils import parse_coordinates
from shared.models import build_geometry_payloads
from shared.geometry_classifier import classify_geometry_archetype, _is_sequential


V961 = """NAVAREA VIII -961/26 INDIA WEST COAST - OFF HAZIRA TO MUMBAI (.)
CHARTS IN 21 292 INT 7021 (.) VANESSA 6 WILL CARRY OUT SEABED SURVEY FROM
11 SEP TO 26 OCT 26 IN VICINITY OF 19-12.44N 071-05.99E, 19-09.75N 071-08.55E,
19-10.61N 070-57.71E, 18-35.7N 072-12.81E, 19-30.97N 071-21.32E, 19-12.18N
071-04.36E, 20-20.02N 072-21.64E, 19-35.32N 071-24.27E, 20-44.33N 071-37.99E
2. CANCEL THIS MSG 261830 UTC OCT 26"""

V1096 = """NAVAREA VIII -1096/26 INDIA WEST COAST - OFF MUMBAI TO HAZIRA (.)
CHARTS IN 21 255 292 INT 7021 (.) VANESSA 7 AND ACOMS 11 WILL CARRY OUT
MAINTENANCE OF WELL HEAD PLATFORM FROM 20 TO 31 OCT 26 IN VICINITY OF
18-38.2N 071-00.92E, 19-22.46N 071-21.54E, 18-42.58N 072-20.4E, 19-31.78N
071-18.15E, 18-36.4N 072-15.77E, 19-06.08N 070-56.43E, 19-21.09N 071-47.23E,
19-22.37N 072-00.62E, 19-23.59N 071-58.19E, 19-18.27N 071-58.58E, 18-41.51N
072-20.86E, 18-43.08N 072-19.12E, 21-03N 072-23E, 19-11.05N 072-11.21E
2. CANCEL THIS MSG 311830 UTC OCT 26"""


def _spatial(text):
    _, _, _, spatial = parse_coordinates(text)
    return spatial


class TestArchetypeClassification(unittest.TestCase):

    def test_v961_seabed_survey_vicinity_is_multipoint(self):
        spatial = _spatial(V961)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertEqual(len(spatial["coordinates"]), 9)

    def test_v1096_wellhead_maintenance_is_multipoint(self):
        spatial = _spatial(V1096)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertEqual(len(spatial["coordinates"]), 14)

    def test_bounded_area_keeps_polygon(self):
        raw = ("HYDROGRAPHIC SURVEY IN AREA BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(spatial["coordinates"][0][0], spatial["coordinates"][0][-1])

    def test_single_position_stays_point(self):
        _, lat, lon, spatial = parse_coordinates("RIG AT 19-22.46N 071-21.54E")
        self.assertEqual(spatial["type"], "Point")
        self.assertIsNotNone(lat)

    def test_two_point_tow_is_linestring(self):
        spatial = _spatial("DREDGER TOW FROM 18-30N 071-00E TO 19-00N 071-30E")
        self.assertEqual(spatial["type"], "LineString")

    def test_sequential_survey_track_is_linestring(self):
        coords = ", ".join(f"18-{30 + i * 3:02d}N 071-00E" for i in range(6))
        spatial = _spatial(f"SEABED SURVEY ALONG TRACK AT {coords}")
        self.assertEqual(spatial["type"], "LineString")

    def test_no_keywords_falls_back_to_legacy_polygon(self):
        raw = ("SUBMERGED OBJECT REPORTED AT 19-12.44N 071-05.99E, "
               "19-09.75N 071-08.55E, 19-10.61N 070-57.71E, 18-35.7N 072-12.81E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")

    def test_word_boundary_guards(self):
        # 'ORIGINAL' must not match RIG
        raw = ("THIS IS THE ORIGINAL POSITION LIST: 19-12.44N 071-05.99E, "
               "19-09.75N 071-08.55E, 19-10.61N 070-57.71E, 18-35.7N 072-12.81E")
        self.assertIsNone(classify_geometry_archetype(raw, [[71.0998, 19.2073], [71.1425, 19.1625],
                                                             [70.9618, 19.1768], [72.2135, 18.595]]))

    def test_is_sequential_scattered_vs_track(self):
        scattered = [[71.0998, 19.2073], [71.1425, 19.1625], [70.9618, 19.1768],
                     [72.2135, 18.595], [71.3553, 19.5162]]
        track = [[71.00 + i * 0.05, 18.50] for i in range(8)]
        self.assertFalse(_is_sequential(scattered))
        self.assertTrue(_is_sequential(track))


class TestMultiPointGeometryRows(unittest.TestCase):

    def test_multipoint_explodes_to_point_rows_with_buffer(self):
        record = {
            "title": "NAVAREA VIII 961/26",
            "spatial": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"zone_label": "Area"},
                    "geometry": {
                        "type": "MultiPoint",
                        "coordinates": [[71.0998, 19.2073], [71.1425, 19.1625]],
                    },
                }],
            },
        }
        geoms = build_geometry_payloads(record)
        self.assertEqual(len(geoms), 2)
        for g in geoms:
            self.assertEqual(g["feature_type"], "POINT")
            self.assertEqual(g["geojson"]["type"], "Point")
            self.assertGreaterEqual(g["buffer_nm"], 1.0)  # 1 NM safety radius

    def test_point_feature_unchanged(self):
        record = {
            "title": "T",
            "spatial": {"type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Point", "coordinates": [71.0, 19.0]}},
        }
        geoms = build_geometry_payloads(record)
        self.assertEqual(len(geoms), 1)
        self.assertEqual(geoms[0]["feature_type"], "POINT")


if __name__ == "__main__":
    unittest.main()
