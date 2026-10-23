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


class TestRegionRegistry(unittest.TestCase):

    def test_all_six_regions_registered(self):
        self.assertEqual(sorted(REGIONS), ["1", "8", "baltic", "iv", "xi", "xii"])

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
            f.write("   \n  \n")
            path = f.name
        try:
            self.assertFalse(run_manual_paste(["--navarea", "8", "--input", path]))
        finally:
            os.unlink(path)

    def test_invalid_region_rejected(self):
        with self.assertRaises(SystemExit):
            run_manual_paste(["--navarea", "vii", "--input", "x.txt"])


if __name__ == "__main__":
    unittest.main()
