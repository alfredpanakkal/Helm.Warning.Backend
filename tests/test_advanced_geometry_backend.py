#!/usr/bin/env python3
"""tests/test_advanced_geometry_backend.py
Unit and regression tests for Phase B2: Advanced Geometry, Sector Sweep
Generalization, Corridor Swaths, Relocations, and End-to-End Metadata Propagation.
"""

import unittest
from pathlib import Path
from shared.models import build_geometry_payloads, build_master_payload
from shared.geometry_classifier import ring_is_simple, split_antimeridian_ring
from shared.utils import (
    parse_coordinates,
    parse_coordinates_detailed,
    parse_block_geometries,
    parse_corridor_clearance,
    _extract_relocation_positions,
    _extract_sweep_params,
    _sector_from_sweep_wording,
)
from scripts.navarea_universal_parser import parse_bulletin_text
from scripts.navarea_xi_parser import parse_warning as parse_navarea_xi_warning


class TestSectorSweeps(unittest.TestCase):
    """Task 1: Sector sweeps across 5 phrasing variations, directional arcs, and boundary cases."""

    def test_phrase_variant_1_within_between(self):
        # WITHIN <radius> <unit> OF [POS] BETWEEN <a> AND <b> [DEGREES]
        text = "GUNNERY EXERCISE WITHIN 10 NM OF 15-30.0N 060-00.0E BETWEEN 090 AND 180 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")
        self.assertEqual(report["basis"], "keyword:sweep_sector")
        self.assertEqual(report["sweep_radius_nm"], 10.0)
        self.assertEqual(report["sweep_start_azimuth"], 90.0)
        self.assertEqual(report["sweep_end_azimuth"], 180.0)
        self.assertEqual(report["data_quality"], "EXPLICIT")

    def test_phrase_variant_2_between_out_to(self):
        # BETWEEN [BEARINGS] <a> AND <b> [DEGREES] OUT TO <radius> <unit>
        text = "ROCKET FIRING BETWEEN BEARINGS 340 AND 020 DEGREES OUT TO 20 NM FROM 15-30.0N 060-00.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")
        self.assertEqual(report["sweep_radius_nm"], 20.0)
        self.assertEqual(report["sweep_start_azimuth"], 340.0)
        self.assertEqual(report["sweep_end_azimuth"], 20.0)

    def test_phrase_variant_3_sector_bounded_by_radius(self):
        # SECTOR BOUNDED BY <a> AND <b> [DEGREES] RADIUS <radius> <unit>
        text = "HAZARDOUS OPERATIONS IN SECTOR BOUNDED BY 045 AND 135 DEGREES RADIUS 15 NM OF 15-30.0N 060-00.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")
        self.assertEqual(report["sweep_radius_nm"], 15.0)
        self.assertEqual(report["sweep_start_azimuth"], 45.0)
        self.assertEqual(report["sweep_end_azimuth"], 135.0)

    def test_phrase_variant_4_sector_circle_radius_between(self):
        # SECTOR OF A CIRCLE RADIUS <radius> <unit> BETWEEN <a> AND <b> [DEGREES]
        text = "EXERCISE IN SECTOR OF A CIRCLE RADIUS 25 NM BETWEEN 180 AND 270 DEGREES CENTERED ON 15-30.0N 060-00.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")
        self.assertEqual(report["sweep_radius_nm"], 25.0)
        self.assertEqual(report["sweep_start_azimuth"], 180.0)
        self.assertEqual(report["sweep_end_azimuth"], 270.0)

    def test_phrase_variant_5_sector_extending_between(self):
        # SECTOR EXTENDING <radius> <unit> BETWEEN [BEARINGS] <a> AND <b>
        text = "MILITARY PRACTICE IN SECTOR EXTENDING 12 N.M. BETWEEN 270 AND 360 DEGREES OF 15-30.0N 060-00.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")
        self.assertEqual(report["sweep_radius_nm"], 12.0)
        self.assertEqual(report["sweep_start_azimuth"], 270.0)
        self.assertEqual(report["sweep_end_azimuth"], 360.0)

    def test_clockwise_north_crossing(self):
        # 340 to 020 degrees is a 40-degree clockwise span across true North
        text = "FIRING WITHIN 10 NM OF 10-00.0N 050-00.0E BETWEEN 340 AND 020 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["sweep_start_azimuth"], 340.0)
        self.assertEqual(report["sweep_end_azimuth"], 20.0)
        ring = spatial["coordinates"][0]
        # Centre is first and last vertex
        self.assertEqual(ring[0], [50.0, 10.0])
        self.assertEqual(ring[-1], [50.0, 10.0])

    def test_zero_width_fails_closed_to_point(self):
        # 100 to 100 degrees has zero angular width: fail closed to Point
        text = "FIRING WITHIN 10 NM OF 10-00.0N 050-00.0E BETWEEN 100 AND 100 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Point")
        self.assertEqual(spatial["coordinates"], [50.0, 10.0])
        self.assertNotIn("sweep_radius_nm", report)

    def test_full_circle_360_degree(self):
        # 000 to 360 degrees represents full circle around centre
        text = "SPECIAL OPERATIONS WITHIN 5 NM OF 10-00.0N 050-00.0E BETWEEN 000 AND 360 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")
        self.assertEqual(report["sweep_radius_nm"], 5.0)
        ring = spatial["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])  # closed circle ring

    def test_antimeridian_crossing_fails_closed_to_point(self):
        # Sector spanning across 180/-180 meridian fails closed to safe Point
        text = "FIRING WITHIN 100 NM OF 10-00.0N 179-30.0E BETWEEN 045 AND 135 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Point")
        self.assertNotIn("sweep_radius_nm", report)

    def test_high_latitude_fan(self):
        # High Arctic 75N sector
        text = "RESEARCH EXERCISE WITHIN 15 NM OF 75-00.0N 010-00.0E BETWEEN 030 AND 090 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "SWEEP_ARC")


