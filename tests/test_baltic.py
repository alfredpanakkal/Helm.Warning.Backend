#!/usr/bin/env python3
"""test_baltic.py — Unit Tests for NAVAREA Baltic Pipeline & Parser"""
import sys
import os
import json
import tempfile
import unittest

# Ensure repo root is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.baltic_parser import parse_warning, main as parse_main
from scripts.baltic_sync import validate_raw_message, validate_nav_warning, sync_to_supabase
from shared.utils import compute_differential, classify_hazard, parse_coordinates


class TestBalticModuleImports(unittest.TestCase):
    """Verifies that all Baltic pipeline modules are importable from repo root."""

    def test_import_scripts_run_baltic(self):
        import scripts.run_baltic
        self.assertTrue(callable(scripts.run_baltic.main))

    def test_import_baltic_pipeline_modules(self):
        import scripts.baltic_scraper
        import scripts.baltic_parser
        import scripts.baltic_sync
        self.assertTrue(callable(scripts.baltic_scraper.scrape_baltic_warnings))
        self.assertTrue(callable(scripts.baltic_parser.parse_warning))
        self.assertTrue(callable(scripts.baltic_sync.sync_to_supabase))


class TestBalticParser(unittest.TestCase):
    def test_sample_1_skagerrak_detonations_polygon(self):
        header = "SWEDISH NAV WARN 168/26 [Skagerrak]"
        raw = """080056 UTC OCT
SKAGERRAK. LYSEKIL. BONDEN
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS
09 OCT 0600 LT – 14 OCT 2000 LT
PSN:
58-10.2N 011-13.3E
58-13.3N 011-13.3E
58-13.3N 011-17.4E
58-10.2N 011-13.3E
500 MTR CLEARANCE FROM THE AREA IS REQUESTED."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 168/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080056 UTC OCT 2026")
        self.assertIsNotNone(spatial)
        self.assertEqual(spatial["type"], "Polygon")
        self.assertAlmostEqual(nav_warn["latitude"], 58.195834, places=4)
        self.assertAlmostEqual(nav_warn["longitude"], 11.238750, places=4)

    def test_sample_2_kattegat_point(self):
        header = "SWEDISH NAV WARN 167/26 [Kattegat]"
        raw = """080035 UTC OCT
KATTEGAT. MARSTRAND. STORA PÖLSAN.
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS.
09 OCT 0600 LT - 14 OCT 2000 LT.
PSN: 57-47.0N 011-27.9E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "SWEDISH 167/26")
        self.assertEqual(nav_warn["category"], "military")
        self.assertEqual(nav_warn["issued_text"], "080035 UTC OCT 2026")
        self.assertEqual(spatial["type"], "Point")

    def test_sample_3_gnss_interference(self):
        header = "BALTIC SEA NAV WARN 026/25 [Western Baltic, Central Baltic]"
        raw = """021100 UTC JUL
SOUTHERN, SOUTHEASTERN, CENTRAL AND NORTHERN BALTIC.
GNSS, AIS, RADAR AND DGPS INTERFERENCE OBSERVED."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "BALTIC 026/25")
        self.assertEqual(nav_warn["category"], "electronic")
        self.assertEqual(nav_warn["issued_text"], "021100 UTC JUL 2025")
        self.assertIsNone(spatial)

    def test_coordinate_parsing(self):
        coords, lat, lon, spatial = parse_coordinates("PSN 58-10.2N 011-13.3E")
        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, 58.17, places=4)
        self.assertAlmostEqual(lon, 11.221667, places=4)

    def test_category_classification_rules(self):
        self.assertEqual(classify_hazard("UNLIT BUOY REPORTED OFF AIR"), "aton")
        self.assertEqual(classify_hazard("FIRING EXERCISE IN PROGRESS"), "military")
        self.assertEqual(classify_hazard("SUBSEA CABLE REPAIR OPERATION"), "subsea")
        self.assertEqual(classify_hazard("DRIFTING CONTAINER REPORTED"), "drifting")
        self.assertEqual(classify_hazard("DRILLING RIG JACK-UP RELOCATING"), "offshore")
        self.assertEqual(classify_hazard("GPS JAMMING OBSERVED IN AREA"), "electronic")
        self.assertEqual(classify_hazard("ROUTINE NOTICE TO MARINERS"), "general")

    def test_malformed_coordinates_do_not_crash(self):
        # Coordinates with out-of-range minutes or degrees should be safely skipped
        coords, lat, lon, spatial = parse_coordinates("PSN 99-99.9N 199-99.9E")
        self.assertEqual(coords, [])
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertIsNone(spatial)

    def test_multi_warning_file_parsing(self):
        file_content = """--- BALTIC SEA NAV WARN 010/26 [Central Baltic] ---
011200 UTC JAN
CENTRAL BALTIC.
LIGHT BUOY UNLIT PSN 59-00.0N 019-00.0E.

--- SWEDISH NAV WARN 020/26 [Skagerrak] ---
021400 UTC JAN
SKAGERRAK.
DRIFTING TIMBER REPORTED VICINITY 58-00.0N 011-00.0E.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "in.txt")
            out_path = os.path.join(tmpdir, "out.json")
            with open(in_path, "w", encoding="utf-8") as f:
                f.write(file_content)

            success = parse_main(in_path, out_path)
            self.assertTrue(success)
            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(len(data["nav_warnings"]), 2)
            self.assertEqual(data["nav_warnings"][0]["warning_id"], "BALTIC 010/26")
            self.assertEqual(data["nav_warnings"][0]["category"], "aton")
            self.assertEqual(data["nav_warnings"][1]["warning_id"], "SWEDISH 020/26")
            self.assertEqual(data["nav_warnings"][1]["category"], "drifting")


