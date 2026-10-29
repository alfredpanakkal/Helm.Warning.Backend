#!/usr/bin/env python3
"""
tests/test_geometry_classifier.py — Geometry archetype classification regression suite.

Covers the tangled-polygon bug (NAVAREA VIII 961/26, 1096/26): scattered
'vicinity' lists and survey tracks must not be rendered as auto-closed
polygons. Exercises the REAL shared parser (no second parser), the
MultiPoint -> per-point POINT geometry-row explosion in shared/models,
and the ring topology guard (bowtie/self-intersection -> discrete
MultiPoint + AMBIGUOUS_FALLBACK review flag, never a fabricated shape).
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils import parse_coordinates, parse_coordinates_detailed
from shared.models import build_geometry_payloads
from shared.geometry_classifier import classify_geometry_archetype, _is_sequential, ring_is_simple


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
        raw = ("SUBMERGED OBJECT REPORTED AT 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
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


class TestRingTopologyGuard(unittest.TestCase):
    """Bowties / self-intersecting coordinate orders must not become filled polygons."""

    def test_bowtie_order_falls_back_to_multipoint(self):
        # BL, TR, TL, BR — classic bowtie ordering, no keywords: an
        # auto-closed ring (or a LineString 'path') would invent a shape
        # the source never states. Discrete markers + AMBIGUOUS_FALLBACK
        # so the record lands in the review queue, not the map.
        raw = ("OBSTRUCTION REPORTED AT 18-00N 071-00E, 18-30N 071-30E, "
               "18-30N 071-00E, 18-00N 071-30E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertIn("AMBIGUOUS_FALLBACK", report["flags"])
        self.assertEqual(report["data_quality"], "AMBIGUOUS")

    def test_valid_rectangle_keeps_polygon(self):
        raw = ("OBSTRUCTION REPORTED AT 18-00N 071-00E, 18-00N 071-30E, "
               "18-30N 071-30E, 18-30N 071-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")

    def test_v961_legacy_ring_is_crooked(self):
        # Regression guard: the 9 scattered points of VIII 961/26, closed
        # into the old legacy ring, ARE self-intersecting — the exact
        # 'crooked polygon' observed on the map before the classifier fix.
        _, _, _, pts_spatial = parse_coordinates(V961)
        ring = [list(c) for c in pts_spatial["coordinates"]]
        ring.append(list(ring[0]))
        self.assertFalse(ring_is_simple(ring))

    def test_ring_is_simple_square_and_bowtie(self):
        square = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        bowtie = [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]
        self.assertTrue(ring_is_simple(square))
        self.assertFalse(ring_is_simple(bowtie))
        self.assertFalse(ring_is_simple([[0, 0], [1, 1], [0, 0]]))  # < 3 unique


class TestKeywordTaxonomy(unittest.TestCase):
    """Live-bulletin vocabulary: area/line/point keyword routing."""

    def test_v1102_bounded_within_two_corners_expands_to_rectangle(self):
        # Real NAVAREA VIII 1102/26 format: two opposite corners after
        # 'AREA BOUNDED WITHIN' must expand into a closed rectangle ring,
        # not a 2-point corridor LineString.
        raw = ("HYDROGRAPHIC SURVEY UNDER PROGRESS IN AREA BOUNDED WITHIN "
               "14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")
        ring = spatial["coordinates"][0]
        self.assertEqual(len(ring), 5)            # 4 corners + closing
        self.assertEqual(ring[0], ring[-1])       # closed

    def test_v1102_axis_bbox_centroid_is_range_midpoint(self):
        # The axis-token fallback must also return the rectangle centroid
        # (midpoint of both ranges) as the primary position.
        raw = ("HYDROGRAPHIC SURVEY UNDER PROGRESS IN AREA BOUNDED WITHIN "
               "14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E")
        _, lat, lon, spatial = parse_coordinates(raw)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertAlmostEqual(lat, (14 + 47.2/60 + 14 + 50.9/60) / 2, places=4)
        self.assertAlmostEqual(lon, (74 + 2.8/60 + 74 + 8.15/60) / 2, places=4)

    def test_axis_bbox_fails_closed_on_three_lons(self):
        # Not a clean two-corner range (3 distinct longitudes): the
        # fallback must return no spatial at all, never guess a rectangle.
        raw = ("AREA BOUNDED WITHIN 14-47.2N TO 14-50.9N AND "
               "074-02.8E TO 074-08.15E TO 075-00.0E")
        _, lat, lon, spatial = parse_coordinates(raw)
        self.assertIsNone(spatial)
        self.assertIsNone(lat)

    def test_axis_tokens_fail_closed_without_bbox_phrase(self):
        # Axis-separated ranges WITHOUT the 'AREA BOUNDED WITHIN' phrase
        # must not fabricate a rectangle (gating on the bbox phrase).
        raw = "14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E"
        _, lat, lon, spatial = parse_coordinates(raw)
        self.assertIsNone(spatial)

    def test_exclusion_zone_keeps_polygon(self):
        raw = ("MARITIME EXCLUSION ZONE ENCOMPASSING 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")

    def test_trackline_forces_linestring(self):
        # Declared route: force LineString even with 4 waypoints (below
        # the NN-heuristic minimum) — the text itself declares a line.
        raw = ("OPERATIONS ALONG TRACKLINE JOINING 18-30N 071-00E, "
               "18-31N 071-05E, 18-32N 071-10E, 18-33N 071-15E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(len(spatial["coordinates"]), 4)

    def test_cable_route_forces_linestring(self):
        raw = ("CABLE RECOVERY OPERATIONS ALONG ROUTE 18-00N 071-00E, "
               "18-10N 071-20E, 18-20N 071-40E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "LineString")

    def test_racon_buoy_plural_list_is_multipoint(self):
        # '\bBUOY\b' does NOT match 'BUOYS' — plural forms must route
        # point-ops lists to MultiPoint, not a legacy polygon.
        raw = ("BUOYS AND RACONS OFF STATION AT 18-00N 071-00E, "
               "18-30N 071-30E, 19-00N 072-00E, 19-30N 072-30E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "MultiPoint")

    def test_wreck_shoal_point_ops(self):
        raw = ("WRECKS AND SHOALS REPORTED AT 18-00N 071-00E, "
               "18-30N 071-30E, 19-00N 072-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "MultiPoint")


class TestRigListAlwaysPoints(unittest.TestCase):
    """Standing rule (2026-10-28, AMENDED same day by owner decision):
    rig-class keywords (RIG / JACK-UP / DRILLSHIP / MODU) plot as points
    when NO boundary phrase is present, or when the list is long
    (> 6 positions — a genuine rig list). A rig keyword + boundary phrase
    + short list is AMBIGUOUS: flagged RIG_AREA_CONFLICT and classified by
    the normal keyword rules for human review — never silently forced."""

    def test_rig_short_list_in_bounded_area_is_flagged_conflict(self):
        # Rig + 'AREA BOUNDED BY' + only 4 positions: ambiguous — flag it,
        # then the normal bounded-area rule keeps the polygon for review.
        raw = ("FOLLOWING RIGS STATIONED IN AREA BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertIn("RIG_AREA_CONFLICT", report["flags"])

    def test_rig_long_list_in_bounded_area_is_multipoint(self):
        # > 6 positions wrapped in area wording is a genuine rig list:
        # discrete points, no conflict flag.
        coords = ", ".join(f"1{8 + i}-00N 07{1 + i}-00E" for i in range(8))
        raw = "FOLLOWING RIGS STATIONED IN AREA BOUNDED BY " + coords
        _, _, _, spatial, report = parse_coordinates_detailed(raw)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertEqual(len(spatial["coordinates"]), 8)
        self.assertNotIn("RIG_AREA_CONFLICT", report["flags"])
        self.assertEqual(report["basis"], "keyword:rig")

    def test_rig_under_tow_along_trackline_is_multipoint(self):
        raw = ("RIG UNDER TOW ALONG TRACKLINE JOINING 18-30N 071-00E, "
               "18-31N 071-05E, 18-32N 071-10E, 18-33N 071-15E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "MultiPoint")

    def test_modu_and_jackup_variants_route_to_points(self):
        raw = ("MODUS AND JACK-UPS ON LOCATION AT 18-00N 071-00E, "
               "19-00N 072-00E, 20-00N 073-00E, 21-00N 074-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "MultiPoint")

    def test_single_rig_position_stays_point(self):
        # Live NAVAREA IX 358/26: a single rig position is a plain Point
        # (a 1-point array never enters the archetype classifier).
        _, lat, lon, spatial = parse_coordinates(
            'RIG "ORIENTAL DRAGON 1" STATIONED IN 29-18.68N 048-12.70E')
        self.assertEqual(spatial["type"], "Point")
        self.assertIsNotNone(lat)

    def test_bounded_area_without_rigs_stays_polygon(self):
        # No rig-class keyword: the bounded-area rule keeps its polygon —
        # aton wording alone does not inherit the rig precedence.
        raw = ("BUOYS DEPLOYED IN AREA BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")


class TestMultiPointGeometryRows(unittest.TestCase):

    def test_multipoint_explodes_to_point_rows_no_invented_radius(self):
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
            self.assertEqual(g["buffer_nm"], 0.0)  # radius only when the source states one

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




class TestPositionsList(unittest.TestCase):
    """IN POSITIONS enumerations (audit 2026-10-29, finding F6,
    NAVAREA V 0370/26): bare position lists are discrete locations,
    never an auto-closed polygon (was a 153,800 km2 phantom area over
    a USV survey track)."""

    def test_v0370_usv_positions_list_is_multipoint(self):
        raw = ("UNDERWATER OPERATIONS BY USV FUGRO VAQUITA IN POSITIONS "
               "22-03.00S 037-06.48W, 20-27.24S 040-20.52W, "
               "22-59.46S 042-00.84W, 25-55.32S 040-11.58W")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "MultiPoint")
        self.assertEqual(len(spatial["coordinates"]), 4)

    def test_following_positions_is_multipoint(self):
        raw = ("FOLLOWING POSITIONS MARKED BY BUOYS: 18-00N 071-00E, "
               "18-30N 071-30E, 19-00N 072-00E, 19-30N 072-30E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "MultiPoint")

    def test_positions_list_inside_bounded_area_keeps_polygon(self):
        # An explicit boundary phrase wins over the positions-list rule:
        # the source states an area, not discrete locations.
        raw = ("OPERATIONS IN POSITIONS WITHIN AREA BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E")
        spatial = _spatial(raw)
        self.assertEqual(spatial["type"], "Polygon")

    def test_bare_position_list_wording_matches_nothing(self):
        # POSITION LIST without IN/FOLLOWING keeps the word-boundary
        # guarantee (companion to test_word_boundary_guards).
        self.assertIsNone(classify_geometry_archetype(
            "THIS IS THE POSITION LIST", [[71.0, 19.0], [72.0, 20.0]]))


if __name__ == "__main__":
    unittest.main()
