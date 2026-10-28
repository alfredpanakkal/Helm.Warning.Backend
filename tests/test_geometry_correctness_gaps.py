#!/usr/bin/env python3
"""
tests/test_geometry_correctness_gaps.py — Fixtures for the 7 confirmed
'silent wrong geometry' gaps (A1-A7), each reproduced from a live bulletin
raw text before the fix:

  A1  line-wrapped coordinate tokens (NAVAREA VIII 1087/26)
  A2  lettered sub-areas merged into one shape (NAVAREA XI 0475/26)
  A3  'ALONG LINE JOINING' shadowed by the Area rule
  A4  rig keyword hiding a real bounded area (NAVAREA III 0122/26)
  A5  unlabelled 3/5-point lists and bowties inventing a LineString
  A6  data_quality never reflecting geometry guesses
  A7  silent discards ('91-00.0N' out of range, missing hemisphere)
"""

import os
import sys
import unittest
import importlib.util

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, REPO)

from shared.utils import (
    parse_coordinates, parse_coordinates_detailed, parse_block_geometries,
    rejoin_wrapped_coords,
)
from shared.models import build_master_payload


def _load_universal_parser():
    spec = importlib.util.spec_from_file_location(
        "navarea_universal_parser_under_test",
        os.path.join(REPO, "scripts", "navarea_universal_parser.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# NAVAREA VIII 1087/26 shape: every coordinate token is split across a
# line wrap ("16-
# 40.27N"). Before the fix the parser saw 4 of 6 positions
# and built a truncated polygon; the raw excerpt held 6 vertices.
V1087 = """NAVAREA VIII 1087/26 WEST COAST OF INDIA - LIVE FIRING
BY VESSEL IN AREA BOUNDED BY
16-
38.50N 082-
09.00E, 16-
38.50N 082-
16.00E, 16-
40.10N 082-
17.00E, 16-
41.50N 082-
16.00E, 16-
41.50N 082-
09.00E, 16-
40.10N 082-
08.00E.
CANCEL THIS MSG 31 DEC 26."""

# NAVAREA XI 0475/26 shape: three lettered sub-areas A/B/C. Before the
# fix the whole block parsed as ONE merged 12-point shape.
XI475 = """1. SUBMARINE TRAINING EXERCISE WILL BE CONDUCTED IN THE FOLLOWING AREAS:
A. 34-55.00N 139-45.00E, 34-55.00N 139-55.00E, 34-48.00N 139-55.00E, 34-48.00N 139-45.00E
B. 34-40.00N 140-00.00E, 34-40.00N 140-10.00E, 34-33.00N 140-10.00E, 34-33.00N 140-00.00E
C. 34-30.00N 140-20.00E, 34-30.00N 140-30.00E, 34-23.00N 140-30.00E, 34-23.00N 140-20.00E"""

# NAVAREA III 0122/26 shape: drilling operations BY a RIG in a bounded
# area with 4 corners — the old rig rule forced 4 markers and hid the area.
III122_DELIMITED = ("DRILLING OPERATIONS BY RIG PERRODOCE 7 IN AREA DELIMITED BY "
                    "18-00N 071-00E, 18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
III122_BOUNDED = ("DRILLING OPERATIONS BY RIG PERRODOCE 7 IN AREA BOUNDED BY "
                  "18-00N 071-00E, 18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")


class TestLineWrapRejoin(unittest.TestCase):
    """A1: wrapped coordinate tokens rejoin before extraction."""

    def test_rejoin_wrapped_degrees_hyphen(self):
        self.assertEqual(rejoin_wrapped_coords("16-\n40.27N"), "16-40.27N")
        self.assertEqual(rejoin_wrapped_coords("082-\n10.55E"), "082-10.55E")

    def test_rejoin_is_idempotent(self):
        once = rejoin_wrapped_coords(V1087)
        self.assertEqual(rejoin_wrapped_coords(once), once)

    def test_rejoin_leaves_prose_wraps_alone(self):
        raw = "IN AREA BO\nUND BY 18-00N 071-00E"
        self.assertEqual(rejoin_wrapped_coords(raw), raw)

    def test_v1087_extracts_all_six_vertices(self):
        coords, lat, lon, spatial, report = parse_coordinates_detailed(V1087)
        self.assertEqual(spatial["type"], "Polygon")
        ring = spatial["coordinates"][0]
        self.assertEqual(len(ring), 7)  # 6 vertices + closing
        self.assertEqual(len({tuple(p) for p in ring}), 6)
        self.assertNotIn("COORD_COUNT_MISMATCH", report["flags"])
        self.assertEqual(report["data_quality"], "EXPLICIT")
        self.assertEqual(report["basis"], "keyword:area_bounded")

    def test_count_mismatch_never_builds_polygon(self):
        # The out-of-range pair ('91-00.0N') is refused by the pair
        # patterns: the loose token count exceeds the extracted pairs, so
        # the remainder must never be closed into a polygon.
        raw = ("AREA BOUNDED BY 18-00N 071-00E, 18-00N 072-00E, "
               "91-00.0N 010-00.0E, 18-30N 071-30E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertNotEqual(spatial["type"], "Polygon")
        self.assertIn("COORD_COUNT_MISMATCH", report["flags"])
        reasons = {r["token"]: r["reason"] for r in report["rejected"]}
        self.assertEqual(reasons.get("91-00.0N"), "validation_failed")


class TestLetteredSubAreas(unittest.TestCase):
    """A2: lettered clauses parse as separate geometries."""

    def test_xi475_three_polygons(self):
        geoms, coords_text, qa_flags, data_quality = parse_block_geometries(XI475)
        self.assertEqual(len(geoms), 3)
        self.assertEqual([g[0] for g in geoms], ["A", "B", "C"])
        for _label, spatial, _lat, _lon in geoms:
            self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(len(coords_text), 12)  # 4 pairs per sub-area
        self.assertIn("geometry_basis:fallback:legacy_polygon", qa_flags)
        self.assertEqual(data_quality, "AMBIGUOUS")

    def test_universal_segment_clauses_labels(self):
        mod = _load_universal_parser()
        body = XI475
        clauses = mod._segment_clauses(body)
        self.assertEqual([c["label"] for c in clauses], ["1", "A", "B", "C"])


class TestAlongLineJoining(unittest.TestCase):
    """A3: 'ALONG LINE JOINING' is a route, not a bounded area."""

    def test_along_line_joining_is_linestring(self):
        raw = ("OPERATIONS ALONG LINE JOINING 18-30N 071-00E, "
               "18-31N 071-05E, 18-32N 071-10E, 18-33N 071-15E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(len(spatial["coordinates"]), 4)
        self.assertEqual(report["basis"], "keyword:linear")
        self.assertEqual(report["data_quality"], "EXPLICIT")


class TestRigAreaConflict(unittest.TestCase):
    """A4: rig keyword + boundary phrase + short list -> review flag."""

    def test_iii122_delimited_is_flagged(self):
        _, _, _, spatial, report = parse_coordinates_detailed(III122_DELIMITED)
        self.assertIn("RIG_AREA_CONFLICT", report["flags"])
        self.assertEqual(spatial["type"], "Polygon")

    def test_iii122_bounded_is_flagged(self):
        _, _, _, spatial, report = parse_coordinates_detailed(III122_BOUNDED)
        self.assertIn("RIG_AREA_CONFLICT", report["flags"])
        self.assertEqual(spatial["type"], "Polygon")


class TestAmbiguousFallbacks(unittest.TestCase):
    """A5: unlabelled scattered lists never invent a path."""

    def test_three_scattered_points_are_multipoint(self):
        raw = ("OBSTRUCTION REPORTED AT 18-00N 071-00E, "
               "19-10N 072-20E, 20-40N 073-40E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertIn("AMBIGUOUS_FALLBACK", report["flags"])
        self.assertEqual(report["data_quality"], "AMBIGUOUS")

    def test_five_scattered_points_are_multipoint(self):
        raw = ("OBSTRUCTION REPORTED AT 18-00N 071-00E, 19-10N 072-20E, "
               "20-40N 073-40E, 21-50N 074-50E, 22-20N 075-10E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertIn("AMBIGUOUS_FALLBACK", report["flags"])


class TestGeometryQualityBasis(unittest.TestCase):
    """A6: data_quality reflects how the geometry was decided."""

    def test_keyword_bounded_area_is_explicit(self):
        raw = ("HYDROGRAPHIC SURVEY IN AREA BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["basis"], "keyword:area_bounded")
        self.assertEqual(report["data_quality"], "EXPLICIT")

    def test_sequential_survey_is_inferred(self):
        coords = ", ".join(f"18-{30 + i:02d}N 071-00E" for i in range(6))
        raw = "SEABED SURVEY AT " + coords
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(report["basis"], "heuristic:sequential")
        self.assertEqual(report["data_quality"], "INFERRED")


class TestSilentDiscards(unittest.TestCase):
    """A7: refused tokens carry flags and specific unplotted reasons."""

    def test_out_of_range_pair_flags_validation(self):
        _, lat, lon, spatial, report = parse_coordinates_detailed(
            "91-00.0N 010-00.0E")
        self.assertIsNone(spatial)
        self.assertIsNone(lat)
        self.assertIn("VALIDATION_FAILED", report["flags"])
        self.assertIn("COORD_COUNT_MISMATCH", report["flags"])
        reasons = {r["token"]: r["reason"] for r in report["rejected"]}
        self.assertEqual(reasons.get("91-00.0N"), "validation_failed")

    def test_missing_hemisphere_flags_missing_hem(self):
        _, _, _, spatial, report = parse_coordinates_detailed(
            "POSITION 18-30.5 ,")
        self.assertIsNone(spatial)
        self.assertIn("MISSING_HEM", report["flags"])
        reasons = {r["token"]: r["reason"] for r in report["rejected"]}
        self.assertEqual(reasons.get("18-30.5"), "missing_hemisphere")

    def test_master_payload_maps_missing_hem_reason(self):
        payload = build_master_payload({
            "navarea": "VIII", "warning_id": "1087/26", "title": "T",
            "qa_flags": ["MISSING_HEM"],
        })
        self.assertEqual(payload["triage_tier"], "C")
        self.assertEqual(payload["unplotted_reason"], "missing_hemisphere")

    def test_master_payload_maps_validation_reason(self):
        payload = build_master_payload({
            "navarea": "VIII", "warning_id": "1088/26", "title": "T",
            "qa_flags": ["VALIDATION_FAILED"],
        })
        self.assertEqual(payload["unplotted_reason"], "validation_failed")

    def test_master_payload_silent_parse_stays_generic(self):
        payload = build_master_payload({
            "navarea": "VIII", "warning_id": "1089/26", "title": "T",
            "qa_flags": [],
        })
        self.assertEqual(payload["unplotted_reason"], "no_valid_geometry")

    def test_parse_coordinates_wrapper_signature_unchanged(self):
        # The 4-tuple wrapper must keep its contract for existing callers.
        result = parse_coordinates(III122_BOUNDED)
        self.assertEqual(len(result), 4)


if __name__ == "__main__":
    unittest.main()
