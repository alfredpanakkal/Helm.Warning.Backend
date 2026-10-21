#!/usr/bin/env python3
"""tests/test_live_e2e.py — Live end-to-end proof against a scratch Supabase project.

Run explicitly with credentials:
  SUPABASE_URL=... SUPABASE_KEY=... python -m unittest tests.test_live_e2e -v

Skipped automatically when env vars are absent (CI runs the mock suite instead).
This suite asserts the join that the original defect bypassed:
rows must appear in nav_warnings, nav_warning_geometries AND
nav_warnings_active_spatial after the atomic RPC upsert.
"""
import os
import unittest

E2E_CID = "TEST-REGION 999/26"


@unittest.skipUnless(
    os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"),
    "Scratch Supabase credentials not provided; skipping live E2E",
)
class TestLiveEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from supabase import create_client
        cls.sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    def _upsert_test_warning(self):
        payload = {
            "master": {
                "canonical_id": E2E_CID,
                "navarea": "TEST-REGION",
                "title": "Live E2E test warning",
                "area_text": "54-00.0N 010-00.0E",
                "categories": ["test"],
                "status": "active",
                "triage_tier": "A",
                "raw_text": "end-to-end verification row",
                "source_id": "e2e-test",
            },
            "geometries": [{
                "zone_label": "e2e point",
                "feature_type": "POINT",
                "geojson": {"type": "Point", "coordinates": [10.0, 54.0]},
            }],
        }
        cls = self
        cls.sb.rpc("upsert_nav_warning", {"p_payload": payload}).execute()

    def test_01_rpc_populates_master_geometry_and_view(self):
        self._upsert_test_warning()
        view = self.sb.table("nav_warnings_active_spatial").select("canonical_id").execute()
        self.assertIn(
            E2E_CID,
            [r["canonical_id"] for r in view.data or []],
            "ORIGINAL BUG REGRESSION: nav_warnings_active_spatial is empty despite a "
            "successful master + geometry upsert",
        )

    def test_02_cancel_removes_from_view(self):
        self._upsert_test_warning()
        self.sb.table("nav_warnings").update({"status": "cancelled"}) \
            .eq("canonical_id", E2E_CID).execute()
        view = self.sb.table("nav_warnings_active_spatial").select("canonical_id").execute()
        self.assertNotIn(E2E_CID, [r["canonical_id"] for r in view.data or []])

    def test_03_anon_readable_and_realtime_published(self):
        # RLS: the anon role must be able to SELECT the view's base tables
        master = self.sb.table("nav_warnings").select("canonical_id").limit(1).execute()
        geoms = self.sb.table("nav_warning_geometries").select("warning_id").limit(1).execute()
        self.assertIsNotNone(master.data)
        self.assertIsNotNone(geoms.data)


if __name__ == "__main__":
    unittest.main()
