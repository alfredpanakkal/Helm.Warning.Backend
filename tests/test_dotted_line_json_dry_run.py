#!/usr/bin/env python3
"""Safety tests for the offline JSON geometry dry-run."""

import builtins
import os
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts import dry_run_six_warning_geometry as dry_run


class TestOfflineGeometryDryRun(unittest.TestCase):

    def test_json_dry_run_compares_geometry_without_network_or_database(self):
        inputs = [{
            "canonical_id": "NAVAREA III 0169/26",
            "raw_text": (
                "NAVAREA III - 0169/26\n"
                "FOLLOWING THE DOTTED LINE:\n"
                "A\n"
                "42 11.718N 009 59.778E\n"
                "42 12.000N 010 00.000E\n"
                "B\n"
                "42 13.000N 010 01.000E\n"
                "42 14.000N 010 02.000E"
            ),
        }]
        persisted = [
            {
                "canonical_id": "NAVAREA III 0169/26",
                "geojson": {
                    "type": "LineString",
                    "coordinates": [
                        [round(9 + 59.778 / 60, 6), round(42 + 11.718 / 60, 6)],
                        [10.0, 42.2],
                    ],
                },
            },
            {
                "canonical_id": "NAVAREA III 0169/26",
                "geojson": {
                    "type": "LineString",
                    "coordinates": [
                        [round(10 + 1 / 60, 6), round(42 + 13 / 60, 6)],
                        [round(10 + 2 / 60, 6), round(42 + 14 / 60, 6)],
                    ],
                },
            },
        ]
        original_import = builtins.__import__

        def reject_network_or_database_import(name, *args, **kwargs):
            root = name.split(".", 1)[0]
            if root in {"supabase", "requests", "httpx", "psycopg", "asyncpg"}:
                raise AssertionError(f"forbidden dependency imported: {name}")
            return original_import(name, *args, **kwargs)

        with (
            patch("socket.socket", side_effect=AssertionError("network socket used")),
            patch("socket.create_connection",
                  side_effect=AssertionError("network connection used")),
            patch("builtins.__import__", side_effect=reject_network_or_database_import),
        ):
            report = dry_run.run_json_inputs(inputs, persisted)

        self.assertEqual(report["input_count"], 1)
        result = report["results"][0]
        self.assertEqual(result["geometry_type"], ["LineString", "LineString"])
        self.assertEqual(result["coordinate_count"], 4)
        comparison = result["persisted_comparison"]
        self.assertTrue(comparison["geometry_count_equal"])
        self.assertEqual(comparison["parsed_geometry_count"], 2)
        self.assertTrue(all(item["exact_coordinate_equality"] for item in comparison["comparisons"]))
        self.assertEqual(
            comparison["comparisons"][0]["parsed_first_coordinate"],
            comparison["comparisons"][0]["persisted_first_coordinate"],
        )


if __name__ == "__main__":
    unittest.main()