class TestCorridorSwaths(unittest.TestCase):
    """Task 2: Linear corridor clearance, wide berths, and safety zones."""

    def test_route_with_nautical_miles_berth(self):
        text = (
            "CABLE LAYING OPERATIONS ALONG LINE JOINING "
            "10-00.0N 060-00.0E AND 10-30.0N 060-30.0E. "
            "WIDE BERTH OF 2 NM REQUESTED."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(report["feature_type"], "CORRIDOR")
        self.assertEqual(report["buffer_nm"], 0.0)
        self.assertEqual(report["corridor_clearance_nm"], 2.0)
        self.assertNotIn("corridor_half_width_nm", report)
        self.assertIn("corridor_width_semantics_ambiguous", report["flags"])
        # Raw route coordinates are strictly preserved (no artificial buffer deformation)
        self.assertEqual(spatial["coordinates"], [[60.0, 10.0], [60.5, 10.5]])

    def test_route_with_meters_clearance(self):
        text = (
            "SURVEY ALONG TRACK 12-00.0N 050-00.0E TO 12-20.0N 050-20.0E. "
            "SAFETY CLEARANCE OF 500 METRES REQUESTED."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(report["feature_type"], "CORRIDOR")
        self.assertEqual(report["buffer_nm"], 0.0)
        self.assertEqual(report["corridor_clearance_nm"], round(500 / 1852.0, 3))
        self.assertNotIn("corridor_half_width_nm", report)

    def test_route_with_km_clearance(self):
        text = (
            "PIPE LAYING ALONG LINE 14-00.0N 070-00.0E TO 14-10.0N 070-10.0E. "
            "KEEP CLEAR BY 3 KILOMETRES."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(report["feature_type"], "CORRIDOR")
        self.assertEqual(report["buffer_nm"], 0.0)
        self.assertEqual(report["corridor_clearance_nm"], round(3.0 / 1.852, 3))
        self.assertNotIn("corridor_half_width_nm", report)

    def test_point_safety_zone(self):
        text = "DRILLING RIG AT 18-30.0N 072-00.0E. 500 METRES SAFETY ZONE IN FORCE."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Point")
        self.assertEqual(report["feature_type"], "POINT")
        self.assertEqual(report["buffer_nm"], round(500 / 1852.0, 3))

    def test_bare_m_rejected_fails_closed(self):
        # Bare 'M' (e.g. 500 M) could be miles or metres: must reject to 0.0
        text = "PIPE LAYING ALONG LINE 14-00.0N 070-00.0E TO 14-10.0N 070-10.0E. WIDE BERTH OF 500 M."
        self.assertIsNone(parse_corridor_clearance(text))
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(report["feature_type"], "LINE")
        self.assertEqual(report["buffer_nm"], 0.0)

    def test_explicit_half_width_is_stored_separately(self):
        text = (
            "CABLE OPERATIONS ALONG LINE 10-00.0N 060-00.0E TO 10-30.0N 060-30.0E. "
            "WIDE BERTH OF 2 NM ON EACH SIDE."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(report["feature_type"], "CORRIDOR")
        self.assertEqual(report["corridor_half_width_nm"], 2.0)
        self.assertNotIn("corridor_width_semantics_ambiguous", report["flags"])

    def test_explicit_statute_miles_convert_to_nautical_miles(self):
        text = (
            "CABLE OPERATIONS ALONG LINE 10-00.0N 060-00.0E TO 10-30.0N 060-30.0E. "
            "WIDE BERTH OF 2 STATUTE MILES."
        )
        self.assertEqual(parse_corridor_clearance(text), round(2 * 0.868976, 3))

    def test_route_without_berth_is_line(self):
        text = "VESSEL TRANSIT ALONG LINE 10-00.0N 060-00.0E TO 10-30.0N 060-30.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "LineString")
        self.assertEqual(report["feature_type"], "LINE")
        self.assertEqual(report["buffer_nm"], 0.0)


class TestRelocations(unittest.TestCase):
    """Task 3: Relocation notices, position ordering, and dual-point FeatureCollection."""

    def test_relocated_from_to_wording(self):
        text = "LIGHT BUOY NO 4 RELOCATED FROM 12-30.0N 045-15.0E TO 12-35.0N 045-20.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        # Primary coordinates strictly pinned to NEW position
        self.assertEqual(lat, 12.583333)
        self.assertEqual(lon, 45.333333)
        self.assertEqual(report["basis"], "explicit:relocation")
        self.assertIn("has_relocated_station", report["flags"])
        self.assertEqual(spatial["type"], "FeatureCollection")
        self.assertEqual(len(spatial["features"]), 2)

        new_feat = spatial["features"][0]
        former_feat = spatial["features"][1]

        self.assertEqual(new_feat["properties"]["zone_label"], "New Established Position")
        self.assertEqual(new_feat["geometry"]["coordinates"], [45.333333, 12.583333])
        self.assertTrue(new_feat["properties"].get("is_active"))

        self.assertEqual(former_feat["properties"]["zone_label"], "Former Position (Relocated)")
        self.assertEqual(former_feat["geometry"]["coordinates"], [45.25, 12.5])
        self.assertTrue(former_feat["properties"].get("is_ghost"))
        self.assertEqual(former_feat["properties"].get("relocated_to"), [45.333333, 12.583333])

    def test_reversed_text_order_established_discontinued(self):
        # NEW position mentioned first in text, FORMER mentioned second
        text = (
            "LIGHT BUOY NO 8 ESTABLISHED IN NEW POSITION 15-10.0N 055-10.0E. "
            "FORMER POSITION 15-00.0N 055-00.0E DISCONTINUED."
        )
        pos = _extract_relocation_positions(text)
        self.assertIsNotNone(pos)
        former_pt, new_pt = pos
        self.assertEqual(new_pt, [55.166667, 15.166667])
        self.assertEqual(former_pt, [55.0, 15.0])

        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(lat, 15.166667)
        self.assertEqual(lon, 55.166667)

    def test_ambiguous_relocation_never_falls_back_to_point_or_centroid(self):
        cases = (
            "LIGHT BUOY RELOCATED FROM 12-30.0N 045-15.0E.",
            "LIGHT BUOY RELOCATED FROM 12-30.0N 045-15.0E TO POSITION UNKNOWN.",
            "LIGHT BUOY RELOCATED FROM 12-30.0N 045-15.0E AND 12-31.0N 045-16.0E TO 12-35.0N 045-20.0E.",
        )
        for text in cases:
            with self.subTest(text=text):
                coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
                self.assertIsNone(spatial)
                self.assertIsNone(lat)
                self.assertIsNone(lon)
                self.assertIn("AMBIGUOUS_RELOCATION", report["flags"])
                self.assertEqual(report["data_quality"], "AMBIGUOUS")

    def test_relocation_child_payloads_do_not_claim_ghost_columns(self):
        text = "LIGHT BUOY NO 4 RELOCATED FROM 12-30.0N 045-15.0E TO 12-35.0N 045-20.0E."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        record = {
            "title": "LIGHT BUOY 4",
            "spatial": spatial,
            "latitude": lat,
            "longitude": lon,
        }
        payloads = build_geometry_payloads(record)
        self.assertEqual(len(payloads), 2)
        # Database rows must be valid POINT rows with clean zone_labels
        self.assertEqual(payloads[0]["zone_label"], "New Established Position")
        self.assertEqual(payloads[0]["feature_type"], "POINT")
        self.assertEqual(payloads[1]["zone_label"], "Former Position (Relocated)")
        self.assertEqual(payloads[1]["feature_type"], "POINT")
        # Ensure ghost attributes are not top-level DB columns on the child payload
        self.assertNotIn("is_ghost", payloads[1])
        self.assertNotIn("relocated_to", payloads[1])


class TestBoundingBoxes(unittest.TestCase):
    """Task 4: Dual-axis range boxes and two-corner bounding boxes."""

    def test_axis_tokens_bounding_box(self):
        text = (
            "NAVAREA VIII 120/26\n"
            "AREA BOUNDED WITHIN 14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E\n"
            "HYDROGRAPHIC SURVEY IN PROGRESS."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "BOUNDING_BOX")
        self.assertEqual(report["basis"], "keyword:bounding_box")

    def test_navarea_xi_explicit_bounded_area_crossing_antimeridian_is_split(self):
        raw = (
            "NO.26-0504       Date:2026/11/09 12 UTC\n"
            "NORTH PACIFIC.\n"
            "SPACE DEBRIS.\n"
            "0130Z TO 0501Z DAILY 14 TO 20 NOV.\n"
            "AREA BOUNDED BY\n"
            "23-56N 144-37E 26-09N 151-14E\n"
            "27-46N 156-36E 29-28N 165-10E\n"
            "30-43N 172-44E 31-10N 178-00E\n"
            "31-16N 175-01W 31-21N 171-27W\n"
            "30-33N 161-15W 29-37N 155-40W\n"
            "28-49N 151-35W 26-53N 145-26W\n"
            "26-50N 145-28W 24-03N 154-32W\n"
            "23-46N 156-11W 24-52N 159-19W\n"
            "27-38N 167-49W 29-23N 175-00W\n"
            "29-35N 176-36W 29-37N 179-58W\n"
            "29-28N 176-13E 29-11N 170-10E\n"
            "28-12N 163-45E 26-39N 156-17E\n"
            "23-27N 144-49E.\n"
            "CANCEL THIS MSG 200601Z NOV."
        )

        _raw_message, warning, spatial = parse_navarea_xi_warning(
            raw, "NO.26-0504"
        )

        self.assertEqual(warning["canonical_id"], "NAVAREA XI 0504/26")
        self.assertEqual(spatial["type"], "MultiPolygon")
        self.assertEqual(warning["data_quality"], "EXPLICIT")
        self.assertNotIn("COORD_COUNT_MISMATCH", warning["qa_flags"])
        self.assertEqual(len(spatial["coordinates"]), 2)

        output_points = []
        for polygon in spatial["coordinates"]:
            self.assertEqual(len(polygon), 1)
            ring = polygon[0]
            self.assertEqual(ring[0], ring[-1])
            self.assertTrue(ring_is_simple(ring))
            self.assertTrue(all(
                abs(a[0] - b[0]) <= 180.0
                for a, b in zip(ring, ring[1:])
            ))
            output_points.extend(ring)

        # Compare planar area after unwrapping both output pieces into
        # the same longitude domain as the original source ring.
        def signed_area(ring):
            return sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(ring, ring[1:])
            ) / 2.0

        unwrapped_source = [source_points[0][:]]
        for lon, lat in source_points[1:]:
            while lon - unwrapped_source[-1][0] > 180.0:
                lon -= 360.0
            while lon - unwrapped_source[-1][0] < -180.0:
                lon += 360.0
            unwrapped_source.append([lon, lat])
        unwrapped_source.append(unwrapped_source[0][:])

        output_area = 0.0
        for polygon in spatial["coordinates"]:
            output_ring = [point[:] for point in polygon[0]]
            if max(point[0] for point in output_ring) < 0:
                output_ring = [[lon + 360.0, lat] for lon, lat in output_ring]
            output_area += abs(signed_area(output_ring))
        self.assertAlmostEqual(
            abs(signed_area(unwrapped_source)), output_area, places=3
        )

        # Every source vertex survives normalization; only Date Line
        # intersection vertices may be added.
        source_points = [
            [144.616667, 23.933333], [151.233333, 26.15],
            [156.6, 27.766667], [165.166667, 29.466667],
            [172.733333, 30.716667], [178.0, 31.166667],
            [-175.016667, 31.266667], [-171.45, 31.35],
            [-161.25, 30.55], [-155.666667, 29.616667],
            [-151.583333, 28.816667], [-145.433333, 26.883333],
            [-145.466667, 26.833333], [-154.533333, 24.05],
            [-156.183333, 23.766667], [-159.316667, 24.866667],
            [-167.816667, 27.633333], [-175.0, 29.383333],
            [-176.6, 29.583333], [-179.966667, 29.616667],
            [176.216667, 29.466667], [170.166667, 29.183333],
            [163.75, 28.2], [156.283333, 26.65],
            [144.816667, 23.45],
        ]
        for source_point in source_points:
            self.assertTrue(
                any(
                    abs(point[0] - source_point[0]) < 0.00001
                    and abs(point[1] - source_point[1]) < 0.00001
                    for point in output_points
                ),
                f"Source vertex was lost: {source_point}",
            )

        payloads = build_geometry_payloads({
            "title": warning["title"],
            "spatial": spatial,
        })
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["feature_type"], "POLYGON")
        self.assertEqual(payloads[0]["geojson"]["type"], "MultiPolygon")

    def test_antimeridian_split_supports_both_directions_and_winding(self):
        eastern_crossing = [
            [170.0, 10.0], [-170.0, 10.0],
            [-170.0, 20.0], [170.0, 20.0], [170.0, 10.0],
        ]
        western_crossing = [
            [-170.0, 10.0], [170.0, 10.0],
            [170.0, 20.0], [-170.0, 20.0], [-170.0, 10.0],
        ]

        for ring in (
            eastern_crossing,
            list(reversed(eastern_crossing)),
            western_crossing,
            list(reversed(western_crossing)),
        ):
            with self.subTest(ring=ring):
                geometry = split_antimeridian_ring(ring)
                self.assertIsNotNone(geometry)
                self.assertEqual(geometry["type"], "MultiPolygon")
                self.assertEqual(len(geometry["coordinates"]), 2)
                for polygon in geometry["coordinates"]:
                    output_ring = polygon[0]
                    self.assertEqual(output_ring[0], output_ring[-1])
                    self.assertTrue(ring_is_simple(output_ring))
                    self.assertTrue(all(
                        abs(a[0] - b[0]) <= 180.0
                        for a, b in zip(output_ring, output_ring[1:])
                    ))

    def test_non_crossing_ring_is_not_split(self):
        ordinary_ring = [
            [10.0, 10.0], [20.0, 10.0],
            [20.0, 20.0], [10.0, 20.0], [10.0, 10.0],
        ]
        self.assertIsNone(split_antimeridian_ring(ordinary_ring))

    def test_unsupported_multiple_antimeridian_crossings_fail_closed(self):
        text = (
            "AREA BOUNDED BY "
            "10-00.0N 170-00.0E 11-00.0N 170-00.0W "
            "12-00.0N 170-00.0E 13-00.0N 170-00.0W "
            "14-00.0N 170-00.0E 15-00.0N 170-00.0W "
            "16-00.0N 170-00.0E."
        )
        _coords, _lat, _lon, spatial, report = parse_coordinates_detailed(text)
        self.assertIsNone(spatial)
        self.assertIn("ANTIMERIDIAN_SPLIT_FAILED", report["flags"])
        self.assertEqual(report["data_quality"], "AMBIGUOUS")

    def test_axis_range_crossing_antimeridian_is_split(self):
        text = (
            "AREA BOUNDED WITHIN 10-00.0N TO 11-00.0N AND "
            "179-00.0E TO 179-00.0W. HYDROGRAPHIC SURVEY."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "MultiPolygon")
        self.assertEqual(report["feature_type"], "BOUNDING_BOX")
        self.assertEqual(len(spatial["coordinates"]), 2)
        self.assertEqual(lon, -180.0)
        self.assertTrue(all(
            abs(a[0] - b[0]) <= 180.0
            for polygon in spatial["coordinates"]
            for ring in polygon
            for a, b in zip(ring, ring[1:])
        ))
        payloads = build_geometry_payloads({"title": "Dateline", "spatial": {
            "type": "Feature", "properties": {"feature_type": "BOUNDING_BOX"},
            "geometry": spatial,
        }})
        self.assertEqual(payloads[0]["feature_type"], "BOUNDING_BOX")

    def test_two_corner_antimeridian_box_is_split_and_centered(self):
        text = (
            "AREA BOUNDED WITHIN 10-00.0N 179-00.0E AND "
            "11-00.0N 179-00.0W. HYDROGRAPHIC SURVEY."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "MultiPolygon")
        self.assertEqual(report["feature_type"], "BOUNDING_BOX")
        self.assertEqual(lon, -180.0)
        self.assertEqual(len(spatial["coordinates"]), 2)

    def test_two_corner_bounding_box_archetype(self):
        text = (
            "AREA BOUNDED WITHIN\n"
            "10-00.0N 060-00.0E AND 10-10.0N 060-10.0E.\n"
            "MILITARY EXERCISE."
        )
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["feature_type"], "BOUNDING_BOX")


class TestEndToEndPipeline(unittest.TestCase):
    """Task 5: End-to-end parser -> Feature properties -> geometry payloads pipeline."""

    def test_universal_parser_preserves_corridor_feature_type(self):
        bulletin = (
            "NAVAREA II 101/26\n"
            "CANARIAS.\n"
            "1. CABLE OPERATIONS ALONG LINE JOINING 28-30.0N 015-00.0W AND 28-35.0N 015-10.0W.\n"
            "WIDE BERTH OF 1.5 NM REQUESTED.\n"
            "2. CANCEL THIS MSG 012000 UTC NOV 26."
        )
        parsed = parse_bulletin_text(bulletin, "ii")
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        warn = parsed["nav_warnings"][0]
        self.assertEqual(warn["spatial"]["type"], "FeatureCollection")
        feat = warn["spatial"]["features"][0]
        self.assertEqual(feat["geometry"]["type"], "LineString")
        self.assertEqual(feat["properties"]["feature_type"], "CORRIDOR")
        self.assertEqual(feat["properties"]["buffer_nm"], 0.0)
        self.assertEqual(feat["properties"]["corridor_clearance_nm"], 1.5)
        self.assertNotIn("corridor_half_width_nm", feat["properties"])
        self.assertIn("corridor_width_semantics_ambiguous", warn["qa_flags"])

        payloads = build_geometry_payloads(warn)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["feature_type"], "CORRIDOR")
        self.assertEqual(payloads[0]["buffer_nm"], 0.0)
        self.assertEqual(payloads[0]["corridor_clearance_nm"], 1.5)
        self.assertNotIn("corridor_half_width_nm", payloads[0])

    def test_universal_parser_preserves_subarea_sweeps_without_cross_contamination(self):
        bulletin = (
            "NAVAREA VII 0500/26\n"
            "SOUTH AFRICA, SOUTH COAST.\n"
            "GUNNERY FIRING EXERCISES:\n"
            "1. WITHIN 10 NM OF 34-00.0S 020-00.0E BETWEEN 090 AND 180 DEGREES.\n"
            "2. IN AREA BOUNDED BY 35-00.0S 021-00.0E, 35-10.0S 021-00.0E, 35-10.0S 021-10.0E, 35-00.0S 021-10.0E.\n"
            "3. CANCEL THIS MSG 251200 UTC OCT 26."
        )
        parsed = parse_bulletin_text(bulletin, "vii")
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        warn = parsed["nav_warnings"][0]
        features = warn["spatial"]["features"]
        self.assertEqual(len(features), 2)

        # Feature 1 carries sweep metadata
        feat_a = features[0]
        self.assertEqual(feat_a["properties"]["sub_area"], "1")
        self.assertEqual(feat_a["properties"]["feature_type"], "SWEEP_ARC")
        self.assertEqual(feat_a["properties"]["sweep_radius_nm"], 10.0)

        # Feature 2 does NOT inherit sweep metadata from Feature 1
        feat_b = features[1]
        self.assertEqual(feat_b["properties"]["sub_area"], "2")
        self.assertEqual(feat_b["properties"]["feature_type"], "POLYGON")
        self.assertNotIn("sweep_radius_nm", feat_b["properties"])

        payloads = build_geometry_payloads(warn)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["feature_type"], "SWEEP_ARC")
        self.assertEqual(payloads[0]["sweep_radius_nm"], 10.0)
        self.assertEqual(payloads[1]["feature_type"], "POLYGON")
        self.assertNotIn("sweep_radius_nm", payloads[1])

    def test_metadata_migration_preserves_lifecycle_safe_replacement(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261112_geometry_metadata_persistence.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("corridor_half_width_nm", migration)
        self.assertIn("sweep_start_azimuth", migration)
        self.assertIn("sweep_end_azimuth", migration)
        self.assertIn("sweep_radius_nm", migration)
        self.assertLess(
            migration.index("INSERT INTO public.nav_warning_geometries"),
            migration.index("DELETE FROM public.nav_warning_geometries"),
        )
        self.assertIn("ELSIF v_existing > 0 THEN", migration)

    def test_type_validation_mismatch_fallback(self):
        # If record incorrectly claims SWEEP_ARC for a LineString, it must safely fall back
        record = {
            "title": "CORRUPTED RECORD",
            "spatial": {
                "type": "LineString",
                "coordinates": [[10.0, 10.0], [10.5, 10.5]],
                "properties": {
                    "feature_type": "SWEEP_ARC"
                }
            }
        }
        payloads = build_geometry_payloads(record)
        self.assertEqual(len(payloads), 1)
        # Safely falls back to LINE (never emits SWEEP_ARC on LineString)
        self.assertEqual(payloads[0]["feature_type"], "LINE")


if __name__ == "__main__":
    unittest.main()
