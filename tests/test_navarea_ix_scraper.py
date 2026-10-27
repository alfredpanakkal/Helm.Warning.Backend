#!/usr/bin/env python3
"""tests/test_navarea_ix_scraper.py — NAVAREA IX NHO Pakistan scraper tests.

Reproduces the live NHO page structure in miniature (nav menu, intro
prose, the 6-column metadata table with 'View Document' anchors) and
verifies the extract -> fetch -> concatenate -> universal-parser chain
end to end, offline, with an injected document fetcher.
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_ix_scraper import assemble_bulletin, extract_rows
from scripts.navarea_universal_parser import parse_bulletin_text

_BASE = ("https://hydrography.paknavy.gov.pk/wp-content/plugins/"
         "navarea-warnings/custom_uploaded_warnings_for_navarea/")

# Miniature clone of the live page (verified 2026-10-27): a real data
# row (412/26), a pure self-cancel row (410/26), and a row whose
# ATTACHMENT cell lost its link (378/26 — its DTG cell is malformed on
# the live page too). The linked files mirror the live plain-text
# documents: DTG line, 'NAVAREA IX nnn/yy' header, region / area /
# charts lines, numbered paragraphs.
_MINI_HTML = """<html><body>
<ul><li>Home</li><li>NAVAREA IX WARNINGS</li></ul>
<p>Hydrographer of Pakistan (HoP) leads both HQ NAVAREA IX ...</p>
<table>
<thead><tr><th>S.NO</th><th>REGION/AREA</th><th>DTG</th>
<th>WARNING #</th><th>DESCRIPTION</th><th>ATTACHMENT</th></tr></thead>
<tbody>
<tr><td>1</td><td>CENTRAL GULF/QATAR</td><td>271500 UTC OCT 2026</td>
<td>412/26</td><td>TOWING OPERATION</td>
<td><a href="__BASE__20261027SEC%20412.txt">View Document</a></td></tr>
<tr><td>3</td><td>NAVAREA IX</td><td>271500 UTC OCT 2026</td>
<td>410/26</td><td>SELF CANCELING</td>
<td><a href="__BASE__20261027SEC%20410.txt">View Document</a></td></tr>
<tr><td>16</td><td>NORTHERN GULF KUWAIT</td>
<td>NORTHERN GULF KUWAIT</td><td>378/26</td>
<td>BATHYMETRIC SURVEY</td><td>View Document</td></tr>
</tbody>
</table>
</body></html>""".replace("__BASE__", _BASE)

_DOC_412 = (
    "271500 UTC OCT 2026\r\n"
    "NAVAREA IX 412/26\r\n"
    "CENTRAL GULF\r\n"
    "QATAR\r\n"
    "CHARTS BA 2523, 2886, 3783, 3787 AND 3950\r\n"
    "\r\n"
    "1. TOWING OF 350 METERS FLOATING HOSE IN PROGRESS BY\r\n"
    "VESSEL AHTS ACCOMPLISH FROM 26-35.34N 052-02.17E\r\n"
    "TO 24-57.42N 051-35.59E (.) MARINERS CAUTIONED\r\n"
    "\r\n"
    "2. CANCEL THIS MSG 282300 UTC OCT 26 \r\n"
)

_DOC_410 = (
    "271500 UTC OCT 2026\r\n"
    "NAVAREA IX 410/26\r\n"
    "\r\n"
    "CANCEL NAVAREA IX 373/26,\r\n"
    "403/26, 404/26 AND THIS MSG\r\n"
)

_FAKE_DOCS = {
    _BASE + "20261027SEC%20412.txt": _DOC_412,
    _BASE + "20261027SEC%20410.txt": _DOC_410,
}

# Same table with the message rows removed (layout change regression).
_EMPTY_HTML = """<html><body>
<ul><li>Home</li></ul>
<table><thead><tr><th>S.NO</th><th>REGION/AREA</th><th>DTG</th>
<th>WARNING #</th><th>DESCRIPTION</th><th>ATTACHMENT</th></tr></thead>
<tbody></tbody></table>
</body></html>"""


def _fake_fetch(href):
    return _FAKE_DOCS.get(href)


class TestExtractRows(unittest.TestCase):
    def test_extracts_linked_warning_rows(self):
        rows = extract_rows(_MINI_HTML)
        self.assertEqual([(r[0], r[1]) for r in rows],
                         [("412", "26"), ("410", "26")])
        self.assertTrue(all(r[2].startswith(_BASE) for r in rows), rows)

    def test_row_without_link_is_skipped(self):
        rows = extract_rows(_MINI_HTML)
        self.assertFalse(any(r[0] == "378" for r in rows), rows)

    def test_empty_table_yields_no_rows(self):
        self.assertEqual(extract_rows(_EMPTY_HTML), [])


class TestAssembleBulletin(unittest.TestCase):
    def test_concatenates_documents_in_table_order(self):
        rows = extract_rows(_MINI_HTML)
        bulletin = assemble_bulletin(rows, _fake_fetch)
        self.assertIsNotNone(bulletin)
        self.assertIn("NAVAREA IX 412/26", bulletin)
        self.assertIn("NAVAREA IX 410/26", bulletin)
        self.assertLess(bulletin.index("412/26"), bulletin.index("410/26"))

    def test_crlf_normalized_and_lines_trimmed(self):
        rows = extract_rows(_MINI_HTML)
        bulletin = assemble_bulletin(rows, _fake_fetch)
        self.assertNotIn("\r", bulletin)

    def test_fail_closed_when_a_document_is_unreachable(self):
        rows = extract_rows(_MINI_HTML)
        self.assertIsNone(assemble_bulletin(rows, lambda href: None))

    def test_fail_closed_when_document_is_the_wrong_warning(self):
        rows = extract_rows(_MINI_HTML)
        self.assertIsNone(assemble_bulletin(rows, lambda href: _DOC_410))


class TestUniversalParserIngestion(unittest.TestCase):
    def setUp(self):
        rows = extract_rows(_MINI_HTML)
        self.parsed = parse_bulletin_text(
            assemble_bulletin(rows, _fake_fetch), "ix")

    def test_exactly_two_warnings(self):
        self.assertEqual(len(self.parsed["nav_warnings"]), 2)

    def test_warning_ids_carry_the_block_numbers(self):
        ids = [w["warning_id"] for w in self.parsed["nav_warnings"]]
        self.assertTrue(any("412" in i for i in ids), ids)
        self.assertTrue(any("410" in i for i in ids), ids)

    def test_cancel_crossref_is_not_a_phantom_warning(self):
        ids = [w["warning_id"] for w in self.parsed["nav_warnings"]]
        self.assertFalse(any("373" in i for i in ids), ids)

    def test_towing_operation_yields_geometry(self):
        with_geom = [w for w in self.parsed["nav_warnings"] if w.get("spatial")]
        self.assertTrue(with_geom, "expected at least one warning with geometry")


if __name__ == "__main__":
    unittest.main()
