#!/usr/bin/env python3
"""tests/test_navarea_x_scraper.py — NAVAREA X AMSA RCC publication scraper tests.

Reproduces the live AMSA.Web.MSIPublication/Home page structure in
miniature (page chrome, Part 1, Part 2 with two in-force warnings —
including the weekly in-force summary warning — Part 3 AUSCOAST blocks
(harvested separately as area-scoped pseudo-regions and never leaking
into the regional 'x' harvest), Part 4 tables) and verifies the
extract -> universal-parser chain end to end, offline, for both the
NAVAREA X and the AUSCOAST area harvests.
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_x_scraper import extract_message_text, extract_auscoast_areas
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
<p>AUSCOAST coastal warning - area C:<br>
SECURITE<br>
FM JRCC AUSTRALIA 291202Z JUN 26<br>
AUSCOAST WARNING 231/26<br>
1. . SPECIAL PURPOSE VESSEL RESPONDER / V7CY9 CONDUCTING CABLE LAYING OPERATIONS 5 NM EITHER SIDE OF A LINE JOINING<br>
A. 38-19.86S 144-19.61E<br>
B. 39-06.11S 145-33.18E<br>
2. 1.0NM CLEARANCE REQUESTED.<br>
SEE ALSO NAVAREA X 113/26.<br>
NNNN</p>
<p>AUSCOAST coastal warning - area D:<br>
SECURITE<br>
FM JRCC AUSTRALIA 291202Z JUN 26<br>
AUSCOAST WARNING 231/26<br>
1. . SPECIAL PURPOSE VESSEL RESPONDER / V7CY9 CONDUCTING CABLE LAYING OPERATIONS 5 NM EITHER SIDE OF A LINE JOINING<br>
A. 38-19.86S 144-19.61E<br>
2. 1.0NM CLEARANCE REQUESTED.<br>
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
        # Every message must start at its 'NAVAREA X nnn/yy' header: the
        # SECURITE/FM preamble is discarded by the parser anyway, and
        # keeping it would leak each message's preamble into the
        # PREVIOUS block's raw_text tail. Line-based assertions on
        # purpose: the raw HTML may or may not carry blank lines
        # between its <br>-separated message lines, and the harvest
        # contract must not depend on that layout.
        lines = [ln.strip() for ln in self.text.split("\n") if ln.strip()]
        self.assertEqual(lines[0], "NAVAREA X 113/26")
        self.assertEqual(lines.count("NAVAREA X 114/26"), 1)
        self.assertEqual(
            sum(1 for ln in lines if ln.startswith("NAVAREA X ")), 2)
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


class TestExtractAuscoastAreas(unittest.TestCase):
    def setUp(self):
        self.areas = extract_auscoast_areas(_MINI_HTML)

    def test_returns_one_bulletin_per_area_with_warnings(self):
        # Areas B, C and D carry warnings; the nil area A is omitted.
        self.assertEqual(sorted(self.areas), ["b", "c", "d"])

    def test_nil_area_is_omitted(self):
        self.assertNotIn("a", self.areas)

    def test_area_blocks_start_at_header_and_drop_preamble(self):
        lines = [ln.strip() for ln in self.areas["b"].split("\n") if ln.strip()]
        self.assertEqual(lines[0], "AUSCOAST WARNING 327/26")
        self.assertNotIn("SECURITE", self.areas["b"])
        self.assertNotIn("FM RCC AUSTRALIA", self.areas["b"])
        self.assertNotIn("NNNN", self.areas["b"])

    def test_same_number_in_two_areas_stays_two_harvests(self):
        # AMSA lists 231/26 under BOTH areas C and D: each area keeps its
        # own verbatim harvest (area-scoped pseudo-regions downstream).
        self.assertIn("AUSCOAST WARNING 231/26", self.areas["c"])
        self.assertIn("AUSCOAST WARNING 231/26", self.areas["d"])

    def test_fail_closed_on_missing_part4_anchor(self):
        broken = _MINI_HTML.replace("Part 4. Summary of Mobile Drilling Rigs:",
                                    "Part IV. Summary of Mobile Drilling Rigs:")
        with self.assertRaises(ValueError):
            extract_auscoast_areas(broken)

    def test_fail_closed_when_no_area_heading_survives(self):
        broken = _MINI_HTML.replace("AUSCOAST coastal warning - area",
                                    "Coastal warning - zone")
        with self.assertRaises(ValueError):
            extract_auscoast_areas(broken)

    def test_fail_closed_on_missing_part3_anchor(self):
        with self.assertRaises(ValueError):
            extract_auscoast_areas(_NO_PART3_HTML)

    def test_fail_closed_on_missing_part4_anchor_only(self):
        # Part 3 anchor present, Part 4 absent: unbounded slice refused.
        with self.assertRaises(ValueError):
            extract_auscoast_areas(_EMPTY_PART2_HTML)


class TestAuscoastUniversalParserIngestion(unittest.TestCase):
    def setUp(self):
        self.areas = extract_auscoast_areas(_MINI_HTML)
        self.parsed_b = parse_bulletin_text(self.areas["b"], "auscoast-b")
        self.parsed_c = parse_bulletin_text(self.areas["c"], "auscoast-c")
        self.parsed_d = parse_bulletin_text(self.areas["d"], "auscoast-d")

    def test_area_scoped_warning_ids(self):
        ids_b = [w["warning_id"] for w in self.parsed_b["nav_warnings"]]
        ids_c = [w["warning_id"] for w in self.parsed_c["nav_warnings"]]
        ids_d = [w["warning_id"] for w in self.parsed_d["nav_warnings"]]
        self.assertEqual(ids_b, ["AUSCOAST B 327/26"])
        self.assertEqual(ids_c, ["AUSCOAST C 231/26"])
        self.assertEqual(ids_d, ["AUSCOAST D 231/26"])

    def test_same_number_two_areas_two_distinct_warnings(self):
        self.assertNotEqual(self.parsed_c["nav_warnings"][0]["canonical_id"],
                            self.parsed_d["nav_warnings"][0]["canonical_id"])

    def test_source_and_navarea_labels(self):
        w = self.parsed_b["nav_warnings"][0]
        self.assertEqual(w["source_id"], "manual-auscoast-b")
        self.assertEqual(w["navarea"], "AUSCOAST B")
        self.assertEqual(self.parsed_b["memo"]["source_id"], "manual-auscoast-b")
        self.assertEqual(self.parsed_b["memo"]["navarea"], "AUSCOAST B")

    def test_point_warning_yields_geometry(self):
        # 19-55.47S 150-16.09E -> Point (-19.9245, 150.268167)
        w = self.parsed_b["nav_warnings"][0]
        self.assertIsNotNone(w["spatial"])
        from shared.utils import _extract_coord_pairs
        pairs = {(round(lat, 6), round(lon, 6))
                 for _kind, lat, lon, _canon in _extract_coord_pairs(w["raw_text"])}
        self.assertIn((-19.924500, 150.268167), pairs)

    def test_cable_line_area_yields_geometry(self):
        w = self.parsed_c["nav_warnings"][0]
        self.assertIsNotNone(w["spatial"])

    def test_navarea_x_cross_reference_never_splits_a_block(self):
        # Area C body carries 'SEE ALSO NAVAREA X 113/26.': the AUSCOAST
        # pseudo-region has no companion truncation and only AUSCOAST
        # headers start blocks — still exactly one warning.
        self.assertEqual(len(self.parsed_c["nav_warnings"]), 1)

    def test_raw_text_free_of_preamble_and_terminator(self):
        for parsed in (self.parsed_b, self.parsed_c, self.parsed_d):
            for w in parsed["nav_warnings"]:
                self.assertNotIn("SECURITE", w["raw_text"])
                self.assertNotIn("FM JRCC", w["raw_text"])
                self.assertNotIn("NNNN", w["raw_text"])


if __name__ == "__main__":
    unittest.main()
