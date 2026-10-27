#!/usr/bin/env python3
"""tests/test_navarea_iii_scraper.py — NAVAREA III IHM XML scraper tests.

Reproduces the two live IHM crudo-XML malformations verified 2026-10-27
(stray CR/LF inside <NAVAREASVIGOR> tag names) and verifies the
synthesize -> universal-parser chain end to end, offline.
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_iii_scraper import (
    parse_xml_records,
    synthesize_bulletin,
    _repair_ihm_tag_names,
)
from shared.navarea_universal_text import warning_header_re
from scripts.navarea_universal_parser import parse_bulletin_text

# Miniature clone of the live IHM file: newest-last document order,
# one opening tag name split across lines ('<NAVAR<newline>EASVIGOR>'),
# one closing tag with a stray newline before '>' ('</NAVAREASVIGOR<newline>>'),
# and one record missing the English text (must be skipped loudly).
_MINI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<dataroot xmlns:od="urn:schemas-microsoft-com:officedata" generated="2026-10-27T09:42:28">
  <NAVAREASVIGOR>
    <nnuna>220092</nnuna>
    <nnunaf>0092/22</nnunaf>
    <nfemi>2022-02-25T00:00:00</nfemi>
    <nlocae>MAR NEGRO NOROCCIDENTAL</nlocae>
    <nlocai>BLACK SEA NORTHWESTERN PART</nlocai>
    <ntees>SPANISH TEXT</ntees>
    <ntein>1.- DUE TO MINE DANGER NAVIGATION PROHIBITED IN AREA BOUNDED BY:
46-04.0N   033-12.8E
46-03.1N   033-13.9E
46-05.0N   033-15.0E</ntein>
    <nasun>ZONA DE MINAS</nasun>
    <nasuni>MINES AREA</nasuni>
  </NAVAREASVIGOR>
  <NAVAR
EASVIGOR>
    <nnuna>240034</nnuna>
    <nnunaf>0034/24</nnunaf>
    <nfemi>2024-04-02T00:00:00</nfemi>
    <nlocae>MAR NEGRO</nlocae>
    <nlocai>BLACK SEA</nlocai>
    <ntees>1. ZONA DE RIESGO DE GUERRA, AL NORTE DE LA LINEA
45-12.2N 029-41.1E
45-11.5N 029-41.4E</ntees>
    <ntein>1. WAR RISK AREA, IN NORTHWESTERN PART OF BLACK SEA TO NORTHERN OF LINE
45-12.2N  029-41.1E
45-11.5N  029-41.4E
2.- CANCEL NAVAREA III 0119/22 AND THIS PARAGRAPH</ntein>
    <nasun>AREA DE RIESGO DE GUERRA</nasun>
    <nasuni>WAR RISK AREA</nasuni>
  </NAVAREASVIGOR
>
  <NAVAREASVIGOR>
    <nnuna>260100</nnuna>
    <nnunaf>0100/26</nnunaf>
    <nfemi>2026-06-27T00:00:00</nfemi>
    <nlocae>MAR MEDITERRANEO OCCIDENTAL</nlocae>
    <nlocai>WESTERN MEDITERRANEAN SEA</nlocai>
    <ntein>DRIFTING TARGET SHOOTING EXERCISE
NAVIGATION EXCLUSION AREA DELIMITED BY:
38-30.60N 000-30.80E
38-35.50N 000-46.40E
37-52.25N 000-06.55E
CANCEL THIS MSG 310100 UTC OCT 26.</ntein>
    <nasun>EJERCICIO DE TIRO</nasun>
    <nasuni>DRIFTING TARGET FIRING EXERCISE</nasuni>
  </NAVAREASVIGOR>
  <NAVAREASVIGOR>
    <nnuna>260111</nnuna>
    <nnunaf>0111/26</nnunaf>
    <nfemi>2026-06-27T00:00:00</nfemi>
    <nlocae>SIN TEXTO</nlocae>
    <nlocai>NO ENGLISH TEXT</nlocai>
    <ntees>SOLO ESPANOL</ntees>
    <nasuni>SIN TEXTO</nasuni>
  </NAVAREASVIGOR>
</dataroot>
"""


class TestIhmXmlRepair(unittest.TestCase):
    def test_repair_collapses_whitespace_inside_tag_names(self):
        repaired = _repair_ihm_tag_names(_MINI_XML)
        self.assertNotIn("<NAVAR\n", repaired)
        self.assertIn("<NAVAREASVIGOR>", repaired)
        self.assertNotIn("</NAVAREASVIGOR\n>", repaired)
        # Attribute-bearing tags must survive untouched.
        self.assertIn('xmlns:od="urn:schemas-microsoft-com:officedata"', repaired)


class TestParseRecords(unittest.TestCase):
    def setUp(self):
        self.records = parse_xml_records(_repair_ihm_tag_names(_MINI_XML))

    def test_extracts_all_records_despite_malformed_tags(self):
        numbers = [r["number"] for r in self.records]
        self.assertEqual(numbers, ["0100/26", "0034/24", "0092/22"])

    def test_skips_records_without_english_text(self):
        self.assertNotIn("0111/26", [r["number"] for r in self.records])

    def test_english_fields_only(self):
        rec = self.records[0]
        self.assertEqual(rec["area"], "WESTERN MEDITERRANEAN SEA")
        self.assertEqual(rec["subject"], "DRIFTING TARGET FIRING EXERCISE")
        self.assertIn("DRIFTING TARGET SHOOTING EXERCISE", rec["text"])
        self.assertEqual(rec["issued"], "2026-06-27T00:00:00")


class TestSynthesizedBulletin(unittest.TestCase):
    def setUp(self):
        records = parse_xml_records(_repair_ihm_tag_names(_MINI_XML))
        self.bulletin = synthesize_bulletin(records)

    def test_every_block_matches_the_region_iii_header_regex(self):
        header_re = warning_header_re("III")
        matches = [
            m for m in header_re.finditer(self.bulletin)
            if "CANCEL" not in self.bulletin[max(0, m.start() - 8):m.start()].upper()
        ]
        self.assertEqual(len(matches), 3)
        self.assertEqual([m.group(1) for m in matches], ["0100", "0034", "0092"])

    def test_block_layout_matches_fixture_format(self):
        first = self.bulletin.split("\n\n\n")[0]
        lines = first.split("\n")
        self.assertEqual(lines[0], "NAVAREA III - 0100/26")
        self.assertEqual(lines[1], "27 June 2026 00:00 UTC")
        self.assertEqual(lines[2], "WESTERN MEDITERRANEAN SEA")
        self.assertEqual(lines[3], "DRIFTING TARGET FIRING EXERCISE")

    def test_universal_parser_ingests_the_bulletin(self):
        parsed = parse_bulletin_text(self.bulletin, "iii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertEqual(len(ids), 3)
        self.assertIn("NAVAREA III 0100/26", ids)
        self.assertIn("NAVAREA III 0034/24", ids)
        self.assertIn("NAVAREA III 0092/22", ids)
        # The CANCEL cross-ref must never have split a block.
        self.assertNotIn("NAVAREA III 0119/22", ids)
        # The bounded-by mine area must yield geometry (rule parser).
        with_geom = [w for w in parsed["nav_warnings"] if w.get("spatial")]
        self.assertTrue(with_geom, "expected at least one warning with geometry")


if __name__ == "__main__":
    unittest.main()