class TestEmptyHarvestBehavior(unittest.TestCase):
    """Ensures empty feeds do not crash the pipeline and correctly trigger cancellation."""

    def test_parser_with_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "empty.txt")
            out_path = os.path.join(tmpdir, "out.json")
            with open(in_path, "w", encoding="utf-8") as f:
                f.write("")

            success = parse_main(in_path, out_path)
            self.assertTrue(success)

            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["raw_messages"], [])
            self.assertEqual(data["nav_warnings"], [])
            self.assertEqual(data["spatial_features"], [])

    def test_parser_with_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "non_existent.txt")
            out_path = os.path.join(tmpdir, "out.json")

            success = parse_main(in_path, out_path)
            self.assertTrue(success)

            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["raw_messages"], [])
            self.assertEqual(data["nav_warnings"], [])
            self.assertEqual(data["spatial_features"], [])

    def test_differential_with_empty_scraped_cancels_all_active(self):
        scraped_warnings = []
        scraped_messages = []
        existing_warnings = {
            "BALTIC 001/26": {"warning_id": "BALTIC 001/26", "status": "active"},
            "SWEDISH 002/26": {"warning_id": "SWEDISH 002/26", "status": "active"},
            "SWEDISH 003/26": {"warning_id": "SWEDISH 003/26", "status": "cancelled"}
        }
        existing_checksums = {("BALTIC 001/26", "hash1"), ("SWEDISH 002/26", "hash2")}

        diff = compute_differential(scraped_warnings, scraped_messages, existing_warnings, existing_checksums)
        self.assertEqual(diff["skip"], [])
        self.assertEqual(diff["new"], [])
        self.assertEqual(diff["update"], [])
        self.assertCountEqual(diff["cancel"], ["BALTIC 001/26", "SWEDISH 002/26"])


class TestBalticSyncValidation(unittest.TestCase):
    """Validates data structures and dry-run safety for Baltic sync."""

    def test_validate_raw_message(self):
        valid_msg = {
            "warning_id": "BALTIC 001/26",
            "source_id": "sma-baltic-subarea",
            "checksum_sha256": "abcdef123456"
        }
        self.assertTrue(validate_raw_message(valid_msg))

        # Missing warning_id
        self.assertFalse(validate_raw_message({"source_id": "s", "checksum_sha256": "c"}))
        # Missing source_id
        self.assertFalse(validate_raw_message({"warning_id": "w", "checksum_sha256": "c"}))
        # Missing checksum
        self.assertFalse(validate_raw_message({"warning_id": "w", "source_id": "s"}))
        # Non-dict
        self.assertFalse(validate_raw_message(None))

    def test_validate_nav_warning(self):
        valid_warn = {
            "warning_id": "BALTIC 001/26",
            "source_id": "sma-baltic-subarea",
            "title": "Central Baltic"
        }
        self.assertTrue(validate_nav_warning(valid_warn))

        # Missing warning_id
        self.assertFalse(validate_nav_warning({"source_id": "s"}))
        # Missing source_id
        self.assertFalse(validate_nav_warning({"warning_id": "w"}))
        # Non-dict
        self.assertFalse(validate_nav_warning("invalid"))

    def test_sync_dry_run_without_credentials(self):
        # When SUPABASE_URL / SUPABASE_KEY are unset, sync_to_supabase should exit cleanly (dry-run)
        orig_url = os.environ.pop("SUPABASE_URL", None)
        orig_key = os.environ.pop("SUPABASE_KEY", None)
        try:
            res = sync_to_supabase("non_existent_file.json")
            self.assertTrue(res)
        finally:
            if orig_url:
                os.environ["SUPABASE_URL"] = orig_url
            if orig_key:
                os.environ["SUPABASE_KEY"] = orig_key


class TestDifferentialSync(unittest.TestCase):
    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "SWEDISH 168/26", "title": "Lysekil"},
            {"warning_id": "SWEDISH 167/26", "title": "Stora Polsan"},
            {"warning_id": "SWEDISH 999/26", "title": "New"}
        ]
        self.scraped_messages = [
            {"warning_id": "SWEDISH 168/26", "checksum_sha256": "hash_168_unchanged"},
            {"warning_id": "SWEDISH 167/26", "checksum_sha256": "hash_167_new"},
            {"warning_id": "SWEDISH 999/26", "checksum_sha256": "hash_999_new"}
        ]
        self.existing_warnings = {
            "SWEDISH 168/26": {"warning_id": "SWEDISH 168/26", "status": "active"},
            "SWEDISH 167/26": {"warning_id": "SWEDISH 167/26", "status": "active"},
            "SWEDISH 100/26": {"warning_id": "SWEDISH 100/26", "status": "active"}
        }
        self.existing_checksums = {
            ("SWEDISH 168/26", "hash_168_unchanged"),
            ("SWEDISH 167/26", "hash_167_old"),
            ("SWEDISH 100/26", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings, self.scraped_messages,
            self.existing_warnings, self.existing_checksums
        )
        self.assertIn("SWEDISH 168/26", diff["skip"])
        self.assertEqual(len(diff["skip"]), 1)
        new_ids = [w["warning_id"] for w, m in diff["new"]]
        self.assertIn("SWEDISH 999/26", new_ids)
        self.assertEqual(len(diff["new"]), 1)
        update_ids = [w["warning_id"] for w, m in diff["update"]]
        self.assertIn("SWEDISH 167/26", update_ids)
        self.assertEqual(len(diff["update"]), 1)
        self.assertIn("SWEDISH 100/26", diff["cancel"])
        self.assertEqual(len(diff["cancel"]), 1)


if __name__ == "__main__":
    unittest.main()

