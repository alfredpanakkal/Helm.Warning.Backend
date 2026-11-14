#!/usr/bin/env python3
"""tests/test_issue_dtg.py - Shared issue-DTG extractor + conversion tests.

Covers the deterministic, fail-closed extract_issue_dtg() helper in
shared/models.py: whole-line time groups at the first/last non-empty
line, BOM/dash stripping, explicit month dict (3-letter + full English
names), calendar-existence checks, keyword guards, both-ends-conflict
fail-closed, and the conversion through parse_safe_iso_timestamp() /
build_master_payload().

Positive fixtures are VERBATIM from live DB rows (NAVAREA VIII 1155/26,
1173/26, 1144/26, 1001/26, 713/26, 499/26, 664/26; NGA memo DTG lines;
NAVTEX trailing groups). Nothing is invented.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.models import (
    extract_issue_dtg,
    parse_safe_iso_timestamp,
    build_master_payload,
)

BOM = "\ufeff"


class TestExtractPositive(unittest.TestCase):
    """extract_issue_dtg() returns the matched token verbatim; ISO
    values are asserted through parse_safe_iso_timestamp() below."""

    def test_nga_memo_space_form(self):
        raw = "301639Z OCT 26\nNAVAREA IV 1045/26.\nBODY TEXT."
        self.assertEqual(extract_issue_dtg(raw), "301639Z OCT 26")

    def test_navtex_utc_form(self):
        raw = "NAVAREA IX 430/26\n\nBUOY RESTORED (.)\n\n051500 UTC NOV 2026"
        self.assertEqual(extract_issue_dtg(raw), "051500 UTC NOV 2026")

    def test_full_month_name(self):
        raw = "071500 UTC JUNE 2022"
        self.assertEqual(extract_issue_dtg(raw), "071500 UTC JUNE 2022")

    def test_viii_slash_form_own_line(self):
        # NAVAREA VIII 1155/26 tail (live): dashes line + DTG last line.
        raw = "NAVAREA VIII -1155/26\n------------\n021102Z/NOV 26"
        self.assertEqual(extract_issue_dtg(raw), "021102Z/NOV 26")

    def test_viii_slash_form_dashes_same_line(self):
        # NAVAREA VIII 1001/26 tail (live): dashes and DTG on one line.
        raw = "NAVAREA VIII -1001/26\n----------------------------------------- --  271002Z/SEP 26"
        self.assertEqual(extract_issue_dtg(raw), "271002Z/SEP 26")

    def test_bom_prefixed_line(self):
        raw = BOM + "031500 UTC SEP 24"
        self.assertEqual(extract_issue_dtg(raw), "031500 UTC SEP 24")


class TestExtractNegative(unittest.TestCase):
    def _raw(self, tail):
        return "NAVAREA X 1/26\nBODY TEXT.\n" + tail

    def test_cancel_line_rejected(self):
        self.assertIsNone(extract_issue_dtg(
            self._raw("2. CANCEL THIS MSG 010001Z DEC 26.")))

    def test_validity_range_rejected(self):
        self.assertIsNone(extract_issue_dtg(
            self._raw("290301 UTC OCT 26 TO 060301 UTC NOV 26")))

    def test_time_group_in_sentence_rejected(self):
        self.assertIsNone(extract_issue_dtg(
            self._raw("070500 UTC NOV 26 IN AREA BOUNDED BY 00-31.43N 090-19.42E")))

    def test_missing_z_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("061500 FEB 26")))

    def test_missing_year_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("231157 UTC OCT")))

    def test_slash_form_missing_year_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("021102Z/NOV")))

    def test_bulletin_in_force_line_rejected(self):
        self.assertIsNone(extract_issue_dtg(
            "1. NAVAREA I WARNINGS IN FORCE AT 061000 UTC NOV 2026:"))

    def test_impossible_calendar_date_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("300102Z FEB 26")))

    def test_impossible_day_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("321102Z NOV 26")))

    def test_impossible_hour_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("012502Z NOV 26")))

    def test_unknown_month_rejected(self):
        self.assertIsNone(extract_issue_dtg(self._raw("301639Z XYZ 26")))

    def test_both_ends_disagree_returns_none(self):
        raw = "301639Z OCT 26\nBODY TEXT.\n051500 UTC NOV 2026"
        self.assertIsNone(extract_issue_dtg(raw))

    def test_both_ends_agree_returns_token(self):
        raw = "301639Z OCT 26\nBODY TEXT.\n301639Z OCT 26"
        self.assertEqual(extract_issue_dtg(raw), "301639Z OCT 26")

    def test_no_dtg_block_returns_none(self):
        self.assertIsNone(extract_issue_dtg("NAVAREA X 1/26\nJUST SOME BODY TEXT."))


class TestConversion(unittest.TestCase):
    def test_nga_memo_space_form(self):
        self.assertEqual(
            parse_safe_iso_timestamp("301639Z OCT 26"), "2026-10-30T16:39:00")

    def test_navtex_utc_form(self):
        self.assertEqual(
            parse_safe_iso_timestamp("051500 UTC NOV 2026"), "2026-11-05T15:00:00")

    def test_full_month_name(self):
        self.assertEqual(
            parse_safe_iso_timestamp("071500 UTC JUNE 2022"), "2022-06-07T15:00:00")

    def test_viii_slash_tokens(self):
        self.assertEqual(
            parse_safe_iso_timestamp("021102Z/NOV 26"), "2026-11-02T11:02:00")
        self.assertEqual(
            parse_safe_iso_timestamp("061101Z/NOV 26"), "2026-11-06T11:01:00")
        self.assertEqual(
            parse_safe_iso_timestamp("301102Z/OCT 26"), "2026-10-30T11:02:00")

    def test_dashes_same_line_token(self):
        self.assertEqual(
            parse_safe_iso_timestamp("271002Z/SEP 26"), "2026-09-27T10:02:00")

    def test_bom_prefixed_token(self):
        self.assertEqual(
            parse_safe_iso_timestamp(BOM + "031500 UTC SEP 24"), "2024-09-03T15:00:00")

    def test_existing_formats_untouched(self):
        self.assertEqual(
            parse_safe_iso_timestamp("030020Z JUL 26"), "2026-07-03T00:20:00")
        self.assertEqual(
            parse_safe_iso_timestamp("2026-10-30T16:39:00Z"), "2026-10-30T16:39:00+00:00")
        self.assertIsNone(parse_safe_iso_timestamp("UNTIL FURTHER NOTICE"))


class TestEndToEnd(unittest.TestCase):
    def test_viii_block_issue_date_is_not_validity(self):
        block = ("NAVAREA VIII -1155/26\nVAKALPUDI NAVTEX STATION OFF AIR\n-------\n021102Z/NOV 26")
        record = {
            "warning_id": "1155/26",
            "navarea": "VIII",
            "title": "VAKALPUDI NAVTEX STATION OFF AIR",
            "raw_text": block,
            "source_id": "nho-navarea-viii",
            "issued_text": extract_issue_dtg(block),
        }
        master = build_master_payload(record)
        self.assertEqual(master["issued_at"], "2026-11-02T11:02:00+00:00")
        self.assertIsNone(master["valid_from"])
        self.assertNotIn("issued_text", master)

    def test_labelled_header_date_populates_issued_at(self):
        raw = "NO.26-0504 Date:2026/11/09 12 UTC\\nAREA BOUNDED BY ..."
        master = build_master_payload({
            "warning_id": "0504/26",
            "navarea": "XI",
            "title": "SPACE DEBRIS",
            "raw_text": raw,
            "source_id": "kaiho-navarea-xi",
        })
        self.assertEqual(master["issued_at"], "2026-11-09T12:00:00+00:00")
        self.assertIsNone(master["valid_from"])
        self.assertIsNone(master["area_text"])

    def test_invalid_labelled_header_date_is_rejected(self):
        raw = "NO.26-0504 Date:2026/02/30 12 UTC\\nBODY"
        master = build_master_payload({
            "warning_id": "0504/26", "navarea": "XI", "raw_text": raw,
        })
        self.assertIsNone(master["issued_at"])

    def test_no_dtg_block_stays_none(self):
        record = {
            "warning_id": "1/26",
            "navarea": "X",
            "title": "T",
            "raw_text": "NAVAREA X 1/26\nJUST SOME BODY TEXT.",
            "source_id": "manual-navarea-x",
            "issued_text": None,
        }
        master = build_master_payload(record)
        self.assertIsNone(master["valid_from"])


if __name__ == "__main__":
    unittest.main()
