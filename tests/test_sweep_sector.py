import unittest

from shared.models import build_geometry_payloads
from shared.utils import parse_coordinates, parse_coordinates_detailed
from scripts.navarea_universal_parser import parse_bulletin_text


# Live NAVAREA II 358/26 text (firing exercise off the Canary Islands;
# recovered from the coordinator's archived bulletin, Oct 2026).
II_358_26 = (
    "NAVAREA II 358/26\n"
    "CANARIAS. SPECIAL OPERATIONS: FIRING EXERCISE. "
    "VALID FROM 20 OCT 2026 00:00 UTC TO 20 OCT 2026 23:59 UTC. "
    "WITHIN 20 MILES OF: CHARLIE 26-50.00N 014-00.00W "
    "BETWEEN 270 AND 360 DEGREES. "
    "NAVIGATE WITH CAUTION. RESTRICTED AREA."
)


class TestSweepSector(unittest.TestCase):
    def test_sector_built_from_sweep_wording(self):
        coords, lat, lon, spatial, report = parse_coordinates_detailed(
            II_358_26)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(report["basis"], "keyword:sweep_sector")
        self.assertEqual(report["data_quality"], "EXPLICIT")
        self.assertEqual(report["sweep_radius_nm"], 20.0)
        self.assertEqual(report["sweep_start_azimuth"], 270.0)
        self.assertEqual(report["sweep_end_azimuth"], 360.0)
        ring = spatial["coordinates"][0]
        # centre -> 10 arc points (90 deg span, <=10 deg steps) -> closure
        self.assertEqual(len(ring), 12)
        self.assertEqual(ring[0], [-14.0, round(26 + 50.0 / 60, 6)])
        self.assertEqual(ring[-1], ring[0])
        # first arc vertex: due west of the centre at 20 NM
        self.assertAlmostEqual(ring[1][0], -14.373748, places=3)
        self.assertAlmostEqual(ring[1][1], 26.8328, places=3)
        # last arc vertex: due north of the centre at 20 NM
        self.assertAlmostEqual(ring[-2][0], -14.0, places=3)
        self.assertAlmostEqual(ring[-2][1], 27.16671, places=4)

    def test_wraparound_bearings(self):
        text = ("FIRING EXERCISE WITHIN 10 MILES OF TARGET "
                "31-00.00N 015-00.00W BETWEEN 350 AND 10 DEGREES.")
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Polygon")
        # source-stated bearings kept verbatim; the fan wraps north
        self.assertEqual(report["sweep_start_azimuth"], 350.0)
        self.assertEqual(report["sweep_end_azimuth"], 10.0)
        self.assertEqual(report["sweep_radius_nm"], 10.0)
        # 20 deg span -> steps = max(2, 2) = 2 -> centre + 3 arc + closure
        self.assertEqual(len(spatial["coordinates"][0]), 5)

    def test_circle_without_bearings_stays_point(self):
        text = "DANGEROUS WRECK WITHIN 5 MILES OF POSITION 34-00.00S 150-00.00E"
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Point")
        self.assertNotIn("sweep_radius_nm", report)

    def test_bearings_without_radius_phrase_stay_point(self):
        text = "FIRING EXERCISE 34-00.00S 150-00.00E BETWEEN 270 AND 360 DEGREES."
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertEqual(spatial["type"], "Point")

    def test_two_positions_never_a_sector(self):
        text = ("FIRING EXERCISE WITHIN 20 MILES OF 26-50.00N 014-00.00W "
                "AND 26-55.00N 014-05.00W BETWEEN 270 AND 360 DEGREES.")
        coords, lat, lon, spatial, report = parse_coordinates_detailed(text)
        self.assertNotEqual(spatial["type"], "Polygon")
        self.assertNotIn("sweep_radius_nm", report)

    def test_pipeline_emits_sweep_properties(self):
        parsed = parse_bulletin_text(II_358_26, "ii")
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        warn = parsed["nav_warnings"][0]
        self.assertEqual(warn["canonical_id"], "NAVAREA II 358/26")
        feature = warn["spatial"]["features"][0]
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        props = feature["properties"]
        self.assertEqual(props["sweep_radius_nm"], 20.0)
        self.assertEqual(props["sweep_start_azimuth"], 270.0)
        self.assertEqual(props["sweep_end_azimuth"], 360.0)

    def test_geometry_payload_carries_sweep_columns(self):
        parsed = parse_bulletin_text(II_358_26, "ii")
        warn = parsed["nav_warnings"][0]
        payloads = build_geometry_payloads(warn)
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["feature_type"], "POLYGON")
        self.assertEqual(payload["sweep_radius_nm"], 20.0)
        self.assertEqual(payload["sweep_start_azimuth"], 270.0)
        self.assertEqual(payload["sweep_end_azimuth"], 360.0)


if __name__ == "__main__":
    unittest.main()
