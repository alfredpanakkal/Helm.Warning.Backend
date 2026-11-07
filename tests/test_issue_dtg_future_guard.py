#!/usr/bin/env python3
"""tests/test_issue_dtg_future_guard.py - Issue-DTG future guard + conflict flag tests.

All tests inject now_utc explicitly (the real clock is never read):
NOW = 2026-10-20T12:00Z, so now + 2 days = 2026-10-22T12:00Z (boundary
inclusive: exactly the boundary is accepted).

Covers the shared pure helpers (issue_dtg_is_future,
issue_dtg_has_conflict), the 2-digit year fail-closed rule (00-68 ->
2000s, 69-99 -> None), and the per-parser wiring (IV, universal, VIII):
a future issue DTG rejects to issued_text None + qa_flags
issue_dtg_future (never clamped); a both-ends match-and-disagree flags
issue_dtg_conflict; validity ranges and CANCEL datelines never trigger
the guard.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.models import (
    extract_issue_dtg,
    parse_safe_iso_timestamp,
    issue_dtg_is_future,
    issue_dtg_has_conflict,
)
from scripts.navarea_iv_parser import parse_warning as parse_warning_iv
from scripts.navarea_8_parser import parse_warning as parse_warning_viii
from scripts.navarea_universal_parser import (
    parse_warning as parse_warning_universal,
    _region_config,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
NAIVE_NOW = datetime(2026, 10, 20, 12, 0)  # naive UTC, like utcnow()


def _iv_block(raw_text):
    return {"warning_id": "NAVAREA IV 001/26", "number": "001", "year": "26",
            "raw_text": raw_text}


class TestFutureGuardPure(unittest.TestCase):
    def test_dtg_within_two_days_accepted(self):
        self.assertFalse(issue_dtg_is_future("221100Z OCT 26", NOW))
        self.assertEqual(parse_safe_iso_timestamp("221100Z OCT 26"), "2026-10-22T11:00:00")

    def test_boundary_exactly_two_days_accepted(self):
        self.assertFalse(issue_dtg_is_future("221200Z OCT 26", NOW))

    def test_one_minute_past_boundary_rejected(self):
        self.assertTrue(issue_dtg_is_future("221201Z OCT 26", NOW))

    def test_next_day_rejected(self):
        self.assertTrue(issue_dtg_is_future("230000Z OCT 26", NOW))

    def test_old_dates_always_accepted(self):
        self.assertFalse(issue_dtg_is_future("010000Z JAN 21", NOW))
        self.assertEqual(parse_safe_iso_timestamp("010000Z JAN 21"), "2021-01-01T00:00:00")

    def test_year_69_99_fails_closed(self):
        self.assertIsNone(parse_safe_iso_timestamp("011500 UTC NOV 99"))
        self.assertIsNone(extract_issue_dtg("011500 UTC NOV 99"))

    def test_year_68_parses_then_future_guard_rejects(self):
        # 68 -> 2068 per the 00-68 rule (maintainer decision); 2068 is
        # impossible for this corpus, so the run-start future guard
        # rejects it downstream.
        self.assertEqual(parse_safe_iso_timestamp("011500 UTC NOV 68"), "2068-11-01T15:00:00")
        self.assertTrue(issue_dtg_is_future("011500 UTC NOV 68", NOW))

    def test_current_year_parses(self):
        self.assertEqual(parse_safe_iso_timestamp("011500 UTC NOV 26"), "2026-11-01T15:00:00")

    def test_naive_now_no_typeerror(self):
        # naive utcnow()-style values are assumed UTC, never compared
        # directly against aware datetimes.
        self.assertTrue(issue_dtg_is_future("221201Z OCT 26", NAIVE_NOW))
        self.assertFalse(issue_dtg_is_future("221100Z OCT 26", NAIVE_NOW))

    def test_trailing_cr_handled(self):
        self.assertEqual(extract_issue_dtg("021102Z/NOV 26\r"), "021102Z/NOV 26")

    def test_none_or_invalid_token_not_future(self):
        self.assertFalse(issue_dtg_is_future(None, NOW))
        self.assertFalse(issue_dtg_is_future("NOT A DTG", NOW))
        self.assertFalse(issue_dtg_is_future("221201Z OCT 26", None))


class TestConflictPure(unittest.TestCase):
    def test_both_ends_disagree(self):
        raw = "301639Z OCT 26\nBODY TEXT.\n051500 UTC NOV 2026"
        self.assertTrue(issue_dtg_has_conflict(raw))
        self.assertIsNone(extract_issue_dtg(raw))

    def test_both_ends_agree_no_conflict(self):
        raw = "301639Z OCT 26\nBODY TEXT.\n301639Z OCT 26"
        self.assertFalse(issue_dtg_has_conflict(raw))
        self.assertEqual(extract_issue_dtg(raw), "301639Z OCT 26")

    def test_single_dtg_no_conflict(self):
        raw = "301639Z OCT 26\nBODY TEXT."
        self.assertFalse(issue_dtg_has_conflict(raw))


class TestIVWiring(unittest.TestCase):
    def test_future_dtg_rejected_and_flagged(self):
        raw = "230000Z OCT 26\nNAVAREA IV 001/26 TEST AREA.\n1. 12-34.5N 067-56.7W"
        _, warn = parse_warning_iv(_iv_block(raw), now_utc=NOW)
        self.assertIsNone(warn["issued_text"])
        self.assertEqual(warn["qa_flags"], ["issue_dtg_future"])

    def test_boundary_dtg_accepted(self):
        raw = "221200Z OCT 26\nNAVAREA IV 001/26 TEST AREA.\n1. 12-34.5N 067-56.7W"
        _, warn = parse_warning_iv(_iv_block(raw), now_utc=NOW)
        self.assertEqual(warn["issued_text"], "221200Z OCT 26")
        self.assertEqual(warn["qa_flags"], [])

    def test_old_dtg_accepted_no_flag(self):
        raw = "010000Z JAN 21\nNAVAREA IV 001/26 TEST AREA.\n1. 12-34.5N 067-56.7W"
        _, warn = parse_warning_iv(_iv_block(raw), now_utc=NOW)
        self.assertEqual(warn["issued_text"], "010000Z JAN 21")
        self.assertEqual(warn["qa_flags"], [])

    def test_both_ends_conflict_flagged(self):
        raw = ("040124Z MAR 26\nNAVAREA IV 001/26 TEST AREA.\n"
               "1. 12-34.5N 067-56.7W\n051200Z MAR 26")
        _, warn = parse_warning_iv(_iv_block(raw), now_utc=NOW)
        self.assertIsNone(warn["issued_text"])
        self.assertEqual(warn["qa_flags"], ["issue_dtg_conflict"])

    def test_naive_now_utc_wiring(self):
        raw = "221201Z OCT 26\nNAVAREA IV 001/26 TEST AREA.\n1. 12-34.5N 067-56.7W"
        _, warn = parse_warning_iv(_iv_block(raw), now_utc=NAIVE_NOW)
        self.assertIsNone(warn["issued_text"])
        self.assertEqual(warn["qa_flags"], ["issue_dtg_future"])


class TestUniversalWiring(unittest.TestCase):
    def setUp(self):
        self.cfg = _region_config("ix")

    def _block(self, raw_text):
        return {"number": "001", "year": "26",
                "header_text": "NAVAREA IX 001/26", "raw_text": raw_text}

    def test_future_validity_range_still_sets_valid_from_no_flag(self):
        raw = ("NAVAREA IX 001/26 GUNNERY EXERCISE IN AREA BOUNDED BY\n"
               "11-11.0N 222-22.0E, 11-44.0N 222-22.0E.\n"
               "14 MAY 27 TO 14 NOV 27")
        _, warn = parse_warning_universal(self._block(raw), self.cfg, now_utc=NOW)
        self.assertEqual(warn["valid_from"], "2027-05-14")
        self.assertEqual(warn["valid_to"], "2027-11-14")
        self.assertIsNone(warn["issued_text"])
        self.assertNotIn("issue_dtg_future", warn["qa_flags"])
        self.assertNotIn("issue_dtg_conflict", warn["qa_flags"])

    def test_future_cancel_dateline_no_flag(self):
        raw = ("NAVAREA IX 001/26 HYDROGRAPHIC SURVEY.\n"
               "2. CANCEL THIS MSG 301000Z NOV 26")
        _, warn = parse_warning_universal(self._block(raw), self.cfg, now_utc=NOW)
        self.assertIsNone(warn["issued_text"])
        self.assertEqual(warn["valid_to"], "2026-11-30T10:00:00Z")
        self.assertNotIn("issue_dtg_future", warn["qa_flags"])
        self.assertNotIn("issue_dtg_conflict", warn["qa_flags"])

    def test_future_trailing_dtg_rejected_and_flagged(self):
        raw = "NAVAREA IX 001/26 GUNNERY EXERCISE.\n221201Z OCT 26"
        _, warn = parse_warning_universal(self._block(raw), self.cfg, now_utc=NOW)
        self.assertIsNone(warn["issued_text"])
        self.assertIn("issue_dtg_future", warn["qa_flags"])


class TestVIIIWiring(unittest.TestCase):
    def _block(self, raw_text):
        return {"warning_id": "NAVAREA VIII 001/26", "number": "001", "year": "26",
                "raw_text": raw_text}

    def test_future_trailing_dtg_rejected_and_flagged(self):
        raw = "NAVAREA VIII -001/26 TEST AREA INDIAN WEST COAST.\n230000Z OCT 26"
        _, warn = parse_warning_viii(self._block(raw), now_utc=NOW)
        self.assertIsNone(warn["issued_text"])
        self.assertEqual(warn["qa_flags"], ["issue_dtg_future"])

    def test_old_trailing_dtg_accepted(self):
        raw = "NAVAREA VIII -001/26 TEST AREA INDIAN WEST COAST.\n010000Z JAN 21"
        _, warn = parse_warning_viii(self._block(raw), now_utc=NOW)
        self.assertEqual(warn["issued_text"], "010000Z JAN 21")
        self.assertEqual(warn["qa_flags"], [])


if __name__ == '__main__':
    unittest.main()
