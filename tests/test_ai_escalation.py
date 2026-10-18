#!/usr/bin/env python3
"""
test_ai_escalation.py — Unit Tests for AI Grounding and Escalation Module
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.ai_escalation import (
    GeminiConfig,
    WarningRecord,
    DataQuality,
    TriageTier,
    ParsingMethod,
    is_ai_coordinate_grounded,
    escalate_warning_to_gemini_flash_lite,
    default_parse_source_token,
)

class TestAIGrounding(unittest.TestCase):

    def test_ai_coordinate_must_match_exact_source_token(self):
        raw = "POSITION 21-16.5N 092-03.25E."
        self.assertTrue(
            is_ai_coordinate_grounded(
                raw_text=raw,
                raw_token="21-16.5N 092-03.25E",
                lat=21.275,
                lon=92.054167,
                parse_source_token=default_parse_source_token,
            )
        )

    def test_ai_cannot_combine_unrelated_source_coordinates(self):
        raw = (
            "POSITION A 21-16.5N 092-03.25E; "
            "POSITION B 18-30.0N 088-15.0E."
        )
        self.assertFalse(
            is_ai_coordinate_grounded(
                raw_text=raw,
                raw_token="21-16.5N 088-15.0E",
                lat=21.275,
                lon=88.25,
                parse_source_token=default_parse_source_token,
            )
        )

    def test_ai_cannot_supply_missing_hemisphere(self):
        raw = "POSITION 21-16.5N 092-03.25."
        self.assertFalse(
            is_ai_coordinate_grounded(
                raw_text=raw,
                raw_token="21-16.5N 092-03.25",
                lat=21.275,
                lon=92.054167,
                parse_source_token=default_parse_source_token,
            )
        )

    def test_unconfigured_escalation_skips_gracefully(self):
        config = GeminiConfig(enabled=False)
        rec = WarningRecord(raw_text="POSITION 50-45.0N 001-20.0E.")
        result = escalate_warning_to_gemini_flash_lite(rec, config=config)
        self.assertFalse(result)
        self.assertIn("AI_ESCALATION_SKIPPED_NO_CONFIG", rec.flags)

if __name__ == "__main__":
    unittest.main()
