#!/usr/bin/env python3
"""
tests/test_universal_parser.py — Universal NAVAREA parser regression tests.

Covers the region registry extension (II/III/V/VI/VII/IX/X via the
universal parser + generic sync), region auto-detection for the new
numerals, segmentation/cross-refs on a synthetic NAVAREA II bulletin,
and the fail-closed mixed-region / dedicated-region guards.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.run_manual_paste import REGIONS, detect_navarea
from scripts.navarea_universal_parser import (
    parse_bulletin_text, resolve_region, _region_config,
)
from shared.navarea_universal_text import UNIVERSAL_REGIONS

ALL_REGION_KEYS = ["1", "8", "baltic", "ii", "iii", "iv", "ix",
                   "v", "vi", "vii", "x", "xi", "xii"]

SAMPLE_II = (
    "WARNINGS IN FORCE AS ON 23 OCT 2026\n"
    "\n"
    "NAVAREA II 123/26\n"
    " 1. HYDROGRAPHIC SURVEY IN AREA BOUNDED BY 48-00.0N 006-00.0W, "
    "48-30.0N 006-30.0W, 48-30.0N 005-30.0W, 48-00.0N 005-30.0W\n"
    " 2. CANCEL NAVAREA II 100/26\n"
    "\n"
    "NAVAREA II 124/26\n"
    " BAY OF BISCAY (.) FIRING PRACTICE IN AREA BOUNDED WITHIN "
    "45-10.0N TO 45-20.0N AND 001-00.0W TO 001-10.0W (.) WIDE BERTH "
    "REQUESTED\n"
    " 2. CANCEL THIS MSG 311800 UTC DEC 26\n"
)


class TestUniversalRegistry(unittest.TestCase):

    def test_all_thirteen_regions_registered(self):
        self.assertEqual(sorted(REGIONS), ALL_REGION_KEYS)

    def test_universal_regions_use_universal_modules(self):
        for key in UNIVERSAL_REGIONS:
            parser_mod, sync_mod, subdir = REGIONS[key]
            self.assertEqual(parser_mod, "scripts.navarea_universal_parser", key)
            self.assertEqual(sync_mod, "scripts.navarea_generic_sync", key)
            self.assertEqual(subdir, "navarea_" + key)

    def test_dedicated_regions_unchanged(self):
        for key in ["1", "8", "iv", "xi", "xii", "baltic"]:
            parser_mod, _sync_mod, _sub = REGIONS[key]
            self.assertNotEqual(parser_mod, "scripts.navarea_universal_parser", key)


class TestDetectNavareaNewRegions(unittest.TestCase):

    def test_detect_all_universal_numerals(self):
        self.assertEqual(detect_navarea("NAVAREA II 123/26"), "ii")
        self.assertEqual(detect_navarea("NAVAREA III 004/26"), "iii")
        self.assertEqual(detect_navarea("NAVAREA V 012/26"), "v")
        self.assertEqual(detect_navarea("NAVAREA VI 007/26"), "vi")
        self.assertEqual(detect_navarea("NAVAREA VII 001/26"), "vii")
        self.assertEqual(detect_navarea("NAVAREA IX 011/26"), "ix")
        self.assertEqual(detect_navarea("NAVAREA X 002/26"), "x")
        self.assertEqual(detect_navarea("NAV AREA IX 011/26"), "ix")

    def test_no_false_positive_on_warning_number(self):
        self.assertIsNone(detect_navarea("NAVAREA 961/26 SOMETHING"))

    def test_dedicated_regions_still_detect(self):
        self.assertEqual(detect_navarea("NAVAREA VIII -961/26"), "8")
        self.assertEqual(detect_navarea("NAVAREA XII 001/26"), "xii")
        self.assertEqual(detect_navarea("SWEDISH NAV WARN 168/26"), "baltic")


class TestUniversalParse(unittest.TestCase):

    def test_region_config(self):
        cfg = _region_config("ii")
        self.assertEqual(cfg["roman"], "II")
        self.assertEqual(cfg["source_id"], "manual-navarea-ii")

    def test_parse_bulletin_text_ii(self):
        parsed = parse_bulletin_text(SAMPLE_II, "ii")
        self.assertEqual(len(parsed["nav_warnings"]), 2)
        self.assertEqual(parsed["nav_warnings"][0]["warning_id"],
                         "NAVAREA II 123/26")
        self.assertEqual(parsed["nav_warnings"][0]["canonical_id"],
                         "NAVAREA II 123/26")
        self.assertEqual(parsed["nav_warnings"][0]["navarea"], "II")
        self.assertEqual(parsed["nav_warnings"][0]["source_id"],
                         "manual-navarea-ii")
        # cross-ref from body CANCEL
        refs = parsed["nav_warnings"][0]["cross_refs"]
        self.assertEqual(refs, [{"number": "100", "year": "26"}])
        # geometry resolved for at least one warning
        self.assertTrue(any(w["spatial"] for w in parsed["nav_warnings"]))
        # memo carries the sync keys
        self.assertEqual(parsed["memo"]["source_id"], "manual-navarea-ii")
        self.assertEqual(parsed["memo"]["navarea"], "II")
        # as-on header captured
        self.assertTrue(parsed["memo"]["in_force_as_on"])

    def test_cancel_cross_ref_of_other_region_is_not_mixed(self):
        text = SAMPLE_II + "\nSEE ALSO CANCEL NAVAREA VIII 1104/26\n"
        key, error = resolve_region(None, text)
        self.assertEqual(key, "ii")
        self.assertIsNone(error)


class TestRegionResolutionGuards(unittest.TestCase):

    def test_path_region_wins(self):
        key, error = resolve_region("/x/navarea_ix/pasted_raw.txt",
                                    "NAVAREA IX 011/26 FIRING PRACTICE AREA ...")
        self.assertEqual(key, "ix")
        self.assertIsNone(error)

    def test_mixed_region_rejected(self):
        text = SAMPLE_II + "\nNAVAREA VII 005/26 SOMETHING\n"
        key, error = resolve_region(None, text)
        self.assertIsNone(key)
        self.assertIn("mixed-region", error)

    def test_path_target_with_foreign_headers_rejected(self):
        key, error = resolve_region("/x/navarea_ii/pasted_raw.txt",
                                    "NAVAREA X 002/26 TEXT")
        self.assertIsNone(key)
        self.assertIn("mixed-region", error)

    def test_dedicated_region_headers_rejected(self):
        key, error = resolve_region(None, "NAVAREA VIII -1102/26 KARWAR")
        self.assertIsNone(key)
        self.assertIn("dedicated parser", error)

    def test_dedicated_region_path_rejected(self):
        key, error = resolve_region("/x/navarea_8/pasted_raw.txt",
                                    "NAVAREA VIII -1102/26 KARWAR")
        self.assertIsNone(key)
        self.assertIn("dedicated parser", error)

    def test_no_headers_rejected(self):
        key, error = resolve_region(None, "JUST SOME TEXT ABOUT RIGS")
        self.assertIsNone(key)
        self.assertIn("could not determine", error)


if __name__ == "__main__":
    unittest.main()
