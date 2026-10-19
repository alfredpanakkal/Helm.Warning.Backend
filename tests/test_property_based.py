#!/usr/bin/env python3
"""
tests/test_property_based.py — Property-Based and Fuzz Testing for Coordinate Processing
Generates hundreds of coordinate variations and verifies invariants (never crash, range bounds, NaN handling).
"""

import unittest
import math
import random
import string
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils import (
    repair_coordinate_token,
    convert_to_decimal,
    parse_coordinates,
    parse_coordinate_with_provenance,
)
from shared.models import CoordinateProvenance, DataQuality


class TestPropertyBasedCoordinates(unittest.TestCase):

    def test_invariant_repair_coordinate_token_never_crashes(self):
        """Fuzz test repair_coordinate_token on 500 randomized tokens."""
        for _ in range(500):
            length = random.randint(0, 50)
            token = "".join(random.choices(string.ascii_letters + string.digits + " -.,/:;'\"", k=length))
            try:
                repaired, rules = repair_coordinate_token(token)
                self.assertIsInstance(repaired, str)
                self.assertIsInstance(rules, list)
            except Exception as e:
                self.fail(f"repair_coordinate_token crashed on token {token!r}: {e}")

    def test_invariant_convert_to_decimal_bounded_or_nan(self):
        """Verify convert_to_decimal always yields a valid bounded float or math.nan."""
        for _ in range(500):
            deg = random.choice([str(random.randint(-150, 150)), "nan", "abc", 45, 91, 55.5])
            mins = random.choice([str(random.uniform(-10, 80)), "60.0", "59.999", -1])
            direction = random.choice(["N", "S", "E", "W", "X", "", None])

            val = convert_to_decimal(deg, mins, direction)
            if not math.isnan(val):
                if direction in ("N", "S"):
                    self.assertTrue(-90.0 <= val <= 90.0, f"Latitude {val} out of bounds")
                elif direction in ("E", "W"):
                    self.assertTrue(-180.0 <= val <= 180.0, f"Longitude {val} out of bounds")

    def test_invariant_parse_coordinates_never_crashes(self):
        """Fuzz test parse_coordinates with 300 malformed text blocks."""
        for _ in range(300):
            chars = random.choices(string.printable, k=random.randint(0, 150))
            text = "".join(chars)
            try:
                coords, lat, lon, spatial = parse_coordinates(text)
                self.assertIsInstance(coords, list)
                if lat is not None:
                    self.assertTrue(-90.0 <= lat <= 90.0)
                if lon is not None:
                    self.assertTrue(-180.0 <= lon <= 180.0)
            except Exception as e:
                self.fail(f"parse_coordinates crashed on input {text!r}: {e}")

    def test_invariant_provenance_safe(self):
        """parse_coordinate_with_provenance should never raise unhandled exceptions."""
        for _ in range(200):
            token = "".join(random.choices(string.ascii_uppercase + string.digits + "-., ", k=random.randint(1, 25)))
            try:
                prov = parse_coordinate_with_provenance("SAMPLE TEXT " + token, token)
                self.assertIsInstance(prov, CoordinateProvenance)
                self.assertIn(prov.quality, (DataQuality.EXPLICIT, DataQuality.INFERRED, DataQuality.AMBIGUOUS, DataQuality.INVALID))
            except Exception as e:
                self.fail(f"parse_coordinate_with_provenance crashed on token {token!r}: {e}")


if __name__ == "__main__":
    unittest.main()
