#!/usr/bin/env python3
"""tests/test_navarea_x_scraper.py — NAVAREA X AMSA RCC publication scraper tests.

Reproduces the live AMSA.Web.MSIPublication/Home page structure in
miniature (page chrome, Part 1, Part 2 with two in-force warnings —
including the weekly in-force summary warning — Part 3 AUSCOAST blocks
that must never leak into the regional harvest, Part 4 tables) and
verifies the extract -> universal-parser chain end to end, offline.
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_x_scraper import extract_message_text
from scripts.navarea_universal_parser import parse_bulletin_text

# Miniature clone of the live publication page (verified 2026-10-27):
# header chrome, Part 1, Part 2 (the LAYLA cable-recovery warning with
# the live 'A.13-06.14S 161-11.58E' dot-prefixed DMM pairs + the weekly
# in-force summary warning), Part 3 AUSCOAST coastal warnings
# (Australian national warnings — must be sliced out), Part 4 tables.
_MINI_HTML = """<html><body>
<p>Maritime Safety Information current at 271826 UTC Oct 26</p>
<p>Issued by the Australian Maritime Safety Authority<br>
Rescue Coordination Centre (RCC Australia)</p>
<p>Part 1. Safety Messages:</p>
<p>Part 2. NAVAREA X warnings:</p>
<p>SECURITE<br>
FM JRCC AUSTRALIA 210029Z OCT 26<br>
NAVAREA X 113/26<br>
SPECIAL PURPOSE VESSEL LAYLA / V2YX9 / 304716000 CONDUCTING CABLE RECOVERY ALONG THE FOLLOWING LINE<br>
A.13-06.14S 161-11.58E<br>
B.12-23.69S 162-08.91E<br>
C.11-43.41S 163-07.90E<br>
D.10-50.91S 163-20.29E<br>
2.0NM&nbsp;CLEARANCE REQUESTED.<br>
NNNN</p>
<p>SECURITE<br>
FM JRCC AUSTRALIA 220000Z OCT 26<br>
NAVAREA X 114/26<br>
1. NAVAREA X WARNINGS IN FORCE AT 220000 UTC OCT 26<br>
113/26, 114/26<br>
2. AUSCOAST WARNINGS IN FORCE AT 220000 UTC OCT 26<br>
AREA A 324/26, 325/26<br>
3. COMPLETE TEXTS OF ALL WARNINGS IN FORCE ARE AVAILABLE FROM WEBSITE WWW.AMSA.GOV.AU.<br>
4. CANCEL THIS MESSAGE 290000 UTC OCT 26<br>
NNNN</p>
<p>Part 3. Coastal warnings:</p>
<p>AUSCOAST coastal warning - area A: nil</p>
<p>AUSCOAST coastal warning - area B:<br>
SECURITE<br>
FM RCC AUSTRALIA 170642Z OCT 26<br>
AUSCOAST WARNING 327/26<br>
WHITE TIP REEF (MAIN &amp; REAR) LIGHT K3054.1 IN POSITION 19-55.47S 150-16.09E<br>
UNRELIABLE<br>
NNNN</p>
<p>Part 4. Summary of Mobile Drilling Rigs:</p>
<table><tr><td>JANSZ FCS</td><td>AXA001</td><td>19 52.7S 114 36.5E</td></tr></table>
</body></html>
"""

# Live quirk (verified 2026-10-27): AMSA escapes some periods as '1\.'
# inside the weekly summary body. The extractor passes text through
# verbatim, so the bulletin must carry the escape untouched.
_MINI_HTML_ESCAPED = _MINI_HTML.replace(
    "1. NAVAREA X WARNINGS", "1" + chr(92) + ". NAVAREA X WARNINGS")

# Layout-change regressions (fail-closed: every variant must raise).
_NO_PART2_HTML = _MINI_HTML.replace("Part 2. NAVAREA X warnings:",
                                    "Part 2. Notices:")
_NO_PART3_HTML = _MINI_HTML.replace("Part 3. Coastal warnings:",
                                    "Part 3. More coastal warnings:")
_EMPTY_PART2_HTML = """<html><body>
<p>Part 2. NAVAREA X warnings:</p>
<p>NIL.</p>
<p>Part 3. Coastal warnings:</p>
</body></html>
"""


class TestExtractMessageText(unittest.TestCase):
    def setUp(self):
        self.text = extract_message_text(_MINI_HTML)

    def test_slices_out_page_chrome_and_other_parts(self):
        self.assertNotIn("Maritime Safety Information current", self.text)
        self.assertNotIn("Rescue Coordination Centre", self.text)
        self.assertNotIn("Part 1", self.text)
        self.assertNotIn("Part 3", self.text)
        self.assertNotIn("Part 4", self.text)
        self.assertNotIn("JANSZ FCS", self.text)

    def test_auscoast_coastal_warnings_never_leak(self):
        # AUSCOAST warnings are Australian national warnings outside
        # NAVAREA numbering: they must never enter the region 'x' harvest.
        self.assertNotIn("AUSCOAST WARNING 327/26", self.text)
        self.assertNotIn("WHITE TIP REEF", self.text)
        self.assertNotIn("19-55.47S", self.text)

    def test_keeps_warning_headers_and_bodies(self):
        self.assertIn("NAVAREA X 113/26", self.text)
        self.assertIn("NAVAREA X 114/26", self.text)
        self.assertIn("SPECIAL PURPOSE VESSEL LAYLA", self.text)
        self.assertIn("A.13-06.14S 161-11.58E", self.text)
        self.assertIn("COMPLETE TEXTS OF ALL WARNINGS IN FORCE", self.text)

    def test_blocks_start_at_header_and_drop_preamble(self):
        # Every block must start at its 'NAVAREA X nnn/yy' header: the
        # SECURITE/FM preamble is discarded by the parser anyway, and
        # keeping it would leak each message's preamble into the
        # PREVIOUS block's raw_text tail.
        blocks = self.text.split("\n\n")
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].startswith("NAVAREA X 113/26\n"), repr(blocks[0][:60]))
        self.assertTrue(blocks[1].startswith("NAVAREA X 114/26\n"), repr(blocks[1][:60]))
        self.assertNotIn("SECURITE", self.text)
        self.assertNotIn("FM JRCC", self.text)
        self.assertNotIn("NNNN", self.text)

    def test_nbsp_normalized(self):
        self.assertNotIn("\xa0", self.text)
        self.assertIn("2.0NM CLEARANCE REQUESTED.", self.text)

    def test_escaped_dot_live_quirk_passes_through_verbatim(self):
        bulletin = extract_message_text(_MINI_HTML_ESCAPED)
        self.assertIn("1" + chr(92) + ". NAVAREA X WARNINGS", bulletin)

    def test_fail_closed_on_missing_part2_anchor(self):
        with self.assertRaises(ValueError):
            extract_message_text(_NO_PART2_HTML)

    def test_fail_closed_on_missing_part3_anchor(self):
        # Without the Part 3 anchor the AUSCOAST blocks would leak into
        # the harvest: the slice must refuse to run unbounded.
        with self.assertRaises(ValueError):
            extract_message_text(_NO_PART3_HTML)

    def test_fail_closed_on_empty_part2(self):
        with self.assertRaises(ValueError):
            extract_message_text(_EMPTY_PART2_HTML)


class TestUniversalParserIngestion(unittest.TestCase):
    def setUp(self):
        self.bulletin = extract_message_text(_MINI_HTML)
        self.parsed = parse_bulletin_text(self.bulletin, "x")

    def by_id(self, warning_id):
        for w in self.parsed["nav_warnings"]:
            if w["warning_id"] == warning_id:
                return w
        raise AssertionError(warning_id + " not parsed; got "
                             + str([w["warning_id"] for w in self.parsed["nav_warnings"]]))

    def test_exactly_two_warnings(self):
        self.assertEqual(len(self.parsed["nav_warnings"]), 2)

    def test_warning_ids_carry_the_block_numbers(self):
        ids = [w["warning_id"] for w in self.parsed["nav_warnings"]]
        self.assertIn("NAVAREA X 113/26", ids)
        self.assertIn("NAVAREA X 114/26", ids)

    def test_in_force_summary_lines_do_not_split_a_phantom_warning(self):
        # '1. NAVAREA X WARNINGS IN FORCE AT 220000 UTC OCT 26' carries no
        # n/yy token: it must never act as a header (no third warning).
        self.assertEqual(len(self.parsed["nav_warnings"]), 2)

    def test_layla_cable_line_yields_geometry(self):
        w = self.by_id("NAVAREA X 113/26")
        self.assertIsNotNone(w["spatial"], "expected geometry for the cable line")
        from shared.utils import _extract_coord_pairs
        pairs = {(round(lat, 6), round(lon, 6))
                 for _kind, lat, lon, _canon in _extract_coord_pairs(w["raw_text"])}
        self.assertIn((-13.102333, 161.193), pairs)   # A.13-06.14S 161-11.58E
        self.assertIn((-10.8485, 163.338167), pairs)   # D.10-50.91S 163-20.29E

    def test_raw_text_free_of_preamble_and_terminator(self):
        for w in self.parsed["nav_warnings"]:
            self.assertNotIn("SECURITE", w["raw_text"])
            self.assertNotIn("FM JRCC", w["raw_text"])
            self.assertNotIn("NNNN", w["raw_text"])

    def test_next_message_preamble_never_leaks_into_previous_block(self):
        w = self.by_id("NAVAREA X 113/26")
        self.assertNotIn("FM JRCC AUSTRALIA 220000Z", w["raw_text"])

    def test_summary_warning_fails_closed_without_geometry(self):
        summary = self.by_id("NAVAREA X 114/26")
        self.assertIsNone(summary["spatial"])

    def test_title_keeps_the_warning_subject(self):
        w = self.by_id("NAVAREA X 113/26")
        self.assertIn("SPECIAL PURPOSE VESSEL LAYLA", w["title"])


if __name__ == "__main__":
    unittest.main()
