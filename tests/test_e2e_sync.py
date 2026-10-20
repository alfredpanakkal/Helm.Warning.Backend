#!/usr/bin/env python3
"""tests/test_e2e_sync.py — End-to-End Regression Harness for Schema-Aware Sync & RPC.
Uses standard library unittest for zero-dependency test runner execution.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.models import (
    build_master_payload,
    build_geometry_payloads,
    format_canonical_id,
    parse_safe_iso_timestamp,
    TriageRecord,
    TriageTier,
    DataQuality,
    ParsingMethod,
)
from shared.utils import compute_differential
from shared.sync_engine import run_differential_sync, upsert_warning_atomic


class TestE2ESync(unittest.TestCase):

    def test_format_canonical_id(self):
        self.assertEqual(format_canonical_id("NAVAREA I", "042/26"), "NAVAREA I 042/26")
        self.assertEqual(format_canonical_id("NAVAREA XI", "NAVAREA XI 105/26"), "NAVAREA XI 105/26")
        self.assertEqual(format_canonical_id("NAVAREA II", "359/26"), "NAVAREA II 359/26")
        self.assertEqual(format_canonical_id("NAVAREA BALTIC", "005/26"), "NAVAREA BALTIC 005/26")

    def test_safe_iso_timestamp_parsing(self):
        self.assertIsNotNone(parse_safe_iso_timestamp("2026-10-19T14:30:00Z"))
        self.assertIsNotNone(parse_safe_iso_timestamp("2026-10-19 14:30:00"))

        # Free-text strings must return None so PostgreSQL timestamptz does not throw
        self.assertIsNone(parse_safe_iso_timestamp("2026 HOURS 19 OCT"))
        self.assertIsNone(parse_safe_iso_timestamp("UNTIL FURTHER NOTICE"))
        self.assertIsNone(parse_safe_iso_timestamp(""))
        self.assertIsNone(parse_safe_iso_timestamp(None))

    def test_build_master_payload_schema_compliance(self):
        raw_input = {
            "warning_id": "042/26",
            "navarea": "NAVAREA I",
            "title": "ENGLAND, EAST COAST",
            "area_text": "THAMES ESTUARY",
            "category": "drifting",
            "categories": ["drifting", "military"],
            "status": "active",
            "latitude": 51.5074,
            "longitude": 0.1278,
            "spatial": {
                "type": "Point",
                "coordinates": [0.1278, 51.5074]
            },
            "issued_text": "2026-10-19T08:00:00Z",
            "raw_text": "NAVAREA I 042/26 DRIFTING BUOY ADRIFT IN THAMES",
            "source_id": "ukho-navarea-1"
        }

        master = build_master_payload(raw_input)

        # 1. Stale columns must NOT be present in master payload
        self.assertNotIn("latitude", master)
        self.assertNotIn("longitude", master)
        self.assertNotIn("spatial", master)
        self.assertNotIn("issued_text", master)

        # 2. Schema columns must be present and well-typed
        self.assertEqual(master["canonical_id"], "NAVAREA I 042/26")
        self.assertEqual(master["navarea"], "NAVAREA I")
        self.assertEqual(master["status"], "active")
        self.assertEqual(master["triage_tier"], "A")
        self.assertEqual(master["data_quality"], "EXPLICIT")
        self.assertEqual(master["parsing_method"], "RULE")
        self.assertEqual(master["categories"], ["drifting", "military"])
        self.assertIsNotNone(master["valid_from"])
        self.assertEqual(master["source_id"], "ukho-navarea-1")

    def test_build_geometry_payloads(self):
        # Point
        point_input = {
            "title": "Hazard Pin",
            "latitude": 55.5,
            "longitude": 12.5,
        }
        geoms = build_geometry_payloads(point_input)
        self.assertEqual(len(geoms), 1)
        self.assertEqual(geoms[0]["feature_type"], "point")
        self.assertEqual(geoms[0]["geojson"]["type"], "Point")
        self.assertEqual(geoms[0]["geojson"]["coordinates"], [12.5, 55.5])

        # Polygon
        poly_input = {
            "title": "Firing Range",
            "spatial": {
                "type": "Polygon",
                "coordinates": [[[10, 50], [11, 50], [11, 51], [10, 50]]]
            }
        }
        poly_geoms = build_geometry_payloads(poly_input)
        self.assertEqual(len(poly_geoms), 1)
        self.assertEqual(poly_geoms[0]["feature_type"], "polygon")
        self.assertEqual(poly_geoms[0]["geojson"]["type"], "Polygon")

    def test_triage_tier_c_for_no_geometry(self):
        stub_record = {
            "warning_id": "999/26",
            "navarea": "NAVAREA I",
            "title": "NO COORD WARNING",
            "raw_text": "GENERAL WARNING TEXT WITHOUT COORDS",
            "source_id": "ukho-navarea-1"
        }
        master = build_master_payload(stub_record)
        geoms = build_geometry_payloads(stub_record)

        self.assertEqual(len(geoms), 0)
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "no_valid_geometry")

    def test_compute_differential_with_canonical_id(self):
        scraped_warnings = [
            {"canonical_id": "NAVAREA I 001/26", "warning_id": "001/26", "status": "active"},
            {"canonical_id": "NAVAREA I 002/26", "warning_id": "002/26", "status": "active"},
        ]
        scraped_messages = [
            {"warning_id": "001/26", "checksum_sha256": "chk1"},
            {"warning_id": "002/26", "checksum_sha256": "chk2"},
        ]
        existing_warnings = {
            "NAVAREA I 001/26": {"status": "active"},
            "NAVAREA I 003/26": {"status": "active"},  # vanished -> should cancel
        }
        existing_checksums = {("001/26", "chk1")}

        diff = compute_differential(
            scraped_warnings=scraped_warnings,
            scraped_messages=scraped_messages,
            existing_warnings=existing_warnings,
            existing_checksums=existing_checksums,
            key_fn=lambda w: w.get("canonical_id")
        )

        self.assertIn("NAVAREA I 001/26", diff["skip"])
        self.assertTrue(any(w[0]["canonical_id"] == "NAVAREA I 002/26" for w in diff["new"]))
        self.assertIn("NAVAREA I 003/26", diff["cancel"])

    def test_atomic_rpc_call_structure(self):
        mock_supabase = MagicMock()
        mock_rpc = MagicMock()
        mock_supabase.rpc.return_value = mock_rpc

        master = {"canonical_id": "NAVAREA I 042/26", "title": "Test Warning"}
        geoms = [{"zone_label": "Zone A", "geojson": {"type": "Point", "coordinates": [0, 0]}}]

        success = upsert_warning_atomic(mock_supabase, master, geoms)
        self.assertTrue(success)
        mock_supabase.rpc.assert_called_once_with(
            "upsert_nav_warning",
            {"p_payload": {"master": master, "geometries": geoms}}
        )

    def test_fail_fast_missing_credentials(self):
        from shared.sync_engine import get_supabase_client
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_KEY": "", "ALLOW_DRY_RUN": ""}):
            with self.assertRaises(SystemExit) as cm:
                get_supabase_client()
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

    def test_regional_sync_script_no_silent_success_without_credentials(self):
        """Regression: regional sync scripts must NOT exit 0 when credentials
        are absent and ALLOW_DRY_RUN is unset (the 'green CI, nothing saved' bug).
        The shared engine pre-flight must exit with code 2."""
        import subprocess
        env = {k: v for k, v in os.environ.items()
               if k not in ("SUPABASE_URL", "SUPABASE_KEY", "ALLOW_DRY_RUN")}
        for script in ("scripts/navarea_1_sync.py",
                       "scripts/navarea_xi_sync.py",
                       "scripts/baltic_sync.py"):
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, script],
                    env=env, capture_output=True, timeout=120,
                )
                self.assertEqual(
                    result.returncode, 2,
                    f"{script} must exit 2 on missing credentials, got {result.returncode}"
                )

    def test_regional_sync_dry_run_is_explicit(self):
        """With ALLOW_DRY_RUN=1 the engine prints an explicit dry-run banner
        rather than pretending a sync happened."""
        import subprocess
        env = {k: v for k, v in os.environ.items()
               if k not in ("SUPABASE_URL", "SUPABASE_KEY")}
        env["ALLOW_DRY_RUN"] = "1"
        result = subprocess.run(
            [sys.executable, "scripts/navarea_1_sync.py"],
            env=env, capture_output=True, timeout=120,
        )
        self.assertIn(result.returncode, (0, 1))  # 1 acceptable if fixture file missing
        self.assertIn(b"Dry-run", result.stdout + result.stderr)
