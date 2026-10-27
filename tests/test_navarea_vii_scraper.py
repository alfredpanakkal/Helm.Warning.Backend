#!/usr/bin/env python3
"""tests/test_navarea_vii_scraper.py — NAVAREA VII SANHO scraper tests.

Reproduces the live SANHO page structure in miniature (nav junk before the
anchors, 'Nil Prior to these Messages' start marker, 'copyright' footer)
and verifies the extract -> universal-parser chain end to end, offline.
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_vii_scraper import extract_message_text
from scripts.navarea_universal_parser import parse_bulletin_text

# Miniature clone of the live SANHO page (verified 2026-10-27):
# navigation menu junk, the IMPORTANT disclaimer, the 'Nil Prior' anchor,
# bold block headers, lettered coordinate lists, a 'CANCEL NAVAREA VII ...
# OF 2025' cross-ref, and the copyright footer.
_MINI_HTML = """<html><body>
<ul><li>Home</li><li>Notices to Mariners</li><li>Full Catalogue</li></ul>
<h4>NAVAREA VII MESSAGES</h4>
<p><b>IMPORTANT :</b></p>
<p>This information is only updated during working hours 0730 -1600 Mon - Fri.</p>
<p>Nil Prior to these Messages</p>
<p><b>2026 Series</b></p>
<p><b>NAVAREA VII 014 OF 2026: (12 JAN 26)</b><br>
1. INDIAN OCEAN - SW SECTOR - PORT OF MAPUTO<br>
2. CHARTS BA644 (BAIA DE MAPUTO)<br>
3. FOLLOWING BUOYS OUT OF POSITION:<br>
A. STBD LATERAL BUOY NR 7, FL.G.4S MISSING<br>
B. BUOY 6N UNLIT AND OUT OF POSITION.<br>
4. VESSELS TO NAVIGATE WITH CAUTION<br>
5. CANCEL NAVAREA VII 374 OF 2025<br>
6. UNTIL FURTHER NOTICE</p>
<p><b>NAVAREA VII 271 OF 2026: (29 SEP 26)</b><br>
1. INDIAN OCEAN - SW SECTOR - MOZAMBIQUE CHANNEL<br>
2. CHART SAN 1<br>
3. ESTABLISHMENT OF MARITIME EXCLUSION ZONE BOUNDED BY FOLLOWING COORDINATES<br>
A. 10 - 31.52 S 040 - 42.53 E<br>
B. 10 - 31.45 S 040 - 54.59 E<br>
C. 10 - 45.55 S 040 - 54.68 E<br>
D. 10 - 45.62 S 040 - 42.61 E<br>
4. VESSELS TO NAVIGATE WITH CAUTION<br>
5. UNTIL FURTHER NOTICE</p>
<p>© copyright SAN 2020 | ^ back to top</p>
</body></html>
"""

# Same page but with the message region removed (layout change regression).
_EMPTY_HTML = """<html><body>
<ul><li>Home</li><li>Notices to Mariners</li></ul>
<p>Nil Prior to these Messages</p>
<p>© copyright SAN 2020</p>
</body></html>
"""


class TestExtractMessageText(unittest.TestCase):
    def setUp(self):
        self.text = extract_message_text(_MINI_HTML)

    def test_slices_out_nav_menu_and_footer(self):
        self.assertNotIn("Full Catalogue", self.text)
        self.assertNotIn("IMPORTANT", self.text)
        self.assertNotIn("copyright SAN", self.text)
        self.assertNotIn("Home", self.text)

    def test_keeps_block_headers_and_bodies(self):
        self.assertIn("NAVAREA VII 014 OF 2026: (12 JAN 26)", self.text)
        self.assertIn("NAVAREA VII 271 OF 2026: (29 SEP 26)", self.text)
        self.assertIn("PORT OF MAPUTO", self.text)
        self.assertIn("10 - 31.52 S 040 - 42.53 E", self.text)

    def test_nbsp_normalized(self):
        self.assertNotIn("\xa0", self.text)

    def test_fail_closed_on_headerless_page(self):
        with self.assertRaises(ValueError):
            extract_message_text(_EMPTY_HTML)


class TestUniversalParserIngestion(unittest.TestCase):
    def setUp(self):
        self.text = extract_message_text(_MINI_HTML)
        self.parsed = parse_bulletin_text(self.text, "vii")

    def test_exactly_two_warnings(self):
        self.assertEqual(len(self.parsed["nav_warnings"]), 2)

    def test_warning_ids_carry_the_block_numbers(self):
        ids = [w["warning_id"] for w in self.parsed["nav_warnings"]]
        self.assertTrue(any("014" in i for i in ids), ids)
        self.assertTrue(any("271" in i for i in ids), ids)

    def test_cancel_crossref_is_not_a_phantom_warning(self):
        ids = [w["warning_id"] for w in self.parsed["nav_warnings"]]
        self.assertFalse(any("374" in i for i in ids), ids)

    def test_exclusion_zone_yields_geometry(self):
        with_geom = [w for w in self.parsed["nav_warnings"] if w.get("spatial")]
        self.assertTrue(with_geom, "expected at least one warning with geometry")


if __name__ == "__main__":
    unittest.main()
