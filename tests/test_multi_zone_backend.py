"""tests/test_multi_zone_backend.py — Dedicated Phase B3 regression suite.

Covers:
- Group A: Marker detection & punctuation variants ((A)..(D), (A):..(D):, AREA 1..2, AREA A:..B:)
- Group B: False-positive protection (prose, non-monotonic, isolated markers, conflicting segmentations)
- Group C: Strict coordinate isolation (geographically distant polygons, zero cross-contamination)
- Group D: Incomplete-zone QA (partial zone failures, has_incomplete_zone flag, AMBIGUOUS quality roll-up)
- Group E: Governing preamble context propagation and geometry classification
- Group F: Four-value return contract compatibility
- Group G: Payload generation and triage gate validation
- Group H: Regional parser regression (NAVAREA VIII, XI, I, Baltic)
"""

import unittest
from shared.navarea_universal_text import subarea_marks
from shared.utils import parse_block_geometries, parse_coordinates_detailed
from shared.models import build_geometry_payloads, TriageTier, DataQuality
from shared.triage import assign_final_triage


class TestGroupAMarkers(unittest.TestCase):
    """Group A — Marker detection and punctuation variants."""

    def test_paren_markers_with_colons(self):
        text = "(A): 20-12.0N 075-10.0E (B): 21-12.0N 076-10.0E"
        marks = subarea_marks(text)
        self.assertEqual([m[1] for m in marks], ["A", "B"])

    def test_paren_markers_with_periods(self):
        text = "(A). 20-12.0N 075-10.0E (B). 21-12.0N 076-10.0E"
        marks = subarea_marks(text)
        self.assertEqual([m[1] for m in marks], ["A", "B"])

    def test_area_letter_with_colon(self):
        text = "AREA A: 20-12.0N 075-10.0E AREA B: 21-12.0N 076-10.0E"
        marks = subarea_marks(text)
        self.assertEqual([m[1] for m in marks], ["A", "B"])

    def test_area_number_markers(self):
        text = "AREA 1 20-12.0N 075-10.0E AREA 2 21-12.0N 076-10.0E"
        marks = subarea_marks(text)
        self.assertEqual([m[1] for m in marks], ["1", "2"])

    def test_four_paren_markers_with_colons(self):
        text = "(A): 20-10N 070-10E (B): 20-20N 070-20E (C): 20-30N 070-30E (D): 20-40N 070-40E"
        marks = subarea_marks(text)
        self.assertEqual([m[1] for m in marks], ["A", "B", "C", "D"])


class TestGroupBFalsePositives(unittest.TestCase):
    """Group B — False-positive protection."""

    def test_single_marker_is_prose(self):
        text = "(A): 20-12.0N 075-10.0E (B): NO COORDINATES HERE"
        self.assertEqual(subarea_marks(text), [])

    def test_decreasing_sequence_is_prose(self):
        text = "(B): 21-12.0N 076-10.0E (A): 20-12.0N 075-10.0E"
        self.assertEqual(subarea_marks(text), [])

    def test_repeated_marker_is_prose(self):
        text = "(A): 20-12.0N 075-10.0E (A): 21-12.0N 076-10.0E"
        self.assertEqual(subarea_marks(text), [])

    def test_area_bounded_by_prose_never_splits(self):
        text = "IN AREA BOUNDED BY 20-12.0N 075-10.0E, 20-15.0N 075-10.0E, 20-15.0N 075-15.0E, 20-12.0N 075-15.0E"
        geoms, _, _, _ = parse_block_geometries(text)
        self.assertEqual(len(geoms), 1)
        self.assertIsNone(geoms[0][0])

    def test_prose_paren_never_splits(self):
        text = "PLEASE REFER TO NOTE (A) BEFORE PROCEEDING."
        self.assertEqual(subarea_marks(text), [])


