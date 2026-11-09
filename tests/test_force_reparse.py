#!/usr/bin/env python3
"""Tests for the SYNC_FORCE_REPARSE full-rewrite mode in
compute_differential (shared/utils.py): an ACTIVE row whose raw-text
checksum matches re-classifies skip -> update, while rows carrying
AI/admin correction qa_flags stay skipped (corrections are never
clobbered by a fresh rule parse). Offline; no DB access.
"""

import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.utils import compute_differential, _has_applied_corrections


def _warn(cid):
    return {"canonical_id": cid, "warning_id": cid,
            "status": "active", "raw_text": "RAW " + cid}


def _msg(cid):
    return {"warning_id": cid, "canonical_id": cid,
            "checksum_sha256": "chk-" + cid}


class TestForceReparse(unittest.TestCase):

    def setUp(self):
        self.existing = {
            "NAVAREA I 010/26": {"id": 1, "canonical_id": "NAVAREA I 010/26",
                                 "status": "active", "qa_flags": []},
            "NAVAREA I 011/26": {"id": 2, "canonical_id": "NAVAREA I 011/26",
                                 "status": "active",
                                 "qa_flags": ["edited_by_admin"]},
            "NAVAREA I 012/26": {"id": 3, "canonical_id": "NAVAREA I 012/26",
                                 "status": "active",
                                 "qa_flags": ["ai_correction_applied", "MISSING_HEM"]},
            "NAVAREA I 013/26": {"id": 4, "canonical_id": "NAVAREA I 013/26",
                                 "status": "cancelled", "qa_flags": []},
        }
        self.scraped = [_warn(c) for c in self.existing]
        self.msgs = [_msg(c) for c in self.existing]
        self.checksums = {(c, "chk-" + c) for c in self.existing}

    def _diff(self, force):
        return compute_differential(
            scraped_warnings=self.scraped,
            scraped_messages=self.msgs,
            existing_warnings=self.existing,
            existing_checksums=self.checksums,
            key_fn=lambda w: w.get("canonical_id"),
            force_reparse=force,
        )

    def test_default_mode_skips_unchanged_active_rows(self):
        diff = self._diff(force=False)
        self.assertEqual(set(diff["skip"]),
                         {"NAVAREA I 010/26", "NAVAREA I 011/26", "NAVAREA I 012/26"})
        updated_ids = {w["canonical_id"] for w, _m in diff["update"]}
        self.assertEqual(updated_ids, {"NAVAREA I 013/26"})  # not active

    def test_force_reparse_updates_unchanged_rows(self):
        diff = self._diff(force=True)
        updated_ids = {w["canonical_id"] for w, _m in diff["update"]}
        self.assertIn("NAVAREA I 010/26", updated_ids)
        self.assertIn("NAVAREA I 013/26", updated_ids)  # unchanged: not active
        # AI/admin-corrected rows are preserved
        self.assertIn("NAVAREA I 011/26", diff["skip"])
        self.assertIn("NAVAREA I 012/26", diff["skip"])
        self.assertNotIn("NAVAREA I 011/26", updated_ids)
        self.assertNotIn("NAVAREA I 012/26", updated_ids)

    def test_force_reparse_new_warning_still_new(self):
        self.scraped.append(_warn("NAVAREA I 999/26"))
        self.msgs.append(_msg("NAVAREA I 999/26"))
        diff = self._diff(force=True)
        new_ids = {w["canonical_id"] for w, _m in diff["new"]}
        self.assertIn("NAVAREA I 999/26", new_ids)

    def test_has_applied_corrections_tolerant(self):
        self.assertTrue(_has_applied_corrections({"qa_flags": ["ai_correction_applied"]}))
        self.assertTrue(_has_applied_corrections({"qa_flags": ["edited_by_admin"]}))
        self.assertTrue(_has_applied_corrections({"qa_flags": "edited_by_admin"}))
        self.assertFalse(_has_applied_corrections({"qa_flags": ["MISSING_HEM"]}))
        self.assertFalse(_has_applied_corrections({}))
        self.assertFalse(_has_applied_corrections(None))


if __name__ == "__main__":
    unittest.main()
