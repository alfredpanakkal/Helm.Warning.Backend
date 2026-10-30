#!/usr/bin/env python3
"""tests/test_step6_cosmetics.py — Step 6 audit fixes (F5 / F7 / F9).

Covers the three Step 6 findings from the 2026-10-30 audit:
  F7 — universal-parser titles cut at the first sentence boundary
       at/after 30 characters instead of running to the 255 cap;
  F5 — zone labels built from the source's own sub-area markers
       ('A' -> 'Area A', '1'..'3' -> 'Areas 1-3');
  F9 — NAVAREA IX .txt documents decoded as UTF-8 even when the
       response declares ISO-8859-1 (charset-less text/plain).
"""
import os
import sys
import unittest
from unittest import mock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_universal_parser import _zone_label, parse_bulletin_text
from scripts import navarea_ix_scraper as ix_mod


class TestTitleExtraction(unittest.TestCase):
    def _parse(self, text):
        data = parse_bulletin_text(text, "xi")
        self.assertEqual(len(data["nav_warnings"]), 1)
        return data["nav_warnings"][0]

    def test_short_opener_keeps_operation_sentence(self):
        text = ("NAVAREA XI 001/26" + chr(10)
                + "EAST CHINA SEA." + chr(10)
                + "HAZARD AREA DUE TO SPACE DEBRIS RE-ENTRY." + chr(10)
                + " 1. AREA BOUNDED BY 30-00N 140-00E" + chr(10))
        w = self._parse(text)
        self.assertEqual(
            w["title"],
            "EAST CHINA SEA. HAZARD AREA DUE TO SPACE DEBRIS RE-ENTRY.")

    def test_long_first_sentence_ends_title(self):
        text = ("NAVAREA XI 005/26" + chr(10)
                + "FIRING PRACTICE IN THE AREA BOUNDED BY THE COAST." + chr(10)
                + "FURTHER DETAILS AVAILABLE ON REQUEST." + chr(10)
                + " 1. 30-00N 140-00E" + chr(10))
        w = self._parse(text)
        self.assertEqual(w["title"],
                          "FIRING PRACTICE IN THE AREA BOUNDED BY THE COAST.")

    def test_no_sentence_boundary_keeps_whole_head(self):
        text = ("NAVAREA XI 006/26" + chr(10)
                + "SPECIAL PURPOSE VESSEL CONDUCTING CABLE RECOVERY" + chr(10)
                + "ALONG THE FOLLOWING LINE 30-00.0N 140-00.0E" + chr(10))
        w = self._parse(text)
        self.assertIn("CABLE RECOVERY", w["title"])
        self.assertIn("140-00.0E", w["title"])

    def test_empty_head_falls_back_to_region_title(self):
        text = ("NAVAREA XI 007/26" + chr(10)
                + " 1. FIRING AREA 30-00N 140-00E" + chr(10))
        w = self._parse(text)
        self.assertEqual(w["title"], "NAVAREA XI Warning")


class TestZoneLabels(unittest.TestCase):
    def test_unit_zone_label_rules(self):
        self.assertEqual(_zone_label([]), "Area")
        self.assertEqual(_zone_label([""]), "Area")
        self.assertEqual(_zone_label(["A"]), "Area A")
        self.assertEqual(_zone_label(["12"]), "Area 12")
        self.assertEqual(_zone_label(["NORTH RANGE"]), "NORTH RANGE")
        self.assertEqual(_zone_label(["A", "B", "C", "D"]), "Areas A-D")
        self.assertEqual(_zone_label(["1", "2", "3"]), "Areas 1-3")
        self.assertEqual(_zone_label(["A", "MIXED PROSE"]), "Areas")

    def test_lettered_polygons_get_lettered_zone_labels(self):
        text = ("NAVAREA XI 002/26" + chr(10)
                + "EAST CHINA SEA." + chr(10)
                + " 1. AREA BOUNDED BY" + chr(10)
                + "A. 30-00N 140-00E, 30-00N 141-00E, 31-00N 141-00E" + chr(10)
                + "B. 32-00N 140-00E, 32-00N 141-00E, 33-00N 141-00E" + chr(10)
                + "C. 34-00N 140-00E, 34-00N 141-00E, 35-00N 141-00E" + chr(10))
        data = parse_bulletin_text(text, "xi")
        w = data["nav_warnings"][0]
        labels = [f["properties"]["zone_label"]
                  for f in w["spatial"]["features"]]
        self.assertEqual(labels, ["Area A", "Area B", "Area C"])

    def test_numbered_points_get_single_range_label(self):
        text = ("NAVAREA XI 003/26" + chr(10)
                + "GULF." + chr(10)
                + " 1. 16-00.0N 082-00.0E" + chr(10)
                + " 2. 16-00.0N 083-00.0E" + chr(10)
                + " 3. 17-00.0N 083-00.0E" + chr(10))
        data = parse_bulletin_text(text, "xi")
        w = data["nav_warnings"][0]
        feats = w["spatial"]["features"]
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]["geometry"]["type"], "MultiPoint")
        self.assertEqual(feats[0]["properties"]["zone_label"], "Areas 1-3")

    def test_single_preamble_clause_keeps_area_label(self):
        text = ("NAVAREA XI 004/26" + chr(10)
                + "GULF OF OMAN." + chr(10)
                + "DRILLING IN 16-00.0N 082-00.0E" + chr(10))
        data = parse_bulletin_text(text, "xi")
        w = data["nav_warnings"][0]
        feats = w["spatial"]["features"]
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]["properties"]["zone_label"], "Area")


class TestIxFetchUtf8(unittest.TestCase):
    class _FakeResponse:
        def __init__(self, text, encoding, content=None):
            self.status_code = 200
            self.text = text
            self.encoding = encoding
            if content is not None:
                self.content = content

    def _fetch(self, resp):
        with mock.patch.object(ix_mod, "HAS_SCRAPLING", False), \
             mock.patch.object(ix_mod, "HAS_REQUESTS", True), \
             mock.patch.object(ix_mod.requests, "get",
                                return_value=resp):
            return ix_mod._fetch_once("http://x", {})

    def test_latin1_declared_utf8_content_decodes_utf8(self):
        utf8_body = "NAVAREA IX 050/26 — CAPE MOJIBAKÉ TEST".encode("utf-8")
        latin1_text = utf8_body.decode("iso-8859-1")
        resp = self._FakeResponse(latin1_text, "ISO-8859-1", utf8_body)
        text, status, retry = self._fetch(resp)
        self.assertEqual(status, 200)
        self.assertIn("CAPE MOJIBAKÉ TEST", text)
        self.assertNotIn("Ã©", text)

    def test_response_without_content_keeps_resp_text(self):
        resp = self._FakeResponse("PLAIN ASCII BODY", "")
        text, status, _ = self._fetch(resp)
        self.assertEqual(text, "PLAIN ASCII BODY")


if __name__ == "__main__":
    unittest.main()