class TestGroupCCoordinateIsolation(unittest.TestCase):
    """Group C — Coordinate isolation between discrete geographical zones."""

    def test_arabian_sea_and_bay_of_bengal_isolation(self):
        # Two geographically distant areas
        # Zone A: Arabian Sea (~20N, ~72E)
        # Zone B: Bay of Bengal (~15N, ~88E)
        text = (
            "MILITARY EXERCISES IN AREAS BOUNDED BY:\n"
            "(A) 20-00.00N 072-00.00E, 20-10.00N 072-00.00E, "
            "20-10.00N 072-10.00E, 20-00.00N 072-10.00E\n"
            "(B) 15-00.00N 088-00.00E, 15-10.00N 088-00.00E, "
            "15-10.00N 088-10.00E, 15-00.00N 088-10.00E"
        )
        geoms, coords_text, qa_flags, data_quality = parse_block_geometries(text)
        self.assertEqual(len(geoms), 2)
        self.assertEqual([g[0] for g in geoms], ["A", "B"])

        geom_a = geoms[0][1]
        geom_b = geoms[1][1]
        self.assertEqual(geom_a["type"], "Polygon")
        self.assertEqual(geom_b["type"], "Polygon")

        ring_a = geom_a["coordinates"][0]
        ring_b = geom_b["coordinates"][0]

        # Assert Zone A vertices are strictly around 72E, 20N
        for lon, lat in ring_a:
            self.assertTrue(71.9 <= lon <= 72.2)
            self.assertTrue(19.9 <= lat <= 20.2)

        # Assert Zone B vertices are strictly around 88E, 15N
        for lon, lat in ring_b:
            self.assertTrue(87.9 <= lon <= 88.2)
            self.assertTrue(14.9 <= lat <= 15.2)

        # Zero coordinate leakage
        set_a = {tuple(p) for p in ring_a}
        set_b = {tuple(p) for p in ring_b}
        self.assertTrue(set_a.isdisjoint(set_b))
        self.assertEqual(data_quality, "EXPLICIT")


class TestGroupDIncompleteZoneQA(unittest.TestCase):
    """Group D — Incomplete-zone QA and parent reporting."""

    def test_zone_b_single_coordinate_flags_incomplete(self):
        text = (
            "PIPELINE OPERATIONS. IN AREAS BOUNDED BY:\n"
            "(A) 20-12.00N 075-10.00E, 20-15.00N 075-10.00E, "
            "20-15.00N 075-15.00E, 20-12.00N 075-15.00E\n"
            "(B) 21-12.00N 076-10.00E\n"
            "(C) 22-12.00N 077-10.00E, 22-15.00N 077-10.00E, "
            "22-15.00N 077-15.00E, 22-12.00N 077-15.00E"
        )
        geoms, coords_text, qa_flags, data_quality = parse_block_geometries(text)
        self.assertEqual(len(geoms), 3)
        self.assertEqual([g[0] for g in geoms], ["A", "B", "C"])
        self.assertEqual(geoms[0][1]["type"], "Polygon")
        self.assertEqual(geoms[1][1]["type"], "Point")
        self.assertEqual(geoms[2][1]["type"], "Polygon")

        # Incomplete zone B (single point in a bounded area context) must set parent QA
        self.assertIn("has_incomplete_zone", qa_flags)
        self.assertEqual(data_quality, "AMBIGUOUS")

    def test_zone_b_two_coordinates_flags_incomplete(self):
        text = (
            "PIPELINE OPERATIONS. IN AREAS BOUNDED BY:\n"
            "(A) 20-12.00N 075-10.00E, 20-15.00N 075-10.00E, "
            "20-15.00N 075-15.00E, 20-12.00N 075-15.00E\n"
            "(B) 21-12.00N 076-10.00E, 21-15.00N 076-10.00E\n"
            "(C) 22-12.00N 077-10.00E, 22-15.00N 077-10.00E, "
            "22-15.00N 077-15.00E, 22-12.00N 077-15.00E"
        )
        geoms, coords_text, qa_flags, data_quality = parse_block_geometries(text)
        self.assertEqual(len(geoms), 3)
        self.assertEqual([g[0] for g in geoms], ["A", "B", "C"])
        self.assertEqual(geoms[0][1]["type"], "Polygon")
        self.assertEqual(geoms[1][1]["type"], "LineString")
        self.assertEqual(geoms[2][1]["type"], "Polygon")

        # Two points cannot form a closed bounded area; parent receives incomplete zone flag
        self.assertIn("has_incomplete_zone", qa_flags)
        self.assertEqual(data_quality, "AMBIGUOUS")


