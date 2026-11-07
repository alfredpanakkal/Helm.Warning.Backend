#!/usr/bin/env python3
"""Tests for the trailing issue-DTG rule (NAVAREA IX / NAVTEX style).

Rule (Alfred, 2026-10-31): the issue date can come at the END of a
warning as a 'DDHHMM UTC MON YY' time group — '201400 UTC JUN 26'
means 20 JUN 2026, 14:00 UTC. The parser captures it verbatim as
issued_text, fail-closed against self-cancel datelines and validity
ranges (live fixture: NAVAREA IX 208/26 Strait of Hormuz advisory).
"""

import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_universal_parser import (
    parse_bulletin_text, _extract_issue_dtg)


IX_WARNING = """NAVAREA IX 208/26
PERSIAN GULF
STRAIT OF HORMUZ

1. SULTANATE OF OMAN ADVISORY. VESSELS PROCEED TO THE DESIGNATED
WAITING AREA WITHIN A 3 NM RADIUS OF POSITION 26-16.17N/055-46.52E.

2. EASTBOUND TRANSIT WAYPOINTS:
A. 26-02.72N 056-00.68E
B. 26-22.56N 056-16.93E
C. 26-24.35N 056-23.00E
D. 26-24.75N 056-31.11E
E. 26-22.10N 056-33.42E
F. 26-00.00N 056-33.30E

201400 UTC JUN 26"""


class TestTrailingIssueDtg(unittest.TestCase):
    def test_alfred_format_208_26(self):
        parsed = parse_bulletin_text(IX_WARNING, "ix")
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        warn = parsed["nav_warnings"][0]
        self.assertEqual(warn["canonical_id"], "NAVAREA IX 208/26")
        self.assertEqual(warn["issued_text"], "201400 UTC JUN 26")
        self.assertEqual(warn["valid_to"], None)

    def test_helper_direct(self):
        self.assertEqual(_extract_issue_dtg(IX_WARNING), "201400 UTC JUN 26")
        self.assertEqual(_extract_issue_dtg("X\n301200 UTC DEC 26"), "301200 UTC DEC 26")
        self.assertEqual(_extract_issue_dtg("X\n201400Z JUN 26"), "201400Z JUN 26")
        self.assertEqual(_extract_issue_dtg("X\n201400 UTC JUN 2026"), "201400 UTC JUN 2026")

    def test_self_cancel_dateline_not_issue_date(self):
        text = "NAVAREA IX 205/26\nEXERCISE AREA.\nCANCEL THIS WARNING 301200 UTC OCT 26\n"
        self.assertIsNone(_extract_issue_dtg(text))

    def test_validity_range_not_issue_date(self):
        text = "NAVAREA IX 206/26\nSURVEY.\n270300 UTC OCT 26 TO 090259 UTC NOV 26\n"
        self.assertIsNone(_extract_issue_dtg(text))

    def test_no_trailing_dtg(self):
        text = "NAVAREA IX 207/26\nGENERAL NOTICE.\n"
        self.assertIsNone(_extract_issue_dtg(text))

    def test_garbage_not_issue_date(self):
        self.assertIsNone(_extract_issue_dtg("X\n999999 UTC JUN 26"))
        self.assertIsNone(_extract_issue_dtg("X\n201400 UTC QUX 26"))


if __name__ == "__main__":
    unittest.main()
