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
from datetime import datetime, timezone

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, REPO)

from shared.utils import (
    parse_coordinates, parse_coordinates_detailed, parse_block_geometries,
    rejoin_wrapped_coords,
)
from shared.models import build_master_payload
from shared.geometry_classifier import ring_is_simple
from scripts import dry_run_six_warning_geometry as offline_geometry_dry_run


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

    def test_five_unlabelled_points_keep_ring_guard(self):
        # A 5-position unlabelled list with a simple ring is
        # geometrically indistinguishable from a genuine 5-corner area
        # (XII 151/26 sub-area B): the ring guard keeps the legacy
        # polygon, and the fallback basis marks the record AMBIGUOUS
        # for review — never silently EXPLICIT. Genuinely scattered
        # 5-point sets produce crooked rings and land in the bowtie
        # branch (MultiPoint + AMBIGUOUS_FALLBACK).
        raw = ("OBSTRUCTION REPORTED AT 18-00N 071-00E, 19-10N 072-20E, "
               "20-40N 073-40E, 21-50N 074-50E, 22-20N 075-10E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["basis"], "fallback:legacy_polygon")
        self.assertEqual(report["data_quality"], "AMBIGUOUS")


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


class TestDottedLineRoutes(unittest.TestCase):
    """Source-worded dotted routes remain separate open lines and Tier B."""

    III_0169 = """NAVAREA III - 0169/26
03 November 2026 00:00 UTC
CENTRAL MEDITERRANEAN SEA
OCEANOGRAPHIC WORKS
OCEANOGRAPHIC WORK ON THE BRITOIL CENTURION (IMO 9619177 / MMSI 566921000)
DAYS 05 NOV 26 TO 15 FEB 27
FOLLOWING THE DOTTED LINE:
A
42 11,718N 009 59,778E
41 55.463N 010 06.575E
41 48.921N 010 22.386E
41 36.287N 010 32.817E
41 18.762N 010 35.890E
41 02.470N 010 42.350E
40 51.515N 010 55.697E
B
41 24,536N 006 10,312E
41 15,352N 006 42,299E
41 04.447N 006 55.017E
40 46.984N 006 58.881E
40 29.057N 006 59.907E
40 11.212N 007 01.863E
39 53,531N 007 05,221E
39 36.134N 007 09.841E
39 23.905N 007 21.336E
39 17.645N 007 32.114E
39 07.245N 007 40.415E
38 54.093N 007 44.943E
38 47.211N 007 55.733E
38 34.105N 008 08.816E
38 24,404N 008 23,951E
38 22.900N 008 37.252E
38 27,204N 008 54.302E
38 26.992N 009 12.300E
38 27.619N 009 30.256E
38 30,561N 009 53,983E
38 25.976N 010 11.262E
38 24.205N 010 30.113E
WIDE RECEIPT IS REQUESTED"""

    III_0171 = """NAVAREA III - 0171/26
06 November 2026 00:00 UTC
EASTERN MEDITERRANEAN SEA
CABLE OPERATIONS BY ABEILLE MARENGO (IMO 9388613)
DAYS 06 NOV 26 TO 06 MAR 27
ALONG THE DOTTED LINE:
35 24.98N 024 56.13E
35 28.18N 024 56.56E
35 29.86N 024 59.46E
35 30.28N 025 14.95E
35 25.04N 025 57.13E
35 26.62N 026 10.82E
35 23.13N 026 17.24E
35 21.44N 026 31.46E
35 18.51N 026 47.22E
35 18.15N 026 54.30E
35 19.95N 027 11.84E
35 19.34N 027 24.74E
35 12.93N 027 34.55E
35 00.96N 027 41.45E
34 46.87N 028 09.64E
34 41.74N 028 40.27E
34 26.01N 029 24.87E
34 22.57N 029 32.16E
34 16.97N 029 51.75E
34 11.28N 029 57.82E
34 09.68N 030 04.31E
2 MN OF BERTH IS REQUIRED
CANCEL THIS MSG 062200 UTC MAR 27."""

    IX_0440 = """NAVAREA IX 440/26
ARABIAN SEA
PAKISTAN
1. CABLE REPAIR OPERATION IN PROGRESS BY CS MARAM IN FOLLOWING AREA:
24-46.15N 066-51.13E
24-42.08N 066-34.99E
24-46.55N 066-50.41E
24-42.58N 066-34.85E
MARINERS ARE REQUESTED TO GIVE WIDE BERTH
2. CANCEL NAVAREA WARNING 437/26
140300 UTC NOV 2026"""

    @staticmethod
    def _parse(raw_text, region, header, number):
        mod = _load_universal_parser()
        cfg = mod._region_config(region)
        block = {
            "number": number,
            "year": "26",
            "header_text": header,
            "raw_text": raw_text,
        }
        _, warning = mod.parse_warning(
            block, cfg, now_utc=datetime(2026, 11, 15, tzinfo=timezone.utc)
        )
        return warning

    def test_0169_keeps_a_and_b_as_separate_lines_and_tier_b(self):
        warning = self._parse(
            self.III_0169, "iii", "NAVAREA III - 0169/26", "0169"
        )
        features = warning["spatial"]["features"]
        self.assertEqual([f["properties"]["sub_area"] for f in features], ["A", "B"])
        self.assertEqual([f["geometry"]["type"] for f in features],
                         ["LineString", "LineString"])
        self.assertEqual(len(features[0]["geometry"]["coordinates"]), 7)
        self.assertEqual(len(features[1]["geometry"]["coordinates"]), 22)
        self.assertEqual(warning["data_quality"], "EXPLICIT")
        for feature in features:
            coords = feature["geometry"]["coordinates"]
            self.assertNotEqual(coords[0], coords[-1])
        self.assertIn("DOTTED_LINE_ROUTE_REVIEW", warning["qa_flags"])
        self.assertEqual(build_master_payload(warning)["triage_tier"], "B")

    def test_0171_along_dotted_line_is_open_linestring_and_tier_b(self):
        warning = self._parse(
            self.III_0171, "iii", "NAVAREA III - 0171/26", "0171"
        )
        features = warning["spatial"]["features"]
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["geometry"]["type"], "LineString")
        self.assertEqual(len(features[0]["geometry"]["coordinates"]), 21)
        self.assertIsNone(features[0]["properties"]["sub_area"])
        self.assertIn("DOTTED_LINE_ROUTE_REVIEW", warning["qa_flags"])
        self.assertEqual(build_master_payload(warning)["triage_tier"], "B")

    def test_ix_440_remains_ambiguous_and_is_not_promoted_to_line_or_polygon(self):
        warning = self._parse(
            self.IX_0440, "ix", "NAVAREA IX 440/26", "440"
        )
        geometry = warning["spatial"]["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "MultiPoint")
        self.assertNotIn(geometry["type"], ("LineString", "Polygon"))
        self.assertEqual(warning["data_quality"], "AMBIGUOUS")
        self.assertEqual(build_master_payload(warning)["triage_tier"], "B")



class TestStoredSixWarningGeometryContracts(unittest.TestCase):
    """Verbatim stored-row contracts not already covered by identical fixtures."""

    III_0124 = """NAVAREA III - 0124/22
23 March 2022 00:00 UTC
BLACK SEA
WAR RISK AREA
1. WAR RISK AREA, IN NORTHWESTERN PART OF BLACK SEA TO NORTHERN OF LINE 
45-12.2N  029-41.1E
45-11.5N  029-41.4E
45-11.5N  033-10.5E
FROM 19 MAR 22 UNTIL FURTHER NOTICE.
2.- CANCEL NAVAREA III 0119/22 AND THIS PARAGRAPH"""

    III_0171_STORED = """NAVAREA III - 0171/26
06 November 2026 00:00 UTC
EASTERN MEDITERRANEAN SEA
CABLE OPERATIONS BY ABEILLE MARENGO (IMO 9388613)
CABLE OPERATIONS BY ABEILLE MARENGO (IMO 9388613) 
DAYS 06 NOV 26 TO 06 MAR 27
ALONG THE DOTTED LINE:
35 24.98N 024 56.13E
35 28.18N 024 56.56E
35 29.86N 024 59.46E
35 30.28N 025 14.95E
35 25.04N 025 57.13E
35 26.62N 026 10.82E
35 23.13N 026 17.24E
35 21.44N 026 31.46E
35 18.51N 026 47.22E
35 18.15N 026 54.30E
35 19.95N 027 11.84E
35 19.34N 027 24.74E
35 12.93N 027 34.55E
35 00.96N 027 41.45E
34 46.87N 028 09.64E
34 41.74N 028 40.27E
34 26.01N 029 24.87E
34 22.57N 029 32.16E
34 16.97N 029 51.75E
34 11.28N 029 57.82E
34 09.68N 030 04.31E
2 MN OF BERTH IS REQUIRED
CANCEL THIS MSG 062200 UTC MAR 27."""

    IX_428 = """NAVAREA IX 428/26
RED SEA
SAUDI ARABIA (AMAALA TRIPLE BAY)
BA CHART 159

SEAPLANE LANDING AND OPERATIONAL ZONE ESTABLISHED IN FOLLOWING AREA:

26-38.92N 036-13.32E
26-36.80N 036-14.95E
26-36.32N 036-14.15E
26-38.40N 036-12.53E

MARINERS CAUTIONED

031500 UTC NOV 2026"""

    IX_438 = """NAVAREA IX 438/26
ARABIAN SEA
PAKISTAN
CHARTS PAK 33, 57 (INT 751), BA 38, 39 AND 707

1. LIVE WEAPON FIRING SCHEDULED ON 14 NOV 26
BETWEEN 0300 TO 1300 UTC IN FOLLOWING AREA:

24-19.00N 066-58.00E
24-00.00N 066-39.00E
24-11.00N 066-27.00E
24-24.30N 066-42.00E

 MARINERS CAUTIONED

2. CANCEL THIS MSG 141500 UTC NOV 26

131855 UTC NOV 2026"""

    IX_440_STORED = """NAVAREA IX 440/26
ARABIAN SEA
PAKISTAN
CHARTS PAK 5 (INT 7314), 33, 57 (INT 751) AND BA 707

1. CABLE REPAIR OPERATION IN PROGRESS BY CS MARAM IN FOLLOWING AREA:

 24-46.15N 066-51.13E
 24-42.08N 066-34.99E
 24-46.55N 066-50.41E
 24-42.58N 066-34.85E

MARINERS ARE REQUESTED TO GIVE WIDE BERTH

2. CANCEL NAVAREA WARNING 437/26

140300 UTC NOV 2026"""

    @staticmethod
    def _parse_stored(raw_text, region, number):
        header = raw_text.splitlines()[0]
        return TestDottedLineRoutes._parse(
            raw_text, region, header, number
        )

    def test_iii_0124_war_risk_line_does_not_invent_boundary(self):
        warning = self._parse_stored(self.III_0124, "iii", "0124")
        geometries = [
            feature["geometry"]
            for feature in (warning.get("spatial") or {}).get("features", [])
        ]
        self.assertTrue(geometries)
        self.assertTrue(all(g["type"] not in ("Polygon", "MultiPolygon", "LineString")
                            for g in geometries))
        self.assertIn("AMBIGUOUS_FALLBACK", warning["qa_flags"])
        self.assertEqual(warning["data_quality"], "AMBIGUOUS")

    def test_iii_0171_exact_stored_text_remains_open_route(self):
        warning = self._parse_stored(self.III_0171_STORED, "iii", "0171")
        features = warning["spatial"]["features"]
        self.assertEqual(len(features), 1)
        geometry = features[0]["geometry"]
        self.assertEqual(geometry["type"], "LineString")
        self.assertEqual(len(geometry["coordinates"]), 21)
        self.assertNotEqual(geometry["coordinates"][0], geometry["coordinates"][-1])
        self.assertIn("DOTTED_LINE_ROUTE_REVIEW", warning["qa_flags"])
        self.assertEqual(warning["data_quality"], "EXPLICIT")
        self.assertEqual(build_master_payload(warning)["triage_tier"], "B")

    def _assert_legacy_area_is_ambiguous(self, warning):
        features = warning["spatial"]["features"]
        self.assertEqual(len(features), 1)
        geometry = features[0]["geometry"]
        self.assertEqual(geometry["type"], "Polygon")
        ring = geometry["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 5)
        self.assertTrue(ring_is_simple(ring))
        self.assertEqual(warning["data_quality"], "AMBIGUOUS")
        self.assertIn("geometry_basis:fallback:legacy_polygon", warning["qa_flags"])
        self.assertEqual(build_master_payload(warning)["triage_tier"], "B")

    def test_ix_428_following_area_is_valid_ambiguous_legacy_ring(self):
        warning = self._parse_stored(self.IX_428, "ix", "428")
        self._assert_legacy_area_is_ambiguous(warning)

    def test_ix_438_following_area_is_valid_ambiguous_legacy_ring(self):
        warning = self._parse_stored(self.IX_438, "ix", "438")
        self._assert_legacy_area_is_ambiguous(warning)

    def test_ix_440_exact_stored_text_bowtie_stays_ambiguous_points(self):
        warning = self._parse_stored(self.IX_440_STORED, "ix", "440")
        geometries = [
            feature["geometry"]
            for feature in (warning.get("spatial") or {}).get("features", [])
        ]
        self.assertEqual(len(geometries), 1)
        self.assertEqual(geometries[0]["type"], "MultiPoint")
        self.assertNotIn(geometries[0]["type"], ("Polygon", "MultiPolygon", "LineString"))
        self.assertIn("AMBIGUOUS_FALLBACK", warning["qa_flags"])
        self.assertIn("geometry_basis:fallback:bowtie", warning["qa_flags"])
        self.assertEqual(warning["data_quality"], "AMBIGUOUS")
        self.assertEqual(build_master_payload(warning)["triage_tier"], "B")


    def test_offline_json_dry_run_processes_all_six_verbatim_inputs(self):
        records = [
            {"canonical_id": "NAVAREA III 0124/22", "raw_text": self.III_0124},
            {"canonical_id": "NAVAREA III 0169/26", "raw_text": TestDottedLineRoutes.III_0169},
            {"canonical_id": "NAVAREA III 0171/26", "raw_text": self.III_0171_STORED},
            {"canonical_id": "NAVAREA IX 428/26", "raw_text": self.IX_428},
            {"canonical_id": "NAVAREA IX 438/26", "raw_text": self.IX_438},
            {"canonical_id": "NAVAREA IX 440/26", "raw_text": self.IX_440_STORED},
        ]
        report = offline_geometry_dry_run.run_json_inputs(records)
        by_id = {item["canonical_id"]: item for item in report["results"]}
        self.assertEqual(report["input_count"], 6)
        self.assertEqual(
            by_id["NAVAREA III 0169/26"]["geometry_type"],
            ["LineString", "LineString"],
        )
        self.assertEqual(by_id["NAVAREA III 0169/26"]["coordinate_count"], 29)
        self.assertEqual(by_id["NAVAREA III 0171/26"]["geometry_type"], "LineString")
        self.assertEqual(by_id["NAVAREA III 0171/26"]["coordinate_count"], 21)
        self.assertEqual(by_id["NAVAREA III 0124/22"]["geometry_type"], "MultiPoint")
        self.assertEqual(by_id["NAVAREA IX 428/26"]["geometry_type"], "Polygon")
        self.assertEqual(by_id["NAVAREA IX 438/26"]["geometry_type"], "Polygon")
        self.assertEqual(by_id["NAVAREA IX 440/26"]["geometry_type"], "MultiPoint")
        for canonical_id in (
            "NAVAREA III 0124/22", "NAVAREA IX 428/26",
            "NAVAREA IX 438/26", "NAVAREA IX 440/26",
        ):
            self.assertEqual(by_id[canonical_id]["data_quality"], "AMBIGUOUS")
            self.assertEqual(by_id[canonical_id]["triage_tier"], "B")
        for canonical_id in ("NAVAREA III 0169/26", "NAVAREA III 0171/26"):
            self.assertEqual(by_id[canonical_id]["data_quality"], "EXPLICIT")
            self.assertEqual(by_id[canonical_id]["triage_tier"], "B")


if __name__ == "__main__":
    unittest.main()
