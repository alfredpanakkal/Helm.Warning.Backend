#!/usr/bin/env python3
"""
tests/test_manual_paste.py — Manual bulk-paste ingest regression tests.

Guards the region registry contract: every region's parser must expose
main(raw_txt, parsed_json) and its sync module sync_to_supabase(parsed_json),
so run_manual_paste can never silently diverge from the scheduled pipelines.
"""
import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.run_manual_paste import REGIONS, main as run_manual_paste

ALL_REGION_KEYS = ["1", "8", "baltic", "ii", "iii", "iv", "ix", "v", "vi", "vii", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi"]


class TestRegionRegistry(unittest.TestCase):

    def test_all_regions_registered(self):
        self.assertEqual(sorted(REGIONS), ALL_REGION_KEYS)

    def test_every_region_parser_has_main_two_arg_signature(self):
        import importlib
        for region, (parser_mod, _sync_mod, _sub) in REGIONS.items():
            mod = importlib.import_module(parser_mod)
            self.assertTrue(callable(mod.main), region)
            params = list(inspect.signature(mod.main).parameters)
            self.assertEqual(len(params), 2, f"{region} parser main() args")

    def test_every_region_sync_has_sync_to_supabase(self):
        import importlib
        for region, (_parser_mod, sync_mod, _sub) in REGIONS.items():
            mod = importlib.import_module(sync_mod)
            self.assertTrue(callable(mod.sync_to_supabase), region)
            params = list(inspect.signature(mod.sync_to_supabase).parameters)
            self.assertEqual(len(params), 1, f"{region} sync_to_supabase() args")


class TestRunnerGuards(unittest.TestCase):

    def test_missing_input_file_fails(self):
        self.assertFalse(run_manual_paste(["--navarea", "8", "--input", "/nonexistent/x.txt"]))

    def test_empty_paste_fails_closed(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("   
  
")
            path = f.name
        try:
            self.assertFalse(run_manual_paste(["--navarea", "8", "--input", path]))
        finally:
            os.unlink(path)

    def test_invalid_region_rejected(self):
        self.assertRaises(SystemExit, run_manual_paste,
                          ["--navarea", "vii", "--input", "x.txt"])


class TestRegionAutoDetect(unittest.TestCase):
    """The text header is authoritative: a wrong selection must be overridden."""

    def test_detect_viii_from_real_header(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertEqual(detect_navarea("NAVAREA VIII -961/26 INDIA WEST COAST (.)"), "8")

    def test_detect_iv_xi_xii(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertEqual(detect_navarea("NAVAREA IV 133/26"), "iv")
        self.assertEqual(detect_navarea("NAVAREA XI 005/26"), "xi")
        self.assertEqual(detect_navarea("NAVAREA XII 001/26"), "xii")

    def test_detect_baltic(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertEqual(detect_navarea("SWEDISH NAV WARN 168/26 [Skagerrak]"), "baltic")

    def test_detect_met_areas(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertEqual(detect_navarea("NAVAREA XVII 001/26"), "xvii")
        self.assertEqual(detect_navarea("NAVAREA XXI 001/26"), "xxi")

    def test_no_false_positive_on_warning_number(self):
        from scripts.run_manual_paste import detect_navarea
        # 'NAVAREA 961/26' style without roman numeral must not map anywhere
        self.assertIsNone(detect_navarea("NAVAREA 961/26 SOMETHING"))

    def test_no_header_returns_none(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertIsNone(detect_navarea("JUST SOME TEXT ABOUT RIGS AT 18-00N 071-00E"))

    def test_auto_choice_accepted_by_argparse(self):
        # 'auto' must be a valid choice (no SystemExit)
        import scripts.run_manual_paste as rmp
        ap_ok = True
        try:
            rmp.main(["--navarea", "auto", "--input", "/nonexistent/x.txt"])
        except SystemExit:
            ap_ok = False
        self.assertTrue(ap_ok, "auto must be a valid --navarea choice")


if __name__ == "__main__":
    unittest.main()
