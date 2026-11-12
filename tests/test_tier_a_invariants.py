#!/usr/bin/env python3
"""Regression tests for the database Tier-A invariant at payload and lifecycle boundaries."""

import os
import sys
import unittest
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.models import build_master_payload, qa_flags_require_review
from scripts.navarea_8_sync import _supersede_cross_refs as supersede_viii
from scripts.navarea_iv_sync import _supersede_cross_refs as supersede_iv
from scripts.navarea_xii_sync import _supersede_cross_refs as supersede_xii


class _Query:
    def __init__(self, rows, table):
        self.rows = rows
        self.table = table

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Table:
    def __init__(self, rows):
        self.rows = rows
        self.patch = None

    def select(self, *_args, **_kwargs):
        return _Query(self.rows, self)

    def update(self, patch):
        self.patch = patch
        return _Query([], self)


class _Client:
    def __init__(self, rows):
        self.table_instance = _Table(rows)

    def table(self, _name):
        return self.table_instance


class TestTierAPayloadInvariant(unittest.TestCase):
    def _record(self, **overrides):
        record = {
            "warning_id": "001/26",
            "navarea": "NAVAREA I",
            "raw_text": "TEST WARNING",
            "spatial": {
                "type": "Point",
                "coordinates": [12.5, 55.5],
            },
            "triage_tier": "A",
            "data_quality": "EXPLICIT",
            "parsing_method": "RULE",
        }
        record.update(overrides)
        return record

    def test_explicit_rule_geometry_remains_tier_a(self):
        self.assertEqual(build_master_payload(self._record())["triage_tier"], "A")

    def test_ambiguous_geometry_is_demoted_to_tier_b(self):
        master = build_master_payload(self._record(data_quality="AMBIGUOUS"))
        self.assertEqual(master["triage_tier"], "B")
        self.assertIsNone(master["unplotted_reason"])

    def test_inferred_geometry_is_demoted_to_tier_b(self):
        master = build_master_payload(self._record(data_quality="INFERRED"))
        self.assertEqual(master["triage_tier"], "B")

    def test_ai_parsed_geometry_is_demoted_to_tier_b(self):
        master = build_master_payload(self._record(parsing_method="AI"))
        self.assertEqual(master["triage_tier"], "B")

    def test_superseded_geometry_is_not_tier_a(self):
        master = build_master_payload(self._record(status="superseded"))
        self.assertEqual(master["triage_tier"], "B")

    def test_unplotted_reason_disqualifies_tier_a(self):
        master = build_master_payload(
            self._record(unplotted_reason="validation_failed")
        )
        self.assertEqual(master["triage_tier"], "B")

    def test_no_geometry_remains_tier_c(self):
        record = self._record()
        record.pop("spatial")
        master = build_master_payload(record)
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "no_valid_geometry")

    def test_review_required_qa_flag_demotes_geometry_to_tier_b(self):
        master = build_master_payload(
            self._record(qa_flags=["COORD_COUNT_MISMATCH"])
        )
        self.assertEqual(master["triage_tier"], "B")

    def test_geometry_basis_flag_remains_informational(self):
        master = build_master_payload(
            self._record(qa_flags=["geometry_basis:keyword:rig"])
        )
        self.assertEqual(master["triage_tier"], "A")


class TestQaFlagReviewPolicy(unittest.TestCase):
    def test_empty_flags_do_not_require_review(self):
        self.assertFalse(qa_flags_require_review([]))

    def test_geometry_basis_flags_are_informational(self):
        self.assertFalse(
            qa_flags_require_review(["geometry_basis:keyword:rig"])
        )

    def test_non_geometry_basis_flags_require_review(self):
        for flag in (
            "COORD_COUNT_MISMATCH",
            "geometry_preserved_previous_run",
            "verified_by_admin",
        ):
            with self.subTest(flag=flag):
                self.assertTrue(qa_flags_require_review([flag]))

    def test_mixed_flags_require_review(self):
        self.assertTrue(
            qa_flags_require_review([
                "geometry_basis:keyword:rig",
                "COORD_COUNT_MISMATCH",
            ])
        )


class TestSupersedeLifecycleInvariant(unittest.TestCase):
    def test_superseding_tier_a_demotes_to_b_without_geometry_mutation(self):
        cases = (
            (supersede_viii, "NAVAREA VIII", "nho-navarea-viii"),
            (supersede_iv, "NAVAREA IV", "nga-navarea-iv"),
            (supersede_xii, "NAVAREA XII", "nga-navarea-xii"),
        )
        for transition, navarea, _source_id in cases:
            with self.subTest(navarea=navarea):
                cid = navarea + " 001/26"
                client = _Client([{
                    "canonical_id": cid,
                    "status": "active",
                    "triage_tier": "A",
                }])
                ok = transition(client, [{
                    "cross_refs": [{"number": "001", "year": "26"}],
                }])
                self.assertTrue(ok)
                self.assertEqual(
                    client.table_instance.patch,
                    {"status": "superseded", "triage_tier": "B"},
                )

    def test_superseding_tier_b_or_c_preserves_existing_tier(self):
        for transition, navarea in (
            (supersede_viii, "NAVAREA VIII"),
            (supersede_iv, "NAVAREA IV"),
            (supersede_xii, "NAVAREA XII"),
        ):
            for tier in ("B", "C"):
                with self.subTest(navarea=navarea, tier=tier):
                    cid = navarea + " 001/26"
                    client = _Client([{
                        "canonical_id": cid,
                        "status": "active",
                        "triage_tier": tier,
                    }])
                    ok = transition(client, [{
                        "cross_refs": [{"number": "001", "year": "26"}],
                    }])
                    self.assertTrue(ok)
                    self.assertEqual(
                        client.table_instance.patch,
                        {"status": "superseded"},
                    )


if __name__ == "__main__":
    unittest.main()
