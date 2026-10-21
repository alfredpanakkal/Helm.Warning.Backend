#!/usr/bin/env python3
"""test_navarea_xii_pipeline.py — NAVAREA XII scraper + parser tests.

Scraper: idempotency via IN FORCE DTG + checksum state.
Parser: segmentation → sub-area records → geometry via shared.utils (H05).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.navarea_xii_scraper import compute_state, should_process
from scripts.navarea_xii_parser import parse_memo, parse_warning
from shared.navarea_xii_text import split_into_warnings

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "navarea_xii")


def _load(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


class TestScraperIdempotency(unittest.TestCase):
    def setUp(self):
        self.memo = _load("daily_memo_snapshot.txt")
        self.state = compute_state(self.memo)

    def test_state_captures_dtg_and_checksum(self):
        self.assertEqual(self.state["in_force_dtg"], "051505Z MAR")
        self.assertEqual(len(self.state["memo_sha256"]), 64)

    def test_unchanged_memo_is_noop(self):
        self.assertFalse(should_process(self.memo, self.state))

    def test_changed_content_triggers_processing(self):
        edited = self.memo.replace("NAVAREA XII 151/26(18).", "NAVAREA XII 151/26(19).")
        self.assertTrue(should_process(edited, self.state))

    def test_no_state_processes(self):
        self.assertTrue(should_process(self.memo, None))

    def test_empty_memo_never_processes(self):
        self.assertFalse(should_process("", self.state))
        self.assertFalse(should_process("", None))


class TestParserMemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parse_memo(_load("daily_memo_snapshot.txt"))
        cls.by_key = {(w["warning_id"], w["sub_area"]): w for w in cls.parsed["nav_warnings"]}

    def test_record_counts(self):
        self.assertEqual(len(self.parsed["raw_messages"]), 32)

    def test_148_sub_area_records(self):
        a = self.by_key[("NAVAREA XII 148/26", "A")]
        b = self.by_key[("NAVAREA XII 148/26", "B")]
        self.assertEqual(len(a["coordinates"].split(", ")), 6)   # wrapped vertex recovered
        self.assertEqual(len(b["coordinates"].split(", ")), 7)
        self.assertEqual(a["spatial"]["type"], "Polygon")

    def test_151_three_sub_areas(self):
        for label in ("A", "B", "C"):
            self.assertIn(("NAVAREA XII 151/26", label), self.by_key)

    def test_150_header_cross_refs(self):
        refs = self.by_key[("NAVAREA XII 150/26", None)]["cross_refs"]
        header = [r for r in refs if r["kind"] == "header_ref"]
        self.assertEqual([(r["number"], r["year"]) for r in header], [("021", "26"), ("022", "26")])

    def test_142_cancellation_ref(self):
        refs = self.by_key[("NAVAREA XII 142/26", "A")]["cross_refs"]
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual([(r["number"], r["year"]) for r in cancels], [("127", "26")])

    def test_title_extraction(self):
        self.assertEqual(self.by_key[("NAVAREA XII 148/26", "A")]["title"], "NORTH PACIFIC., CALIFORNIA.")

    def test_dtg_attached_as_issued_text(self):
        self.assertEqual(self.by_key[("NAVAREA XII 151/26", "A")]["issued_text"], "040124Z MAR 26")

    def test_point_warning_single_record(self):
        rec = self.by_key[("NAVAREA XII 140/26", None)]
        self.assertEqual(rec["spatial"]["type"], "Point")
        self.assertEqual(rec["latitude"], 6.827166666666667)

    def test_statuses_active_and_categories_present(self):
        for w in self.parsed["nav_warnings"]:
            self.assertEqual(w["status"], "active")
            self.assertTrue(w["categories"])

    def test_spatial_features_mirror_records(self):
        self.assertEqual(len(self.parsed["spatial_features"]),
                         sum(1 for w in self.parsed["nav_warnings"] if w["spatial"]))


class TestParserH05Grounding(unittest.TestCase):
    """Every geometry record must derive from tokens that are exact substrings
    of the rejoined normalized text (AI fallback grounds against this text)."""

    @classmethod
    def setUpClass(cls):
        cls.memo = _load("daily_memo_snapshot.txt")
        cls.parsed = parse_memo(cls.memo)
        cls.blocks = {b["warning_id"]: b for b in split_into_warnings(cls.memo)}

    def test_coordinate_tokens_ground_in_normalized_text(self):
        for w in self.parsed["nav_warnings"]:
            normalized = self.blocks[w["warning_id"]]["raw_text"]
            if w["coordinates"]:
                for token in w["coordinates"].split(", "):
                    self.assertIn(token, normalized,
                                  f"{w['warning_id']}/{w['sub_area']}: {token} not grounded")

    def test_raw_block_is_verbatim_source_preserved(self):
        for rm in self.parsed["raw_messages"]:
            self.assertIn(rm["checksum_sha256"], {w["checksum_sha256"] for w in self.parsed["nav_warnings"]})


if __name__ == "__main__":
    unittest.main()
