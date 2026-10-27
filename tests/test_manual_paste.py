#!/usr/bin/env python3
"""
tests/test_manual_paste.py — Manual bulk-paste ingest regression tests.

Guards the region registry contract: every region's parser must expose
main(raw_txt, parsed_json) and its sync module sync_to_supabase(parsed_json),
so run_manual_paste can never silently diverge from the scheduled pipelines.
"""
import inspect
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.run_manual_paste import REGIONS, main as run_manual_paste

ALL_REGION_KEYS = ["1", "8", "baltic", "ii", "iii", "iv", "ix", "v", "vi", "vii", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi"]


class TestRegionRegistry(unittest.TestCase):

    def test_all_regions_registered(self):
        self.assertEqual(sorted(REGIONS), sorted(ALL_REGION_KEYS))

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
        self.assertRaises(SystemExit, run_manual_paste,
                          ["--navarea", "xxii", "--input", "x.txt"])


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


class TestNavareaVManualImport(unittest.TestCase):
    """NAVAREA V manual import: the admin pastes the raw CHM
    avradio_NN.json snapshot copied from the browser (the Cloudflare wall
    blocks the scheduled scrape); it must flow through the SAME filter +
    parser + sync as the scheduled pipeline — with an empty or invalid
    payload failing closed (never an empty sync)."""

    _CHM_JSON = json.dumps(
        {"atualizado": "27/10/2026 04:00",
         "avisos": [
             {"numero": "0648/26", "costa": "", "tipo": "L",
              "textoPT": "A LESTE DE SANTA CATARINA ...",
              "textoEN": ("EAST OF SANTA CATARINA. LAST POSITION IN "
                          "28-07.87S 026-56.90W AT 151906 UTC OCT 26."),
              "geometry": ""},
             {"numero": "SAR 0105/26", "costa": "SAR", "tipo": "Z",
              "textoPT": "HOMEM AO MAR ...",
              "textoEN": "MAN OVERBOARD.",
              "geometry": ""},
         ]}, ensure_ascii=False)

    def test_detect_navarea_from_chm_json(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertEqual(detect_navarea(self._CHM_JSON), "v")

    def test_unrelated_json_stays_undetected(self):
        from scripts.run_manual_paste import detect_navarea
        self.assertIsNone(detect_navarea(json.dumps({"unrelated": [1, 2]})))

    def test_chm_json_paste_ingests_through_parser_and_sync(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                inp = os.path.join(td, "pasted.json")
                with open(inp, "w", encoding="utf-8") as f:
                    f.write(self._CHM_JSON)
                with mock.patch(
                        "scripts.navarea_generic_sync.sync_to_supabase",
                        return_value=True) as sync_mock:
                    self.assertTrue(run_manual_paste(
                        ["--navarea", "v", "--input", inp]))
                sync_mock.assert_called_once()
                # the parser received the SYNTHESIZED bulletin (bare
                # '0648/26' header), not the raw CHM JSON
                with open(os.path.join("navareas", "manual", "navarea_v",
                                      "pasted_raw.txt"),
                          encoding="utf-8") as f:
                    first_line = f.read().splitlines()[0]
                self.assertEqual(first_line, "0648/26")
            finally:
                os.chdir(old_cwd)

    def test_all_national_records_paste_fails_closed(self):
        only_sar = json.dumps(
            {"atualizado": "27/10/2026 04:00",
             "avisos": [{"numero": "SAR 0105/26", "costa": "SAR", "tipo": "Z",
                         "textoPT": "x", "textoEN": "MAN OVERBOARD.",
                         "geometry": ""}]},
            ensure_ascii=False)
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                inp = os.path.join(td, "pasted.json")
                with open(inp, "w", encoding="utf-8") as f:
                    f.write(only_sar)
                with mock.patch(
                        "scripts.navarea_generic_sync.sync_to_supabase",
                        return_value=True) as sync_mock:
                    self.assertFalse(run_manual_paste(
                        ["--navarea", "v", "--input", inp]))
                sync_mock.assert_not_called()
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