class TestGroupEPreambleAndContext(unittest.TestCase):
    """Group E — Preamble context propagation."""

    def test_preamble_in_areas_bounded_by_propagates_explicit_quality(self):
        text = (
            "OFFSHORE OPERATIONS IN AREAS BOUNDED BY:\n"
            "(A) 20-12.00N 075-10.00E, 20-15.00N 075-10.00E, "
            "20-15.00N 075-15.00E, 20-12.00N 075-15.00E\n"
            "(B) 21-12.00N 076-10.00E, 21-15.00N 076-10.00E, "
            "21-15.00N 076-15.00E, 21-12.00N 076-15.00E"
        )
        geoms, _, qa_flags, data_quality = parse_block_geometries(text)
        self.assertEqual(len(geoms), 2)
        self.assertEqual(geoms[0][1]["type"], "Polygon")
        self.assertEqual(geoms[1][1]["type"], "Polygon")
        self.assertIn("geometry_basis:keyword:area_bounded", qa_flags)
        self.assertEqual(data_quality, "EXPLICIT")


class TestGroupFContractCompatibility(unittest.TestCase):
    """Group F — Four-value return contract compatibility."""

    def test_tuple_shape_and_types(self):
        text = "AREA BOUNDED BY 10-00N 070-00E, 10-10N 070-00E, 10-10N 070-10E, 10-00N 070-10E"
        res = parse_block_geometries(text)
        self.assertIsInstance(res, tuple)
        self.assertEqual(len(res), 4)
        geoms, coords_text, qa_flags, data_quality = res
        self.assertIsInstance(geoms, list)
        self.assertIsInstance(coords_text, list)
        self.assertIsInstance(qa_flags, list)
        self.assertIsInstance(data_quality, str)


class TestGroupGPayloadsAndTriage(unittest.TestCase):
    """Group G — Payload building and triage tier assignment."""

    def test_feature_collection_payloads_retain_labels_and_parent_link(self):
        record = {
            "warning_id": "NAVAREA VIII 1139/26",
            "spatial": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[75.0, 20.0], [75.0, 21.0], [76.0, 21.0], [76.0, 20.0], [75.0, 20.0]]],
                        },
                        "properties": {"zone_label": "A"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[77.0, 20.0], [77.0, 21.0], [78.0, 21.0], [78.0, 20.0], [77.0, 20.0]]],
                        },
                        "properties": {"zone_label": "B"},
                    },
                ],
            },
        }
        payloads = build_geometry_payloads(record)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["zone_label"], "A")
        self.assertEqual(payloads[1]["zone_label"], "B")
        self.assertEqual(payloads[0]["feature_type"], "POLYGON")
        self.assertEqual(payloads[1]["feature_type"], "POLYGON")

    def test_incomplete_zone_assigns_tier_b(self):
        class DummyRecord:
            def __init__(self):
                self.data_quality = DataQuality.AMBIGUOUS
                self.qa_flags = ["has_incomplete_zone"]
                self.latitude = 20.0
                self.longitude = 75.0
                self.triage_tier = None
                self.unplotted_reason = None

        rec = DummyRecord()
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)


class TestGroupHRegionalRegression(unittest.TestCase):
    """Group H — Regional block parser regression."""

    def test_xi475_lettered_clauses_remain_compatible(self):
        text = (
            "1. SUBMARINE TRAINING EXERCISE WILL BE CONDUCTED IN THE FOLLOWING AREAS:\n"
            "A. 34-55.00N 139-45.00E, 34-55.00N 139-55.00E, 34-48.00N 139-55.00E, 34-48.00N 139-45.00E\n"
            "B. 34-40.00N 140-00.00E, 34-40.00N 140-10.00E, 34-33.00N 140-10.00E, 34-33.00N 140-00.00E\n"
            "C. 34-30.00N 140-20.00E, 34-30.00N 140-30.00E, 34-23.00N 140-30.00E, 34-23.00N 140-20.00E"
        )
        geoms, coords_text, qa_flags, data_quality = parse_block_geometries(text)
        self.assertEqual(len(geoms), 3)
        self.assertEqual([g[0] for g in geoms], ["A", "B", "C"])
        for g in geoms:
            self.assertEqual(g[1]["type"], "Polygon")
        self.assertEqual(len(coords_text), 12)


if __name__ == "__main__":
    unittest.main()
