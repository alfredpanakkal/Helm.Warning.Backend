#!/usr/bin/env python3
"""tests/test_hazard_taxonomy_followup.py - PR #103 follow-up regression tests.

Covers the review findings on the 16-category taxonomy:
  A. canonical categories first, legacy aliases after; general_chart fallback
  B. contextual matching (container / obstruction / anchor / cable / rig)
  C. completion/discontinuation must not delete an active warning
  D. floodlight references must not suppress a separate AtoN hazard
  E. regional parsers keep `category` (legacy) and `categories` consistent
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.utils import (
    LEGACY_CATEGORY_ALIASES,
    classify_hazard,
    classify_hazard_categories,
)


class TestCanonicalFirstAndFallback(unittest.TestCase):
    def test_canonical_entries_precede_every_alias(self):
        # Two canonical hazards that both carry aliases: the order must be
        # [canonical..., alias...], never interleaved.
        raw = "MISSILE FIRING IN PROGRESS. DRIFTING CONTAINER REPORTED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[:2], ["mil_fire", "drift"])
        self.assertEqual(cats[2:], ["military", "drifting"])

    def test_first_entry_is_always_canonical(self):
        aliases_only = set(LEGACY_CATEGORY_ALIASES.values()) - set(LEGACY_CATEGORY_ALIASES)
        samples = [
            "GUNNERY EXERCISE IN AREA.",
            "DERELICT VESSEL ADRIFT.",
            "SUNKEN WRECK REPORTED.",
            "DRILLING RIG ON LOCATION.",
            "GPS JAMMING REPORTED.",
            "DEPTH CORRECTION. NEW SOUNDINGS.",
            "",
            "XYZ",
        ]
        for raw in samples:
            with self.subTest(raw=raw):
                self.assertNotIn(classify_hazard_categories(raw)[0], aliases_only)

    def test_empty_input_falls_back_to_general_chart(self):
        self.assertEqual(classify_hazard_categories(""), ["general_chart", "general"])
        self.assertEqual(classify_hazard_categories(None), ["general_chart", "general"])

    def test_unmatched_input_falls_back_to_general_chart(self):
        self.assertEqual(
            classify_hazard_categories("ROUTINE NOTICE TO MARINERS"),
            ["general_chart", "general"],
        )

    def test_cancel_only_notice_keeps_existing_general_contract(self):
        # Existing assertions expect a pure cancel notice to stay ['general'].
        self.assertEqual(
            classify_hazard_categories("CANCEL NAVAREA XI 0430/26."), ["general"])

    def test_legacy_classify_hazard_contract_unchanged(self):
        # Default return is the legacy alias; canonical=True is opt-in.
        self.assertEqual(classify_hazard("ROUTINE NOTICE TO MARINERS"), "general")
        self.assertEqual(classify_hazard(""), "general")
        self.assertEqual(classify_hazard("GPS JAMMING REPORTED."), "electronic")
        self.assertEqual(classify_hazard("GPS JAMMING REPORTED.", canonical=True), "service_status")
        self.assertEqual(classify_hazard("DERELICT VESSEL ADRIFT."), "drifting")
        self.assertEqual(classify_hazard("SUNKEN WRECK REPORTED."), "subsea")


class TestContextualMatching(unittest.TestCase):
    def test_ordinary_container_vessel_is_not_drift(self):
        for raw in (
            "CONTAINER VESSEL MV EXAMPLE PROCEEDING TO PORT.",
            "CONTAINER SHIP BERTHING AT CONTAINER TERMINAL 3.",
        ):
            with self.subTest(raw=raw):
                cats = classify_hazard_categories(raw)
                self.assertNotIn("drift", cats)
                self.assertNotIn("drifting", cats)

    def test_container_reported_adrift_is_drift(self):
        for raw in (
            "CONTAINER REPORTED ADRIFT IN APPROACHES.",
            "LOST CONTAINERS FLOATING NEAR THE TSS.",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(classify_hazard_categories(raw)[0], "drift")

    def test_generic_obstruction_is_not_wreck(self):
        cats = classify_hazard_categories("OBSTRUCTION REPORTED IN FAIRWAY.")
        self.assertNotIn("wreck", cats)
        self.assertNotIn("subsea", cats)

    def test_explicit_wreck_obstruction_is_wreck(self):
        for raw in (
            "OBSTRUCTION (WRECK) REPORTED AT FAIRWAY ENTRANCE.",
            "SUBMERGED OBSTRUCTION REPORTED IN CHANNEL.",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(classify_hazard_categories(raw)[0], "wreck")

    def test_ordinary_anchoring_instruction_is_not_ops(self):
        for raw in (
            "VESSELS ARE ADVISED TO ANCHOR IN ANCHORAGE B.",
            "ANCHORING IS PERMITTED NORTH OF THE CHANNEL.",
        ):
            with self.subTest(raw=raw):
                cats = classify_hazard_categories(raw)
                self.assertNotIn("ops", cats)
                self.assertNotIn("subsea", cats)

    def test_anchor_handling_operations_are_ops(self):
        self.assertEqual(
            classify_hazard_categories("ANCHOR HANDLING OPERATIONS BY AHTS NORDIC.")[0], "ops")

    def test_rov_needs_word_boundary(self):
        # 'PROVIDED' contains the letters ROV; it must not file as ops.
        self.assertNotIn("ops", classify_hazard_categories("INFORMATION PROVIDED BY THE HARBOUR MASTER."))
        self.assertEqual(classify_hazard_categories("ROV OPERATIONS IN PROGRESS.")[0], "ops")

    def test_contextual_cable_and_pipeline_hazard_is_cable(self):
        for raw in (
            "SUBMARINE CABLE REPAIR IN PROGRESS.",
            "CABLE LAYING OPERATIONS BY C/S EXAMPLE.",
            "SUBSEA PIPELINE INSTALLATION IN PROGRESS.",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(classify_hazard_categories(raw)[0], "cable")

    def test_cable_as_distance_or_ship_gear_is_not_cable(self):
        for raw in (
            "KEEP WITHIN 2 CABLES OF THE LEADING LINE.",
            "VESSEL LOST ANCHOR CABLE.",
        ):
            with self.subTest(raw=raw):
                self.assertNotIn("cable", classify_hazard_categories(raw))

    def test_contextual_offshore_platform_hazard_is_rig(self):
        for raw in (
            "OFFSHORE PRODUCTION PLATFORM MAINTENANCE IN PROGRESS.",
            "DRILLING PLATFORM ESTABLISHED AT 10-00N 020-00E.",
            "JACK-UP RIG RELOCATING.",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(classify_hazard_categories(raw)[0], "rig")

    def test_rig_needs_word_boundary(self):
        for raw in ("ORIGINAL NOTICE WITHDRAWN BY THE ORIGINATOR.", "BRIGHT LIGHT SEEN ASHORE."):
            with self.subTest(raw=raw):
                self.assertNotIn("rig", classify_hazard_categories(raw))

    def test_generic_platform_is_not_rig(self):
        self.assertNotIn("rig", classify_hazard_categories("PILOT BOARDING PLATFORM RELOCATED TO QUAY 4."))


class TestFloodlightAndAton(unittest.TestCase):
    def test_unlit_buoy_and_floodlight_in_one_bulletin(self):
        raw = "NORTH CARDINAL BUOY DAMAGED. FLOODLIGHT INSTALLED ON QUAY 4."
        self.assertEqual(classify_hazard_categories(raw)[0], "aton")

    def test_floodlight_in_same_bulletin_after_aton_hazard(self):
        raw = "FLOODLIGHT INSTALLED ON QUAY 4. BUOY NO 5 UNLIT."
        self.assertEqual(classify_hazard_categories(raw)[0], "aton")

    def test_floodlight_alone_is_not_aton(self):
        for raw in (
            "OFFSHORE DRILLING RIG EQUIPPED WITH WORKING FLOODLIGHTS.",
            "FLOODLIGHT ON QUAY EXTINGUISHED.",
        ):
            with self.subTest(raw=raw):
                self.assertNotIn("aton", classify_hazard_categories(raw))

    def test_floodlight_status_does_not_leak_to_unrelated_buoy(self):
        # The only status word sits in the floodlight sentence.
        raw = "FLOODLIGHT ON QUAY EXTINGUISHED. BUOY NO 5 IN POSITION."
        self.assertNotIn("aton", classify_hazard_categories(raw))


class TestCompletionDoesNotDeleteActiveWarnings(unittest.TestCase):
    def test_active_aton_warning_containing_discontinued(self):
        raw = "LIGHT BUOY NO 7 DISCONTINUED. RACON ESTABLISHED ON NEW BUOY."
        self.assertEqual(classify_hazard_categories(raw)[0], "aton")

    def test_discontinued_service_is_still_a_service_warning(self):
        raw = "DGPS STATION DISCONTINUED. USE ALTERNATIVE POSITIONING."
        self.assertEqual(classify_hazard_categories(raw)[0], "service_status")

    def test_active_warning_containing_completed(self):
        raw = "DREDGING OPERATIONS COMPLETED IN AREA A. DREDGING CONTINUES IN AREA B."
        self.assertEqual(classify_hazard_categories(raw)[0], "ops")

    def test_completed_equipment_does_not_hide_hazard(self):
        raw = "COMPLETED PLATFORM NOW ON STATION. BUOY NO 5 UNLIT."
        self.assertIn("aton", classify_hazard_categories(raw))

    def test_completed_operation_still_stripped(self):
        # Existing behaviour that must survive the narrowing.
        self.assertEqual(
            classify_hazard_categories("HYDROGRAPHIC SURVEY COMPLETED. CHARTS UPDATED."),
            ["general"])
        self.assertEqual(
            classify_hazard_categories("SEISMIC SURVEY OPERATIONS COMPLETED. CANCEL THIS NOTICE."),
            ["general"])

    def test_priority_rules_still_hold(self):
        gnss = classify_hazard_categories("GPS JAMMING NEAR OFFSHORE PLATFORMS AND RIGS.")
        self.assertEqual(gnss[0], "service_status")
        self.assertIn("rig", gnss)
        debris = classify_hazard_categories("FALLING ROCKET DEBRIS AND SPACE DEBRIS RE-ENTRY.")
        self.assertEqual(debris[0], "mil_fire")
        self.assertNotIn("drift", debris)


class TestParserOutputConsistency(unittest.TestCase):
    """category (legacy) must equal the legacy alias of categories[0]."""

    def _assert_consistent(self, record):
        cats = record["categories"]
        self.assertTrue(cats)
        self.assertEqual(
            record["category"], LEGACY_CATEGORY_ALIASES.get(cats[0], cats[0]))

    def test_ai_fallback_parser(self):
        from scripts.ai_parser import fallback_parse_warning
        self._assert_consistent(fallback_parse_warning(
            "MISSILE FIRING EXERCISE IN AREA 54-10.0N 010-20.0E."))

    def test_navarea_8_parser_category_is_legacy_token(self):
        # navarea_8 used categories[0] (canonical) for `category`, which
        # broke legacy consumers once the taxonomy went canonical-first.
        import inspect
        from scripts import navarea_8_parser
        src = inspect.getsource(navarea_8_parser)
        self.assertIn('"category": classify_hazard(raw_text)', src)
        self.assertNotIn('categories[0] if categories else "general"', src)

    def test_all_parsers_derive_category_from_classify_hazard(self):
        import glob
        import re
        pattern = re.compile(r'categories\[0\]\s+if\s+categories\s+else')
        offenders = []
        for path in glob.glob(os.path.join(ROOT_DIR, "scripts", "*parser*.py")):
            with open(path, encoding="utf-8") as fh:
                if pattern.search(fh.read()):
                    offenders.append(os.path.basename(path))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
