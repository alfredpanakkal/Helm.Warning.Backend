#!/usr/bin/env python3
"""tests/test_hazard_classifier.py — hazard classification negative
guards (audit finding F4, 2026-10-30).

Confirmed mis-tags from the live DB audit, each pinned with a fixture:
  - pure cancel message NAVAREA XI 0479/26 tagged 'drifting'
  - space-debris area XI 0475/26 tagged 'drifting'
  - GNSS-interference warning (BALTIC 030/26 shape) filed 'offshore'
Plus keep-correct cases: replacement warnings keep their own hazard,
self-cancel datelines never blank an active warning's tags.
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.utils import classify_hazard, classify_hazard_categories


class TestCancelNoticesCarryNoHazard(unittest.TestCase):
    def test_pure_cancel_notice_is_general(self):
        # XI 0479/26 shape: the whole message is the cancellation
        raw = ("NAVAREA XI 0479/26\n"
               "CANCEL NAVAREA XI 0430/26.\n")
        self.assertEqual(classify_hazard_categories(raw), ["general"])

    def test_cancel_notice_with_dead_hazard_wording_is_general(self):
        # The notice repeats the CANCELLED warning's description: neither
        # the cancel sentence nor the 'no longer present' retraction may
        # tag the notice with the dead warning's hazard.
        raw = ("NAVAREA XI 0479/26\n"
               "CANCEL NAVAREA XI 0430/26.\n"
               "DRIFTING MINE PREVIOUSLY REPORTED IS NO LONGER A HAZARD "
               "TO NAVIGATION.\n")
        self.assertEqual(classify_hazard_categories(raw), ["general"])

    def test_stub_cancelled_warning_is_general(self):
        raw = "SWEDISH NAV WARN 199/26\nCANCELLED."
        self.assertEqual(classify_hazard(raw), "general")


class TestReplacementWarningsKeepTheirHazard(unittest.TestCase):
    def test_cancel_ref_sentence_does_not_hide_new_hazard(self):
        raw = ("NAVAREA II 125/26\n"
               " 1. CANCEL NAVAREA II 100/26\n"
               " 2. FIRING PRACTICE IN AREA BOUNDED BY 48-00.0N 006-00.0W\n")
        cats = classify_hazard_categories(raw)
        self.assertIn("military", cats)
        self.assertEqual(classify_hazard(raw), "military")

    def test_self_cancel_dateline_keeps_active_tags(self):
        raw = ("SEISMIC SURVEY IN AREA BOUNDED BY 18-00N 071-00E, "
               "18-00N 072-00E, 19-00N 072-00E, 19-00N 071-00E. "
               "CANCEL THIS WARNING 142100 UTC NOV 26.")
        cats = classify_hazard_categories(raw)
        self.assertIn("subsea", cats)
        self.assertNotIn("general", cats)


class TestSpaceDebrisIsLaunchRelated(unittest.TestCase):
    def test_space_debris_area_is_military_not_drifting(self):
        # XI 0475/26 shape: hazard area for debris re-entry
        raw = ("NAVAREA XI 0475/26\n"
               "EAST CHINA SEA.\n"
               "HAZARD AREA DUE TO SPACE DEBRIS RE-ENTRY.\n"
               " 1. AREA BOUNDED BY 30-00N 140-00E, 30-00N 141-00E, "
               "31-00N 141-00E, 31-00N 140-00E\n")
        cats = classify_hazard_categories(raw)
        self.assertIn("military", cats)
        self.assertNotIn("drifting", cats)
        self.assertEqual(classify_hazard(raw), "military")

    def test_rocket_debris_is_military(self):
        raw = "ROCKET DEBRIS EXPECTED TO FALL WITHIN THE AREA."
        self.assertEqual(classify_hazard(raw), "military")


class TestElectronicPriority(unittest.TestCase):
    def test_gnss_interference_near_rigs_files_electronic(self):
        # BALTIC 030/26 shape: interference observed in the vicinity of
        # offshore platforms — 'electronic' must be the PRIMARY category.
        raw = ("GNSS INTERFERENCE MAY BE EXPERIENCED IN THE BALTIC SEA "
               "IN VICINITY OF OFFSHORE PLATFORMS AND RIGS.")
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "electronic")
        self.assertEqual(classify_hazard(raw), "electronic")

    def test_gps_jamming_without_gnss_word_matches(self):
        # 'GPS' alone (no 'GNSS') must still file electronic.
        raw = "GPS JAMMING REPORTED IN THE APPROACHES."
        self.assertEqual(classify_hazard(raw), "electronic")


class TestKeepCorrectBehavior(unittest.TestCase):
    def test_drifting_mooring_line_still_drifting(self):
        # keep-correct case from the audit plan (II 364/26 shape)
        raw = ("DRIFTING MOORING LINE REPORTED IN 48-00.0N 006-00.0W. "
               "VESSELS REQUESTED TO KEEP CLEAR.")
        self.assertEqual(classify_hazard(raw), "drifting")

    def test_multi_hazard_order_preserved(self):
        raw = ("MILITARY FIRING EXERCISE CONDUCTED. DRIFTING TARGET "
               "CONTAINER REPORTED AT VICINITY.")
        cats = classify_hazard_categories(raw)
        self.assertIn("military", cats)
        self.assertIn("drifting", cats)
        self.assertEqual(classify_hazard(raw), "military")

    def test_plain_notice_stays_general(self):
        raw = "HYDROGRAPHIC SURVEY COMPLETED. CHARTS UPDATED."
        self.assertEqual(classify_hazard_categories(raw), ["general"])


if __name__ == "__main__":
    unittest.main()
