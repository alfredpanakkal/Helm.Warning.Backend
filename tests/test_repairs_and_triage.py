#!/usr/bin/env python3
"""
tests/test_repairs_and_triage.py — Tests for Coordinate Repair Rules, Triage Precedence, and Sync Modes
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.models import TriageRecord, DataQuality, ParsingMethod, TriageTier
from shared.triage import assign_final_triage
from shared.sync_modes import compute_differential_guarded
from shared.utils import repair_coordinate_token, parse_coordinate_with_provenance
from shared.splitter import split_corpus

class TestCoordinateRepairsAndTriage(unittest.TestCase):

    def test_rule18_repair(self):
        token, rules = repair_coordinate_token("11-49-992S")
        self.assertEqual(token, "11-49.992S")
        self.assertIn("rule18", rules)

    def test_rule19_repair(self):
        token, rules = repair_coordinate_token("049.01.55E")
        self.assertEqual(token, "049-01.55E")
        self.assertIn("rule19", rules)

    def test_rule20_repair(self):
        token_lat, rules_lat = repair_coordinate_token("021-26.90N")
        self.assertEqual(token_lat, "21-26.90N")
        self.assertIn("rule20", rules_lat)

        token_lon, rules_lon = repair_coordinate_token("42-08.00E")
        self.assertEqual(token_lon, "042-08.00E")
        self.assertIn("rule20", rules_lon)

    def test_rule93_repair(self):
        token, rules = repair_coordinate_token("44-05,12N")
        self.assertEqual(token, "44-05.12N")
        self.assertIn("rule93", rules)

    def test_triage_precedence_tier_a(self):
        rec = TriageRecord()
        rec.coordinates = [parse_coordinate_with_provenance("POS 21-26.90N 042-08.00E", "21-26.90N")]
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.A)

    def test_triage_precedence_tier_b_repaired(self):
        rec = TriageRecord()
        rec.coordinates = [parse_coordinate_with_provenance("POS 021-26.90N 042-08.00E", "021-26.90N")]
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_sync_modes_static_corpus_disables_cancel(self):
        feed_ids = ["BALTIC 001/26"]
        active_ids = ["BALTIC 001/26", "BALTIC 002/26"]
        decisions = compute_differential_guarded(feed_ids, active_ids, mode="static_corpus")
        cancellation_ops = [d for d in decisions if d.op == "cancel"]
        self.assertEqual(len(cancellation_ops), 0)

if __name__ == "__main__":
    unittest.main()
