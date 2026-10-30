import unittest

from shared.utils import parse_coordinates, parse_coordinates_detailed


# Live AMSA RCC publication wording (fetched 2026-10-30,
# operations.amsa.gov.au, current at 301744 UTC Oct 26).
AUSCOAST_330_26 = (
    "AUSCOAST WARNING 330/26\n"
    "UNCREWED VESSEL REACH REMOTE 2 / VKCC / 503189810 CONDUCTING SUBSEA "
    "SURVEY OPERATIONS IN AN AREA BOUNDED BY 34-24.10 S TO 34-53.60 S "
    "AND 114-56.40 E TO 115-39.70 E 2.0NM CLEARANCE REQUESTED."
)
AUSCOAST_270_26 = (
    "AUSCOAST WARNING 270/26\n"
    "SPECIAL PURPOSE VESSEL VE CONSTRUCTOR / H9YT / 373335000 CONDUCTING "
    "UNDERWATER OPERATIONS IN AN AREA BOUNDED BY 19-12.00 S TO 19-21.00 S "
    "AND 116-30.00 E TO 116-50.00 E 0.5NM CLEARANCE REQUESTED."
)
# NAVAREA VIII 1102/26 shape: the pre-existing WITHIN format.
VIII_1102_26 = (
    "AREA BOUNDED WITHIN 14-47.2N TO 14-50.9N AND "
    "074-02.8E TO 074-08.15E"
)
# NAVAREA II 362/26: 'BOUNDED BY' with a corner ENUMERATION — its
# coordinate PAIRS are extracted upstream, so it must never be
# reinterpreted as a two-corner range box.
II_362_26 = (
    "WORKS: OPERATION ON CABLE BY MV MAASVLIET IN AREA BOUNDED BY: "
    "38-05.83N 009-50.14W 38-05.83N 006-04.87W 33-47.24N 006-04.87W "
    "33-47.24N 009-50.14W"
)


class TestAuscoastRangeBox(unittest.TestCase):
    def test_auscoast_range_box_builds_rectangle(self):
        coords, lat, lon, spatial = parse_coordinates(AUSCOAST_330_26)
        self.assertEqual(spatial["type"], "Polygon")
        ring = spatial["coordinates"][0]
        self.assertEqual(len(ring), 5)
        self.assertEqual(ring[0][0], 114.94)          # lon W edge
        self.assertAlmostEqual(ring[0][1], -34.401667, places=6)  # lat S edge
        self.assertAlmostEqual(ring[2][0], 115.661667, places=6)  # lon E edge
        self.assertAlmostEqual(ring[2][1], -34.893333, places=6)  # lat N edge
        self.assertEqual(ring[4], ring[0])           # closed ring
        self.assertAlmostEqual(lat, -34.6475, places=6)
        self.assertAlmostEqual(lon, 115.300833, places=5)
        # Basis is the keyword bbox rule, EXPLICIT quality.
        _, _, _, _, report = parse_coordinates_detailed(AUSCOAST_330_26)
        self.assertEqual(report["basis"], "keyword:bounding_box")
        self.assertEqual(report["data_quality"], "EXPLICIT")

    def test_auscoast_range_box_second_area(self):
        coords, lat, lon, spatial = parse_coordinates(AUSCOAST_270_26)
        self.assertEqual(spatial["type"], "Polygon")
        ring = spatial["coordinates"][0]
        self.assertEqual(len(ring), 5)
        self.assertAlmostEqual(ring[0][1], -19.2, places=6)
        self.assertAlmostEqual(ring[2][0], 116.833333, places=6)
        self.assertEqual(ring[4], ring[0])

    def test_viii_bounded_within_unchanged(self):
        coords, lat, lon, spatial = parse_coordinates(VIII_1102_26)
        self.assertEqual(spatial["type"], "Polygon")
        ring = spatial["coordinates"][0]
        self.assertEqual(len(ring), 5)
        self.assertAlmostEqual(ring[0][0], 74.046667, places=6)
        self.assertAlmostEqual(ring[0][1], 14.786667, places=6)
        self.assertAlmostEqual(ring[2][0], 74.135833, places=6)
        self.assertAlmostEqual(ring[2][1], 14.848333, places=6)

    def test_bounded_by_corner_enumeration_not_a_range_box(self):
        # Corner enumerations keep their pair-extraction polygon shape:
        # four distinct corners, NOT the two-corner rectangle ring.
        coords, lat, lon, spatial = parse_coordinates(II_362_26)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertEqual(len(coords), 4)
        # First pair is a real corner (38N 009-50W), not a rect edge.
        self.assertAlmostEqual(lat, 35.873899, places=5)

    def test_missing_lon_range_fails_closed(self):
        text = ("IN AN AREA BOUNDED BY 34-24.10 S TO 34-53.60 S "
                "AND 114-56.40 E 2.0NM CLEARANCE REQUESTED.")
        coords, lat, lon, spatial = parse_coordinates(text)
        self.assertIsNone(spatial)

    def test_three_lat_range_fails_closed(self):
        text = ("IN AN AREA BOUNDED BY 34-24.10 S TO 34-53.60 S TO "
                "34-60.00 S AND 114-56.40 E TO 115-39.70 E")
        coords, lat, lon, spatial = parse_coordinates(text)
        # A lat-range regex only spans TWO tokens; the third stays an
        # unpaired axis value -> no clean two-corner range -> fail closed.
        self.assertIsNone(spatial)


if __name__ == "__main__":
    unittest.main()
