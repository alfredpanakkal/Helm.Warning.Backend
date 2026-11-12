"""tests/test_multi_zone_backend.py — Dedicated Phase B3 regression suite.

Covers:
- Group A: Marker detection & punctuation variants ((A)..(D), (A):..(D):, AREA 1..2, AREA A:..B:)
- Group B: False-positive protection (prose, non-monotonic, isolated and mixed marker families)
- Group C: Strict coordinate isolation (geographically distant polygons, zero cross-contamination)
- Group D: Incomplete-zone quarantine, valid MultiPolygon preservation, and parent QA roll-up
- Group E: Governing preamble context propagation and geometry classification
- Group F: Four-value return contract compatibility
- Group G: Regional parser adapter, payload generation, and triage integration
- Group H: NAVAREA XI shared-parser compatibility (other regional fixtures remain in full regression)
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shared.navarea_universal_text import subarea_marks
from shared.utils import parse_block_geometries
from shared.models import (
    build_geometry_payloads, build_master_payload, TriageTier,
    CoordinateProvenance, DataQuality,
)
from shared.triage import assign_final_triage
from scripts.navarea_1_parser import parse_warning
from scripts.navarea_8_parser import _segment_clauses as segment_navarea_viii
from scripts.navarea_universal_parser import _segment_clauses as segment_universal


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

    def test_area_number_markers_split_in_shared_parser(self):
        text = (
            "IN AREAS BOUNDED BY:\n"
            "AREA 1 20-12.0N 075-10.0E, 20-15.0N 075-10.0E, "
            "20-15.0N 075-15.0E, 20-12.0N 075-15.0E\n"
            "AREA 2 21-12.0N 076-10.0E, 21-15.0N 076-10.0E, "
            "21-15.0N 076-15.0E, 21-12.0N 076-15.0E"
        )
        geoms, _, qa_flags, data_quality = parse_block_geometries(text)
        self.assertEqual([g[0] for g in geoms], ["1", "2"])
        self.assertEqual([g[1]["type"] for g in geoms], ["Polygon", "Polygon"])
        self.assertNotIn("has_incomplete_zone", qa_flags)
        self.assertEqual(data_quality, "EXPLICIT")


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

    def test_mixed_marker_families_fail_closed(self):
        text = (
            "(A) 20-12.0N 075-10.0E (B) 21-12.0N 076-10.0E "
            "AREA 1 22-12.0N 077-10.0E AREA 2 23-12.0N 078-10.0E"
        )
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
        self.assertEqual(len(geoms), 2)
        self.assertEqual([g[0] for g in geoms], ["A", "C"])
        self.assertEqual(geoms[0][1]["type"], "Polygon")
        self.assertEqual(geoms[1][1]["type"], "Polygon")
        # Coordinates from incomplete B remain available for QA/audit, but no B geometry is emitted.
        self.assertEqual(len(coords_text), 9)

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
        self.assertEqual(len(geoms), 2)
        self.assertEqual([g[0] for g in geoms], ["A", "C"])
        self.assertEqual(geoms[0][1]["type"], "Polygon")
        self.assertEqual(geoms[1][1]["type"], "Polygon")
        # Coordinates from incomplete B remain available for QA/audit, but no B geometry is emitted.
        self.assertEqual(len(coords_text), 10)

        # Two points cannot form a closed bounded area; parent receives incomplete zone flag
        self.assertIn("has_incomplete_zone", qa_flags)
        self.assertEqual(data_quality, "AMBIGUOUS")


    def test_valid_multipolygon_is_not_quarantined(self):
        text = (
            "AREA BOUNDED WITHIN:\n"
            "(A) 10-00N 170-00E (B) 20-00N 170-00E"
        )
        multi = {
            "type": "MultiPolygon",
            "coordinates": [[[[170.0, 10.0], [171.0, 10.0], [171.0, 11.0],
                              [170.0, 11.0], [170.0, 10.0]]]],
        }
        report = {
            "flags": [],
            "basis": "keyword:bounding_box",
            "data_quality": "EXPLICIT",
            "feature_type": "BOUNDING_BOX",
        }
        with patch(
            "shared.utils.parse_coordinates_detailed",
            side_effect=[
                (["10-00N 170-00E"], 10.0, 170.0, multi, report),
                (["20-00N 170-00E"], 20.0, 170.0, multi, report),
            ],
        ):
            geoms, _, qa_flags, data_quality = parse_block_geometries(text)

        self.assertEqual(len(geoms), 2)
        self.assertEqual([g[1]["type"] for g in geoms], ["MultiPolygon", "MultiPolygon"])
        self.assertNotIn("has_incomplete_zone", qa_flags)
        self.assertEqual(data_quality, "EXPLICIT")


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
    """Group G — Actual parser adapter, payload, and triage integration."""

    def _parse_incomplete_notice(self):
        raw_block = (
            "PIPELINE OPERATIONS. IN AREAS BOUNDED BY:\n"
            "(A) 20-12.00N 075-10.00E, 20-15.00N 075-10.00E, "
            "20-15.00N 075-15.00E, 20-12.00N 075-15.00E\n"
            "(B) 21-12.00N 076-10.00E\n"
            "(C) 22-12.00N 077-10.00E, 22-15.00N 077-10.00E, "
            "22-15.00N 077-15.00E, 22-12.00N 077-15.00E"
        )
        return parse_warning(raw_block, "NAVAREA I 999/26")

    def test_adapter_and_payload_exclude_incomplete_zone(self):
        _, nav_warning, spatial = self._parse_incomplete_notice()

        self.assertEqual(spatial["type"], "FeatureCollection")
        self.assertEqual(
            [f["properties"]["zone_label"] for f in spatial["features"]],
            ["A", "C"],
        )
        self.assertIn("has_incomplete_zone", nav_warning["qa_flags"])
        self.assertEqual(nav_warning["data_quality"], "AMBIGUOUS")

        payloads = build_geometry_payloads(nav_warning)
        self.assertEqual([p["zone_label"] for p in payloads], ["A", "C"])
        self.assertEqual([p["feature_type"] for p in payloads], ["POLYGON", "POLYGON"])
        self.assertEqual(nav_warning["warning_id"], "999/26")

    def test_actual_parser_qa_assigns_tier_b(self):
        _, nav_warning, _ = self._parse_incomplete_notice()
        rec = SimpleNamespace(
            data_quality=nav_warning["data_quality"],
            qa_flags=nav_warning["qa_flags"],
            latitude=nav_warning["latitude"],
            longitude=nav_warning["longitude"],
            coordinates=[],
            triage_tier=None,
            unplotted_reason=None,
        )
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_all_incomplete_zones_persist_as_tier_c_with_coordinate_provenance(self):
        raw_block = (
            "PIPELINE OPERATIONS. IN AREAS BOUNDED BY:\n"
            "(A) 20-12.00N 075-10.00E\n"
            "(B) 21-12.00N 076-10.00E, 21-15.00N 076-10.00E"
        )
        _, nav_warning, spatial = parse_warning(raw_block, "NAVAREA I 998/26")

        # The adapter must not invent a fallback point when every bounded
        # sub-area is incomplete.
        self.assertIsNone(spatial)
        self.assertIsNone(nav_warning["spatial"])
        self.assertIsNone(nav_warning["latitude"])
        self.assertIsNone(nav_warning["longitude"])
        self.assertTrue(nav_warning["coordinates"])
        self.assertIn("has_incomplete_zone", nav_warning["qa_flags"])
        self.assertEqual(build_geometry_payloads(nav_warning), [])

        # Model the downstream provenance-bearing triage record. Coordinate
        # provenance is retained for audit, but it is not operational geometry.
        rec = SimpleNamespace(
            data_quality=DataQuality.AMBIGUOUS,
            qa_flags=nav_warning["qa_flags"],
            latitude=None,
            longitude=None,
            coordinates=[
                CoordinateProvenance(
                    raw_token="20-12.00N 075-10.00E",
                    lat=20.2,
                    lon=75.1666667,
                ),
                CoordinateProvenance(
                    raw_token="21-12.00N 076-10.00E",
                    lat=21.2,
                    lon=76.1666667,
                ),
                CoordinateProvenance(
                    raw_token="21-15.00N 076-10.00E",
                    lat=21.25,
                    lon=76.1666667,
                ),
            ],
            triage_tier=None,
            unplotted_reason=None,
        )
        assign_final_triage(rec)
        # Retained coordinate provenance is not operational geometry
        # when every bounded zone was quarantined.
        self.assertEqual(rec.triage_tier, TriageTier.C)
        self.assertEqual(rec.unplotted_reason, "no_valid_geometry")

        master_record = {
            **nav_warning,
            "data_quality": rec.data_quality.value,
            "qa_flags": rec.qa_flags,
            "triage_tier": rec.triage_tier.value,
            "unplotted_reason": rec.unplotted_reason,
            "parsing_method": "RULE",
        }
        master = build_master_payload(master_record)
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "no_valid_geometry")
        self.assertEqual(build_geometry_payloads(master_record), [])


class TestGroupVIIIAndUniversalSegmentation(unittest.TestCase):
    """Regional adapter coverage for inline punctuation variants."""

    def _assert_colon_markers_split(self, segmenter):
        body = (
            "OFFSHORE OPERATIONS IN AREAS BOUNDED BY:\n"
            "(A): 20-12.00N 075-10.00E, 20-15.00N 075-10.00E\n"
            "(B): 21-12.00N 076-10.00E, 21-15.00N 076-10.00E"
        )
        clauses = segmenter(body)
        zones = [c for c in clauses if c["label"] in ("A", "B")]
        self.assertEqual([c["label"] for c in zones], ["A", "B"])
        self.assertIn("20-12.00N", zones[0]["text"])
        self.assertIn("21-12.00N", zones[1]["text"])
        self.assertTrue(all(c.get("context") == "OFFSHORE OPERATIONS IN AREAS BOUNDED BY:" for c in zones))

    def test_navarea_viii_colon_markers(self):
        self._assert_colon_markers_split(segment_navarea_viii)

    def test_universal_parser_colon_markers(self):
        self._assert_colon_markers_split(segment_universal)


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
