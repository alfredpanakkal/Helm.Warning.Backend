"""Inline sub-area marker rules: '(A) ... (B) ...' and 'AREA 1 ... AREA 2 ...'.

NAVAREA VIII 1139/26 (NHO India, live Oct 2026): four '(A)'..'(D)'
pipeline work areas previously merged into ONE crooked geometry (the
16-point ring self-intersects, so the legacy path degraded to a single
open LineString). The marker rules must split them into four separate
polygons. Fail-closed gates: a marker that does not directly introduce
a coordinate never splits; a single or non-increasing marker family is
prose and never splits.
"""
import unittest
from datetime import datetime, timezone

from shared.navarea_universal_text import subarea_marks
from shared.utils import parse_coordinates_detailed
from scripts.navarea_8_parser import _segment_clauses as seg_viii
from scripts.navarea_8_parser import parse_warning as parse_viii
from scripts.navarea_universal_parser import _segment_clauses as seg_universal

VIII_1139_BODY = (
    "INDIA WEST COAST - OFF MUMBAI TO DAMAN (.) CHARTS IN 21 292 INT 7021 (.) "
    "POSH NATUNA, POSH PANGLIMA AND POSH ARCTURUS WILL CARRY OUT PIPELINE "
    "REPLACEMENT WORK FROM 30 OCT 26 TO 14 JAN 27 IN AREAS BOUNDED BY "
    "(A) 20-12.94N 072-25.7E, 20-12.83N 072-31.33E, 20-07.98N 072-31.22E, "
    "20-08.09N 072-25.59E (B) 19-41.07N 071-06.86E, 19-40.69N 071-36.43E, "
    "19-12.14N 071-35.97E, 19-12.52N 071-06.49E (C) 19-24.28N 071-55.82E, "
    "19-23.94N 072-16.01E, 19-08.52N 072-15.7E, 19-08.86N 071-55.54E "
    "(D) 20-20.75N 071-41.13E, 20-20.33N 072-06.74E, 20-04.5N 072-06.42E, "
    "20-04.92N 071-40.86E 2. CANCEL THIS MSG 141830 UTC JAN 27"
)

AREA_NUMBER_BODY = (
    "OFFSHORE WORK IN AREAS BOUNDED BY (.) "
    "AREA 1 20-10.0N 072-20.0E, 20-10.0N 072-25.0E, "
    "20-05.0N 072-25.0E, 20-05.0N 072-20.0E "
    "AREA 2 19-40.0N 071-10.0E, 19-40.0N 071-15.0E, "
    "19-35.0N 071-15.0E, 19-35.0N 071-10.0E"
)


class TestSubareaMarks(unittest.TestCase):
    def test_viii_1139_letters(self):
        marks = subarea_marks(VIII_1139_BODY)
        self.assertEqual([label for _start, label in marks],
                         ["A", "B", "C", "D"])

    def test_area_number_labels(self):
        marks = subarea_marks(AREA_NUMBER_BODY)
        self.assertEqual([label for _start, label in marks], ["1", "2"])

    def test_marker_without_coordinates_never_splits(self):
        self.assertEqual(subarea_marks("SEE NOTE (A) ABOVE"), [])

    def test_single_marker_family_is_prose(self):
        body = "(A) 20-10.0N 072-20.0E (B) NO COORDINATES FOLLOW"
        self.assertEqual(subarea_marks(body), [])

    def test_non_increasing_family_is_prose(self):
        body = ("AREA 2 20-10.0N 072-20.0E, 20-10.0N 072-21.0E "
                "AREA 1 19-40.0N 071-10.0E, 19-40.0N 071-11.0E")
        self.assertEqual(subarea_marks(body), [])

    def test_area_bounded_by_wording_never_matches(self):
        body = ("IN AREA BOUNDED BY 20-10.0N 072-20.0E, 20-10.0N 072-21.0E, "
                "20-09.0N 072-21.0E, 20-09.0N 072-20.0E")
        self.assertEqual(subarea_marks(body), [])

    def test_area_radius_wording_never_splits(self):
        self.assertEqual(
            subarea_marks("WORK WITHIN AREA 1.5 NM RADIUS OF BUOY"), [])


class TestVIII1139Split(unittest.TestCase):
    def test_clauses_split_into_four_areas(self):
        clauses = seg_viii(VIII_1139_BODY)
        self.assertEqual([c["label"] for c in clauses],
                         ["Area", "A", "B", "C", "D", "2"])
        # Inline sub-area clauses carry the governing phrase as context.
        for clause in clauses[1:5]:
            self.assertIn("IN AREAS BOUNDED BY", clause["context"])

    def test_four_separate_polygons(self):
        block = {
            "warning_id": "NAVAREA VIII 1139/26",
            "number": "1139",
            "year": "26",
            "raw_text": "NAVAREA VIII -1139/26 " + VIII_1139_BODY,
        }
        _raw_message, nav_warning = parse_viii(
            block, now_utc=datetime(2026, 11, 8, tzinfo=timezone.utc))
        spatial = nav_warning["spatial"]
        self.assertIsNotNone(spatial)
        features = spatial["features"]
        self.assertEqual(len(features), 4)
        for feature in features:
            self.assertEqual(feature["geometry"]["type"], "Polygon")
            self.assertEqual(len(feature["geometry"]["coordinates"][0]), 5)
        self.assertEqual(nav_warning["geometry_sub_areas"],
                         ["A", "B", "C", "D"])
        # Area A first corner: 20-12.94N 072-25.7E.
        first = features[0]["geometry"]["coordinates"][0][0]
        self.assertAlmostEqual(first[0], 72.428333, places=5)
        self.assertAlmostEqual(first[1], 20.215667, places=5)


class TestUniversalAreaLabels(unittest.TestCase):
    def test_area_number_clauses_classify_as_bounded_areas(self):
        clauses = seg_universal(AREA_NUMBER_BODY)
        self.assertEqual([c["label"] for c in clauses], ["Area", "1", "2"])
        for clause in clauses[1:]:
            _coords, _lat, _lon, spatial, report = parse_coordinates_detailed(
                clause["text"], clause.get("context"))
            self.assertEqual(spatial["type"], "Polygon")
            self.assertEqual(report["basis"], "keyword:area_bounded")


if __name__ == "__main__":
    unittest.main()
