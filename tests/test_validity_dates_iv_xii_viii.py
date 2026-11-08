#!/usr/bin/env python3
"""tests/test_validity_dates_iv_xii_viii.py - validity-date emission for
the dedicated IV / XII / VIII parsers (audit F1 extension, 2026-11-08).

The three dedicated parsers reuse the universal parser's
_extract_validity_dates (same import as the backfill script) with the
block's header year. Contract (Alfred, 2026-11-08): a returned value is
kept ONLY when it carries a time of day; date-only stamps are dropped
(None) and no time is ever invented. A cancel dateline with a time sets
valid_to; valid_from stays the issue DTG (build_master_payload's
issued_text fallback) unless a time-bearing range start exists.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.navarea_iv_parser import parse_memo_text as parse_iv
from scripts.navarea_xii_parser import parse_memo_text as parse_xii
from scripts.navarea_8_parser import parse_bulletin_text as parse_viii
from shared.models import build_master_payload

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)

IV_CANCEL_BODY = (
    "1. SURVEY OPERATIONS IN PROGRESS IN AREA BOUND BY\n"
    "   27-53.36N 095-40.98W, 26-47.28N 095-39.87W.\n"
    "   WIDE BERTH REQUESTED.\n"
    "2. CANCEL THIS MSG 070001Z NOV 26.\n")

IV_UNTIL_BODY = (
    "1. SURVEY OPERATIONS UNTIL 31 DEC 26 IN AREA BOUND BY\n"
    "   27-53.36N 095-40.98W.\n")

IV_RANGE_BODY = (
    "1. OPERATIONS 14 MAY 26 TO 14 NOV 26 IN AREA BOUND BY\n"
    "   27-53.36N 095-40.98W.\n")

IV_TIMED_RANGE_BODY = (
    "1. OPERATIONS 070300Z MAY 26 TO 142300Z NOV 26 IN AREA BOUND BY\n"
    "   27-53.36N 095-40.98W.\n")

IV_PLAIN_BODY = (
    "1. SURVEY OPERATIONS IN PROGRESS IN AREA BOUND BY\n"
    "   27-53.36N 095-40.98W.\n"
    "   WIDE BERTH REQUESTED.\n")


def _iv_memo(number, body):
    return ("062049Z JAN 26\n"
            "NAVAREA IV %s/26(1).\n" % number
            + "GULF OF AMERICA.\n"
            + "TEXAS.\n" + body)


def _xii_memo(number, body):
    return ("251304Z FEB 26\n"
            "NAVAREA XII %s/26(1).\n" % number
            + "NORTH PACIFIC.\n"
            + "CALIFORNIA.\n" + body)


VIII_CANCEL_BULLETIN = (
    "NAVAREA VIII - WARNINGS IN FORCE AS ON 02 NOV 2026\n"
    "NAVAREA VIII -1102/26 INDIA WEST COAST - KARWAR (.) CHARTS IN 215 257 "
    "INT 7343 (.) HYDROGRAPHIC SURVEY UNDER PROGRESS IN AREA BOUNDED WITHIN "
    "14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E 2. CANCEL THIS MSG "
    "070001Z NOV 26.\n"
    "--------------------------------\n"
    "021102Z/NOV 26\n")


class TestCancelDateline(unittest.TestCase):
    """A self-cancel dateline with a time sets valid_to; the parser
    leaves valid_from to the issue DTG (None key, master fallback)."""

    def test_iv_cancel_dateline_sets_valid_to(self):
        parsed = parse_iv(_iv_memo("21", IV_CANCEL_BODY), now_utc=NOW)
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA IV 21/26")
        self.assertEqual(w["valid_to"], "2026-11-07T00:01:00Z")
        self.assertIsNone(w["valid_from"])
        self.assertEqual(w["issued_text"], "062049Z JAN 26")
        self.assertEqual(w["status"], "active")
        self.assertEqual(w["qa_flags"], [])

    def test_xii_cancel_dateline_sets_valid_to(self):
        parsed = parse_xii(_xii_memo("301", IV_CANCEL_BODY), now_utc=NOW)
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA XII 301/26")
        self.assertEqual(w["valid_to"], "2026-11-07T00:01:00Z")
        self.assertIsNone(w["valid_from"])
        self.assertEqual(w["issued_text"], "251304Z FEB 26")
        self.assertEqual(w["qa_flags"], [])

    def test_viii_cancel_before_dashes_and_trailing_dtg(self):
        # NAVAREA VIII 1102/26 shape: the self-cancel dateline sits in
        # the body BEFORE the dashes line and the trailing DTG.
        parsed = parse_viii(VIII_CANCEL_BULLETIN, now_utc=NOW)
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA VIII 1102/26")
        self.assertIn("CANCEL THIS MSG 070001Z NOV 26.", w["raw_text"])
        self.assertIn("----", w["raw_text"])
        self.assertIn("021102Z/NOV 26", w["raw_text"])
        self.assertEqual(w["valid_to"], "2026-11-07T00:01:00Z")
        self.assertEqual(w["issued_text"], "021102Z/NOV 26")
        self.assertIsNone(w["valid_from"])
        self.assertEqual(w["qa_flags"], [])


class TestDateOnlyValuesDropped(unittest.TestCase):
    """Date-only stamps carry no time of day - dropped (None), never
    invented. valid_from keeps falling back to the issue DTG."""

    def test_until_date_only_dropped(self):
        parsed = parse_iv(_iv_memo("22", IV_UNTIL_BODY), now_utc=NOW)
        w = parsed["nav_warnings"][0]
        self.assertIsNone(w["valid_to"])
        self.assertIsNone(w["valid_from"])

    def test_date_only_range_dropped(self):
        parsed = parse_iv(_iv_memo("23", IV_RANGE_BODY), now_utc=NOW)
        w = parsed["nav_warnings"][0]
        self.assertIsNone(w["valid_from"])
        self.assertIsNone(w["valid_to"])
        self.assertEqual(w["issued_text"], "062049Z JAN 26")

    def test_no_validity_evidence_is_none_none(self):
        parsed = parse_iv(_iv_memo("24", IV_PLAIN_BODY), now_utc=NOW)
        w = parsed["nav_warnings"][0]
        self.assertIsNone(w["valid_from"])
        self.assertIsNone(w["valid_to"])


class TestTimeBearingRangeKept(unittest.TestCase):
    def test_timed_range_sets_both_ends(self):
        parsed = parse_iv(_iv_memo("25", IV_TIMED_RANGE_BODY), now_utc=NOW)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["valid_from"], "2026-05-07T03:00:00Z")
        self.assertEqual(w["valid_to"], "2026-11-14T23:00:00Z")


class TestMasterPayloadEndToEnd(unittest.TestCase):
    """build_master_payload: valid_to from the cancel dateline;
    valid_from falls back to the issue DTG when no time-bearing range
    start exists (parse_safe_iso formats: naive DTG iso, Z -> +00:00)."""

    def test_iv_block_master_payload(self):
        parsed = parse_iv(_iv_memo("21", IV_CANCEL_BODY), now_utc=NOW)
        master = build_master_payload(parsed["nav_warnings"][0])
        self.assertEqual(master["valid_from"], "2026-01-06T20:49:00")
        self.assertEqual(master["valid_to"], "2026-11-07T00:01:00+00:00")

    def test_viii_block_master_payload(self):
        parsed = parse_viii(VIII_CANCEL_BULLETIN, now_utc=NOW)
        master = build_master_payload(parsed["nav_warnings"][0])
        self.assertEqual(master["valid_from"], "2026-11-02T11:02:00")
        self.assertEqual(master["valid_to"], "2026-11-07T00:01:00+00:00")


if __name__ == "__main__":
    unittest.main()
