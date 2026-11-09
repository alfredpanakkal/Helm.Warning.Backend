#!/usr/bin/env python3
"""tests/test_validity_dates_and_this_msg.py - combined
"CANCEL <refs> AND THIS MSG <DTG>" dateline (one line) sets valid_to.

Contract: the DTG is read ONLY when it sits on the SAME line as the
"AND THIS MSG" wording, and only with Z or UTC plus the year (2 or 4
digits) - the year is never inherited from the warning year. "AND THIS
MSG" without a DTG, "AND THIS PARAGRAPH" and "CANCEL THIS PARAGRAPH"
never set valid_to. The plain "CANCEL THIS ..." self-cancel dateline
keeps precedence over the combined form.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.navarea_universal_parser import _extract_validity_dates
from scripts.navarea_8_parser import parse_bulletin_text as parse_viii

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

COMBINED = "2.  CANCEL NAVAREA VIII MSG 1097/26 AND THIS MSG 131830 UTC NOV 26 "


class TestCombinedDatelinePositive(unittest.TestCase):
    def test_combined_sets_valid_to(self):
        self.assertEqual(_extract_validity_dates(COMBINED, "26"),
                         (None, "2026-11-13T18:30:00Z"))

    def test_combined_dec_03(self):
        raw = ("2.  CANCEL NAVAREA VIII MSG 1157/26 AND THIS MSG "
               "031830 UTC DEC 26 ")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-12-03T18:30:00Z"))

    def test_combined_dec_24(self):
        raw = ("2.  CANCEL NAVAREA VIII MSG 1097/26 AND THIS MSG "
               "241830 UTC DEC 26 ")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-12-24T18:30:00Z"))

    def test_combined_four_digit_year(self):
        raw = ("CANCEL NAVAREA VIII MSG 1097/26 AND THIS MSG "
               "131830 UTC NOV 2026")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-11-13T18:30:00Z"))


class TestCombinedDatelineNegative(unittest.TestCase):
    def test_dtg_on_next_line_is_not_an_expiry(self):
        # The time group on the NEXT line is the issue DTG, never an expiry.
        raw = ("CANCEL NAVAREA IX 390/26 AND THIS MSG" + chr(10) + chr(10)
               + "291500 UTC OCT 2026")
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_and_this_paragraph_never_expires(self):
        raw = "CANCEL NAVAREA III 0105/26 AND THIS PARAGRAPH."
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_cancel_this_paragraph_never_expires(self):
        raw = "CANCEL THIS PARAGRAPH 232359 UTC MAR 27."
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_no_dtg_after_and_this_msg(self):
        raw = "CANCEL NAVAREA VIII MSG 957/26, 1034/26 AND THIS MSG (.)"
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_no_year_fail_closed_even_with_year_argument(self):
        raw = ("2.  CANCEL NAVAREA VIII MSG 1097/26 AND THIS MSG "
               "131830 UTC NOV")
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_no_z_or_utc_fail_closed(self):
        raw = ("2.  CANCEL NAVAREA VIII MSG 1097/26 AND THIS MSG "
               "131830 NOV 26")
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_impossible_day_fail_closed(self):
        raw = ("2.  CANCEL NAVAREA VIII MSG 1097/26 AND THIS MSG "
               "321830 UTC NOV 26")
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))


class TestCombinedDatelineRegression(unittest.TestCase):
    def test_plain_self_cancel_dateline_wins(self):
        raw = "2. CANCEL THIS MSG 070001Z NOV 26." + chr(10) + COMBINED
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-11-07T00:01:00Z"))


VIII_COMBINED_BULLETIN = (
    "NAVAREA VIII - WARNINGS IN FORCE AS ON 02 NOV 2026\n"
    "NAVAREA VIII -1102/26 INDIA WEST COAST - KARWAR (.) CHARTS IN 215 257 "
    "INT 7343 (.) HYDROGRAPHIC SURVEY UNDER PROGRESS IN AREA BOUNDED WITHIN "
    "14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E 2. CANCEL NAVAREA VIII "
    "MSG 1097/26 AND THIS MSG 131830 UTC NOV 26 \n"
    "--------------------------------\n"
    "021102Z/NOV 26\n")


class TestCombinedEndToEndViii(unittest.TestCase):
    def test_viii_combined_bulletin(self):
        parsed = parse_viii(VIII_COMBINED_BULLETIN, now_utc=NOW)
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA VIII 1102/26")
        self.assertEqual(w["valid_to"], "2026-11-13T18:30:00Z")
        self.assertEqual(w["issued_text"], "021102Z/NOV 26")


if __name__ == "__main__":
    unittest.main()
