#!/usr/bin/env python3
"""
tests/test_navarea_1_companion.py — NAVAREA I companion exception.

NAVAREA XIX publishers (Norway) routinely bundle NAVAREA I (UK / North
Atlantic) warnings. Regression tests for the 2026-10-23 queue failure:
"mixed-region paste: input path targets NAVAREA XIX but the text contains
warning headers for I."

Contract:
  - NAVAREA I headers never make a universal paste mixed-region.
  - NAVAREA I blocks are EXCLUDED from segmentation (no geometry bleed into
    the last regional warning) unless CANCEL cross-references.
  - Pure NAVAREA I pastes still route to the dedicated NAVAREA 1 parser.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.navarea_universal_parser import (
    parse_bulletin_text, resolve_region,
)

SAMPLE_XIX_WITH_I = (
    "WARNINGS IN FORCE AS ON 23 OCT 2026\n"
    "\n"
    "NAVAREA XIX 062/26\n"
    " 1. HYDROGRAPHIC SURVEY IN AREA BOUNDED BY 71-10.0N 020-00.0E, "
    "71-20.0N 020-00.0E, 71-20.0N 020-10.0E, 71-10.0N 020-10.0E\n"
    " 2. CANCEL NAVAREA XIX 061/26\n"
    "\n"
    "NAVAREA I 004/26\n"
    " NORTH SEA (.) FIRING PRACTICE IN AREA BOUNDED WITHIN "
    "58-10.0N TO 58-15.0N AND 002-00.0E TO 002-10.0E (.) WIDE BERTH\n"
    "\n"
    "NAVAREA XIX 063/26\n"
    " NORWEGIAN SEA (.) LIVE FIRING WITHIN 68-00.0N TO 68-10.0N AND "
    "005-00.0E TO 005-10.0E\n"
    " SEE ALSO CANCEL NAVAREA I 003/26\n"
)


class TestNavareaOneCompanion(unittest.TestCase):

    def test_path_target_xix_with_i_headers_accepted(self):
        key, error = resolve_region("/x/navarea_xix/pasted_raw.txt",
                                    SAMPLE_XIX_WITH_I)
        self.assertEqual(key, "xix")
        self.assertIsNone(error)

    def test_no_path_hint_resolves_to_xix(self):
        key, error = resolve_region(None, SAMPLE_XIX_WITH_I)
        self.assertEqual(key, "xix")
        self.assertIsNone(error)

    def test_companion_block_excluded_from_segmentation(self):
        parsed = parse_bulletin_text(SAMPLE_XIX_WITH_I, "xix")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertEqual(ids, ["NAVAREA XIX 062/26", "NAVAREA XIX 063/26"])
        for w in parsed["nav_warnings"]:
            self.assertNotIn("NAVAREA I 004/26", w["raw_text"],
                             "companion block must not be absorbed")
            self.assertNotIn("NORTH SEA", w["raw_text"])

    def test_no_geometry_bleed_from_companion_block(self):
        parsed = parse_bulletin_text(SAMPLE_XIX_WITH_I, "xix")
        first = parsed["nav_warnings"][0]
        if first.get("latitude") is not None:
            # 71-xx N Arctic survey — must not be a North Sea centroid (~58 N)
            self.assertGreater(first["latitude"], 70.0)

    def test_cancel_ref_to_companion_is_not_a_terminator(self):
        parsed = parse_bulletin_text(SAMPLE_XIX_WITH_I, "xix")
        last = parsed["nav_warnings"][-1]
        self.assertIn("SEE ALSO CANCEL NAVAREA I 003/26", last["raw_text"])

    def test_cross_refs_still_region_scoped(self):
        parsed = parse_bulletin_text(SAMPLE_XIX_WITH_I, "xix")
        first = parsed["nav_warnings"][0]
        self.assertEqual(first["cross_refs"],
                         [{"number": "061", "year": "26"}])

    def test_pure_navarea_i_routes_to_dedicated_parser(self):
        text = ("NAVAREA I 004/26\n"
                " NORTH SEA (.) FIRING PRACTICE IN AREA BOUNDED WITHIN "
                "58-10.0N TO 58-15.0N AND 002-00.0E TO 002-10.0E\n")
        key, error = resolve_region(None, text)
        self.assertIsNone(key)
        self.assertIn("dedicated parser", error)

    def test_companion_tolerance_applies_to_all_universal_regions(self):
        text = ("NAVAREA II 123/26\n"
                " 1. HYDROGRAPHIC SURVEY IN AREA BOUNDED BY 48-00.0N 006-00.0W, "
                "48-30.0N 006-30.0W, 48-30.0N 005-30.0W, 48-00.0N 005-30.0W\n"
                "\n"
                "NAVAREA I 005/26\n"
                " ENGLISH CHANNEL (.) SURVEY WITHIN "
                "50-10.0N TO 50-20.0N AND 000-30.0W TO 000-40.0W\n")
        key, error = resolve_region(None, text)
        self.assertEqual(key, "ii")
        self.assertIsNone(error)

    def test_mixed_non_companion_regions_still_rejected(self):
        text = SAMPLE_XIX_WITH_I + "\nNAVAREA XXI 005/26 SOMETHING\n"
        key, error = resolve_region(None, text)
        self.assertIsNone(key)
        self.assertIn("mixed-region", error)
        # only the real foreign region is named — not the tolerated companion
        self.assertIn("XXI", error)


if __name__ == "__main__":
    unittest.main()
