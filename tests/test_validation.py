#!/usr/bin/env python3
"""
tests/test_validation.py — Unit Tests for Validation Framework
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.exceptions import ValidationError
from shared.validation import (
    validate_coordinate_token,
    validate_warning_id,
    validate_raw_text,
    validate_lat_lon,
    validate_nav_warning_dict,
    validate_public_inputs,
)


class TestValidationFramework(unittest.TestCase):

    def test_validate_coordinate_token_valid(self):
        self.assertEqual(validate_coordinate_token("21-26.90N"), "21-26.90N")
        self.assertEqual(validate_coordinate_token("  042-08.00E  "), "042-08.00E")

    def test_validate_coordinate_token_invalid_types_and_bounds(self):
        with self.assertRaises(ValidationError):
            validate_coordinate_token(None)
        with self.assertRaises(ValidationError):
            validate_coordinate_token("")
        with self.assertRaises(ValidationError):
            validate_coordinate_token("   ")
        with self.assertRaises(ValidationError):
            validate_coordinate_token("X" * 105)  # Exceeds max length

    def test_validate_warning_id_valid(self):
        self.assertEqual(validate_warning_id("BALTIC 001/26"), "BALTIC 001/26")
        self.assertEqual(validate_warning_id("NAVAREA I 123/25"), "NAVAREA I 123/25")
        self.assertEqual(validate_warning_id("SWEDISH 168/26 [Skagerrak]"), "SWEDISH 168/26 [Skagerrak]")

    def test_validate_warning_id_invalid(self):
        with self.assertRaises(ValidationError):
            validate_warning_id(None)
        with self.assertRaises(ValidationError):
            validate_warning_id("")
        with self.assertRaises(ValidationError):
            validate_warning_id("BAD$CHAR@ID!")

    def test_validate_lat_lon_bounds(self):
        self.assertTrue(validate_lat_lon(58.17, 11.22))
        self.assertTrue(validate_lat_lon(-90.0, -180.0))
        self.assertTrue(validate_lat_lon(90.0, 180.0))
        self.assertFalse(validate_lat_lon(90.1, 0.0))
        self.assertFalse(validate_lat_lon(0.0, 180.5))
        self.assertFalse(validate_lat_lon(None, 10.0))
        self.assertFalse(validate_lat_lon("not-a-number", 10.0))

    def test_validate_nav_warning_dict(self):
        valid_rec = {
            "warning_id": "BALTIC 100/26",
            "latitude": 55.5,
            "longitude": 14.2,
            "status": "active",
            "triage_tier": "A",
        }
        res = validate_nav_warning_dict(valid_rec)
        self.assertEqual(res["warning_id"], "BALTIC 100/26")

        # Invalid latitude out of range
        invalid_rec = {
            "warning_id": "BALTIC 101/26",
            "latitude": 95.0,
            "longitude": 14.2,
            "status": "active",
        }
        with self.assertRaises(ValidationError):
            validate_nav_warning_dict(invalid_rec)

    def test_validate_public_inputs_decorator(self):
        @validate_public_inputs
        def sample_func(a, b):
            return f"{a}:{b}"

        self.assertEqual(sample_func("hello", "world"), "hello:world")
        with self.assertRaises(ValidationError):
            sample_func(None, "world")


if __name__ == "__main__":
    unittest.main()
