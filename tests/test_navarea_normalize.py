#!/usr/bin/env python3
"""tests/test_navarea_normalize.py — navarea column normalization (F3).

The live DB mixed bare codes ('II'), prefixed labels ('NAVAREA II') and
AUSCOAST area labels in nav_warnings.navarea, breaking region grouping
(audit finding F3, 2026-10-30). The generic sync is the ONE place every
universal source passes through, so normalization lives there: records
are normalized before the shared engine persists them, while the display
label (navarea_name) keeps its prefixed form — it is the canonical-id /
cross-ref target prefix.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_generic_sync import (
    sync_to_supabase, _normalized_navarea_column,
)


class TestNormalizedNavareaColumn(unittest.TestCase):
    def test_bare_code_passes_through(self):
        self.assertEqual(_normalized_navarea_column("II"), "II")
        self.assertEqual(_normalized_navarea_column("X"), "X")

    def test_prefixed_label_is_stripped(self):
        self.assertEqual(_normalized_navarea_column("NAVAREA II"), "II")

    def test_auscoast_area_files_under_x(self):
        self.assertEqual(_normalized_navarea_column("AUSCOAST B"), "X")
        self.assertEqual(_normalized_navarea_column("AUSCOAST D"), "X")

    def test_missing_value_is_none(self):
        self.assertIsNone(_normalized_navarea_column(None))
        self.assertIsNone(_normalized_navarea_column(""))
        self.assertIsNone(_normalized_navarea_column("   "))


class TestSyncNormalizesRecords(unittest.TestCase):
    """sync_to_supabase hands the engine normalized records; the display
    label (navarea_name) keeps its prefixed form."""

    def _sync(self, memo, warnings):
        captured = {}

        def fake_engine(**kwargs):
            captured.update(kwargs)
            return True

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "parsed.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"memo": memo, "nav_warnings": warnings,
                           "raw_messages": []}, f)
            env = {"SUPABASE_URL": "https://example.invalid",
                   "SUPABASE_KEY": "test-key"}
            with mock.patch.dict(os.environ, env), \
                 mock.patch("scripts.navarea_generic_sync."
                            "run_differential_sync", fake_engine):
                ok = sync_to_supabase(path)
        return ok, captured

    def test_legacy_prefixed_records_normalize_to_bare_codes(self):
        warnings = [{"warning_id": "NAVAREA II 001/26",
                     "navarea": "NAVAREA II", "raw_text": "X"}]
        ok, captured = self._sync(
            {"source_id": "manual-navarea-ii", "navarea": "II"}, warnings)
        self.assertTrue(ok)
        self.assertEqual(captured["navarea_name"], "NAVAREA II")
        self.assertEqual(
            captured["scraped_warnings"][0]["navarea"], "II")

    def test_auscoast_records_file_under_x(self):
        warnings = [{"warning_id": "AUSCOAST B 327/26",
                     "navarea": "AUSCOAST B", "raw_text": "X"}]
        ok, captured = self._sync(
            {"source_id": "manual-auscoast-b", "navarea": "AUSCOAST B"},
            warnings)
        self.assertTrue(ok)
        self.assertEqual(captured["navarea_name"], "AUSCOAST B")
        self.assertEqual(
            captured["scraped_warnings"][0]["navarea"], "X")

    def test_record_missing_navarea_gets_the_normalized_memo_code(self):
        warnings = [{"warning_id": "NAVAREA II 001/26", "raw_text": "X"}]
        ok, captured = self._sync(
            {"source_id": "manual-navarea-ii", "navarea": "II"}, warnings)
        self.assertTrue(ok)
        self.assertEqual(
            captured["scraped_warnings"][0]["navarea"], "II")

    def test_legacy_prefixed_memo_keeps_the_display_label(self):
        warnings = [{"warning_id": "NAVAREA II 001/26", "raw_text": "X"}]
        ok, captured = self._sync(
            {"source_id": "manual-navarea-ii", "navarea": "NAVAREA II"},
            warnings)
        self.assertTrue(ok)
        self.assertEqual(captured["navarea_name"], "NAVAREA II")
        self.assertEqual(
            captured["scraped_warnings"][0]["navarea"], "II")

    def test_input_records_are_copied_not_mutated(self):
        warnings = [{"warning_id": "NAVAREA II 001/26",
                     "navarea": "NAVAREA II", "raw_text": "X"}]
        self._sync({"source_id": "manual-navarea-ii", "navarea": "II"},
                   warnings)
        self.assertEqual(warnings[0]["navarea"], "NAVAREA II")


if __name__ == "__main__":
    unittest.main()
