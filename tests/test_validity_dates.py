#!/usr/bin/env python3
"""
tests/test_validity_dates.py — Fail-closed validity-date extraction
regression suite (audit finding F1, 2026-10-29).

Every fixture below is a live warning from the DB audit: the universal
pipeline previously emitted NO validity dates (100% NULL valid_from /
valid_to on all 301 universal rows), so the expiry lifecycle could
never fire. Extraction must stay conservative: unparseable or absent
date evidence yields None, never a guess (hemisphere-safeguard
philosophy).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.navarea_universal_parser import _extract_validity_dates


class TestValidityRange(unittest.TestCase):
    def test_v0370_explicit_range_with_years(self):
        raw = ("UNDERWATER OPERATIONS 14 MAY 26 TO 14 NOV 26 BY USV "
               "FUGRO VAQUITA IN POSITIONS 22-03.00S 037-06.48W")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         ("2026-05-14", "2026-11-14"))

    def test_v0678_dtg_range_with_times(self):
        raw = ("UNDERWATER OPERATIONS DIVERS WORKING "
               "270300 UTC OCT 26 TO 090259 UTC NOV 26 BY SDSV SISTAC "
               "VITORIA IN 22-06.62S 039-54.93W")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         ("2026-10-27T03:00:00Z", "2026-11-09T02:59:00Z"))

    def test_yearless_range_rolls_over(self):
        raw = "OPERATIONS 16 OCT TO 14 JAN IN THE AREA."
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         ("2026-10-16", "2027-01-14"))

    def test_from_without_start_year_uses_warning_year(self):
        raw = "SURVEY FROM 08 OCT TO 10 NOV 26 IN AREA BOUND BY 1-00N 2-00E"
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         ("2026-10-08", "2026-11-10"))

    def test_time_range_without_months_no_match(self):
        # "0938Z TO 1302Z DAILY" is a daily time window, not a date range.
        raw = "HAZARDOUS OPERATIONS 0938Z TO 1302Z DAILY 10 THRU 13 MAR"
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_daily_time_then_month_range(self):
        # The time-only pair must not match; the later day-month range does.
        raw = ("GUNNERY. 2300Z TO 0900Z COMMENCING DAILY "
               "31 OCT TO 29 NOV. AREA BOUNDED BY 12-25.8N 116-36.6E")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         ("2026-10-31", "2026-11-29"))

    def test_day_only_range_not_matched(self):
        # Known limitation: day-only starts ("FROM 20 TO 31 OCT 26")
        # require a month on BOTH ends — fail closed rather than guess.
        raw = "MAINTENANCE FROM 20 TO 31 OCT 26 BY THE VESSEL."
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))


class TestCancelSelfDateline(unittest.TestCase):
    def test_v0336_cancel_dateline_only(self):
        raw = ("FISHING BOAT RIO AMAZONAS I WRECKED IN 23-49.29S 042-49.94W "
               "CANCEL THIS WARNING 232000 UTC NOV 26.")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-11-23T20:00:00Z"))

    def test_v0678_cancel_dateline_wins_over_range_end(self):
        raw = ("OPS 270300 UTC OCT 26 TO 090259 UTC NOV 26 "
               "CANCEL THIS WARNING 090400 UTC NOV 26.")
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         ("2026-10-27T03:00:00Z", "2026-11-09T04:00:00Z"))

    def test_cancel_msg_z_suffix_yearless(self):
        raw = "SPACE DEBRIS SUSPENDED. CANCEL THIS MSG 301000Z NOV."
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-11-30T10:00:00Z"))

    def test_cross_ref_is_not_a_dateline(self):
        # "CANCEL 0475/26 AND THIS MSG" is a cross-reference, not a
        # self-cancel dateline — must produce no dates.
        raw = "SPACE DEBRIS SUSPENDED." + chr(10) + "CANCEL 0475/26 AND THIS MSG."
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_no_year_hint_fail_closed(self):
        raw = "CANCEL THIS WARNING 232000 UTC NOV"
        self.assertEqual(_extract_validity_dates(raw, None), (None, None))


class TestUntilAndGuards(unittest.TestCase):
    def test_until_explicit_date(self):
        raw = "SURVEY WORKS UNTIL 31 DEC 2026 IN AREA BOUNDED BY 1-00N 2-00E"
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-12-31"))

    def test_until_further_notice_is_none(self):
        raw = "OPERATIONS UNTIL FURTHER NOTICE IN THE AREA."
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_impossible_day_rejected(self):
        raw = "CANCEL THIS WARNING 320000 UTC NOV 26."
        self.assertEqual(_extract_validity_dates(raw, "26"), (None, None))

    def test_unknown_month_rejected(self):
        raw = "OPS FROM 12 XYZ 26 TO 14 NOV 26."
        self.assertEqual(_extract_validity_dates(raw, "26"),
                         (None, "2026-11-14"))


if __name__ == "__main__":
    unittest.main()