#!/usr/bin/env python3
"""Tests for NAVAREA VIII partial-sweep salvage and loud-runner aborts.

Covers:
  * Tier 1 early-stop falls through to the authoritative PDF (Tier 2).
  * All tiers fail + salvageable partial on disk -> stop_reason='early_stop',
    full_snapshot=False (never a complete snapshot).
  * All tiers fail + nothing salvageable -> loud RuntimeError.
  * navarea_8_sync.sync_to_supabase forwards full_snapshot to the engine.
  * Lenient-scraper runners abort loudly when the scraper returns None
    (fetch failure) — parse/sync are never reached.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts import navarea_8_scraper
from scripts import navarea_8_sync
import scripts.run_baltic as run_baltic
import scripts.run_navarea_iv as run_navarea_iv


def _bulletin(n=6):
    """Synthesises an in-force bulletin carrying n warning headers."""
    parts = ["NAVAREA VIII - WARNINGS IN FORCE"]
    for i in range(1, n + 1):
        parts.append(f"NAVAREA VIII - {100 + i}/26")
        parts.append(f"Test warning number {100 + i} body text.")
    return "\n".join(parts)


class TestViiiSalvage(unittest.TestCase):
    def test_header_count_regex(self):
        text = _bulletin(6)
        self.assertEqual(navarea_8_scraper._header_count(text), 6)
        # Tolerates dash variants and spacing
        self.assertEqual(navarea_8_scraper._header_count("NAVAREA VIII 12/26"), 1)
        self.assertEqual(navarea_8_scraper._header_count("NAVAREA VIII - 12 / 26"), 1)

    def test_early_stop_falls_through_to_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "navarea_8_warnings.txt")
            pdf_text = _bulletin(8)
            with mock.patch.object(navarea_8_scraper, "_fetch_tier1_table",
                                   side_effect=RuntimeError("pagination stopped early")) as t1, \
                 mock.patch.object(navarea_8_scraper, "_fetch_tier2_pdf",
                                   return_value=(pdf_text, "completed")) as t2, \
                 mock.patch.object(navarea_8_scraper, "_fetch_tier3_mirror") as t3:
                harvest = navarea_8_scraper.scrape_viii_warnings(raw)
            t1.assert_called_once()
            t2.assert_called_once()
            t3.assert_not_called()
            self.assertEqual(harvest["stop_reason"], "completed")
            self.assertTrue(harvest["full_snapshot"])
            with open(raw, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), pdf_text)

    def test_all_tiers_fail_salvages_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "navarea_8_warnings.txt")
            partial = _bulletin(5)
            with open(raw, "w", encoding="utf-8") as f:
                f.write(partial)
            boom = RuntimeError("tier down")
            with mock.patch.object(navarea_8_scraper, "_fetch_tier1_table", side_effect=boom), \
                 mock.patch.object(navarea_8_scraper, "_fetch_tier2_pdf", side_effect=boom), \
                 mock.patch.object(navarea_8_scraper, "_fetch_tier3_mirror", side_effect=boom):
                harvest = navarea_8_scraper.scrape_viii_warnings(raw)
            self.assertEqual(harvest["stop_reason"], "early_stop")
            self.assertFalse(harvest["full_snapshot"])
            self.assertEqual(harvest["text"], partial)

    def test_all_tiers_fail_no_partial_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "navarea_8_warnings.txt")
            boom = RuntimeError("tier down")
            with mock.patch.object(navarea_8_scraper, "_fetch_tier1_table", side_effect=boom), \
                 mock.patch.object(navarea_8_scraper, "_fetch_tier2_pdf", side_effect=boom), \
                 mock.patch.object(navarea_8_scraper, "_fetch_tier3_mirror", side_effect=boom):
                with self.assertRaises(RuntimeError):
                    navarea_8_scraper.scrape_viii_warnings(raw)


class TestViiiSyncForwardsFullSnapshot(unittest.TestCase):
    def test_sync_forwards_partial_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            parsed = os.path.join(tmp, "parsed_navarea_8_warnings.json")
            with open(parsed, "w", encoding="utf-8") as f:
                json.dump({"raw_messages": [], "nav_warnings": []}, f)
            captured = {}

            def fake_sync(**kwargs):
                captured.update(kwargs)
                return True

            with mock.patch.object(navarea_8_sync, "run_differential_sync", side_effect=fake_sync), \
                 mock.patch.object(navarea_8_sync, "get_supabase_client", return_value=None):
                ok = navarea_8_sync.sync_to_supabase(parsed, full_snapshot=False)
            self.assertTrue(ok)
            self.assertFalse(captured["full_snapshot"])
            self.assertEqual(captured["source_id"], "nho-navarea-viii")


class TestLoudRunners(unittest.TestCase):
    def test_baltic_runner_aborts_on_none_harvest(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "baltic_warnings.txt")
            parsed = os.path.join(tmp, "parsed_baltic.json")
            with mock.patch("scripts.baltic_scraper.scrape_baltic_warnings", return_value=None), \
                 mock.patch("scripts.baltic_parser.main") as parse_mock, \
                 mock.patch("scripts.baltic_sync.sync_to_supabase") as sync_mock:
                self.assertFalse(run_baltic.main(raw, parsed))
            parse_mock.assert_not_called()
            sync_mock.assert_not_called()

    def test_iv_runner_aborts_on_none_harvest(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "navarea_iv_warnings.txt")
            parsed = os.path.join(tmp, "parsed_navarea_iv.json")
            with mock.patch("scripts.navarea_iv_scraper.scrape_iv_warnings", return_value=None), \
                 mock.patch("scripts.navarea_iv_parser.main") as parse_mock, \
                 mock.patch("scripts.navarea_iv_sync.sync_to_supabase") as sync_mock:
                self.assertFalse(run_navarea_iv.main(raw, parsed))
            parse_mock.assert_not_called()
            sync_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
