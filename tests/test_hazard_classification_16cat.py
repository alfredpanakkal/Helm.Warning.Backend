#!/usr/bin/env python3
"""tests/test_hazard_classification_16cat.py — 16-category hazard taxonomy verification.

Verifies:
  1. Each of the canonical 16 categories maps to its primary winner (cats[0])
     from representative IMO/WWNWS bulletin text.
  2. Legacy aliases are appended appropriately in categories array.
  3. Priority ladder handles overlapping keywords deterministically:
     - GNSS/GPS jamming (service_status) takes precedence over offshore rigs
     - Space/rocket debris (mil_fire) takes precedence over drifting objects
     - Ordnance demolition (uxo) vs marine civil demolition (ops)
     - Floodlights (rig) vs lights/buoys (aton)
     - Pure cancellation/completion notices file as general
"""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.utils import classify_hazard, classify_hazard_categories


class TestCanonical16Categories(unittest.TestCase):
    def test_sar_category(self):
        raw = "NAVAREA IV 101/26\nDISTRESS ALERT RECEIVED FROM S/V OCEAN BLUE. SEARCH AND RESCUE OPERATION IN PROGRESS."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "sar")

    def test_mil_fire_category(self):
        raw = "NAVAREA VIII 202/26\nGUNNERY AND MISSILE FIRING EXERCISES IN PROGRESS BY NAVAL FORCES."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "mil_fire")
        self.assertIn("military", cats)
        self.assertEqual(classify_hazard(raw), "military")
        self.assertEqual(classify_hazard(raw, canonical=True), "mil_fire")

    def test_uxo_category(self):
        raw = "NAVAREA I 303/26\nDRIFTING SEA MINE REPORTED IN VICINITY. DANGEROUS TO NAVIGATION."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "uxo")
        self.assertIn("military", cats)

    def test_weather_category(self):
        raw = "NAVAREA XI 404/26\nSEVERE CYCLONE WARNING. GALE FORCE WINDS AND HEAVY SWELL REPORTED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "weather")

    def test_ice_category(self):
        raw = "NAVAREA IV 505/26\nINTERNATIONAL ICE PATROL REPORTS LARGE ICEBERG AND PACK ICE SIGHTED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "ice")

    def test_security_category(self):
        raw = "NAVAREA IX 606/26\nSECURITY ADVISORY. SUSPICIOUS SKIFF REPORTED APPROACHING COMMERCIAL VESSEL."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "security")

    def test_drift_category(self):
        raw = "NAVAREA II 707/26\nDERELICT FISHING VESSEL ADRIFT. DRIFTING CONTAINER DANGEROUS TO SURFACE NAVIGATION."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "drift")
        self.assertIn("drifting", cats)
        self.assertEqual(classify_hazard(raw), "drifting")
        self.assertEqual(classify_hazard(raw, canonical=True), "drift")

    def test_wreck_category(self):
        raw = "NAVAREA I 808/26\nDANGEROUS SUNKEN WRECK LOCATED. DEPTH UNKNOWN."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "wreck")
        self.assertIn("subsea", cats)
        self.assertEqual(classify_hazard(raw), "subsea")
        self.assertEqual(classify_hazard(raw, canonical=True), "wreck")

    def test_cable_category(self):
        raw = "NAVAREA VII 909/26\nC/S CABLE INNOVATOR CARRYING OUT SUBMARINE CABLE REPAIR AND PIPE SURVEY."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "cable")
        self.assertIn("subsea", cats)
        self.assertEqual(classify_hazard(raw), "subsea")
        self.assertEqual(classify_hazard(raw, canonical=True), "cable")

    def test_survey_category(self):
        raw = "NAVAREA IV 1010/26\nM/V SEISMIC VENTURE CONDUCTING HYDROGRAPHIC SURVEY WITH 6000M TOWED SENSORS."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "survey")
        self.assertIn("subsea", cats)
        self.assertEqual(classify_hazard(raw), "subsea")
        self.assertEqual(classify_hazard(raw, canonical=True), "survey")

    def test_rig_category(self):
        raw = "NAVAREA I 1111/26\nDRILLING RIG NOBLE LLOYD NOBLE STATIONED. 500M SAFETY ZONE ESTABLISHED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "rig")
        self.assertIn("offshore", cats)
        self.assertEqual(classify_hazard(raw), "offshore")
        self.assertEqual(classify_hazard(raw, canonical=True), "rig")

    def test_aton_category(self):
        raw = "NAVAREA VIII 1212/26\nNORTH CARDINAL BUOY UNLIT AND DAMAGED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "aton")
        self.assertIn("aton", cats)
        self.assertEqual(classify_hazard(raw), "aton")
        self.assertEqual(classify_hazard(raw, canonical=True), "aton")

    def test_restricted_category(self):
        raw = "NAVAREA XII 1313/26\nRESTRICTED AREA ESTABLISHED. UNAUTHORIZED NAVIGATION PROHIBITED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "restricted")

    def test_ops_category(self):
        raw = "NAVAREA I 1414/26\nDREDGING OPERATIONS AND COMMERCIAL DIVING ACTIVITIES UNDERWAY BY TUG TITAN."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "ops")
        self.assertIn("subsea", cats)
        self.assertEqual(classify_hazard(raw), "subsea")
        self.assertEqual(classify_hazard(raw, canonical=True), "ops")

    def test_service_status_category(self):
        raw = "NAVAREA IX 1515/26\nRADIO SERVICES INTERRUPTED. DGPS TRANSMITTER AT STATION OFF AIR."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "service_status")
        self.assertIn("electronic", cats)
        self.assertEqual(classify_hazard(raw), "electronic")
        self.assertEqual(classify_hazard(raw, canonical=True), "service_status")

    def test_general_chart_category(self):
        raw = "NAVAREA I 1616/26\nDEPTH CORRECTION. NEW SOUNDINGS SHOW SHOALING IN NORTH SEA CHANNEL. CHARTS AMENDED."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "general_chart")
        self.assertIn("general", cats)
        self.assertEqual(classify_hazard(raw), "general")
        self.assertEqual(classify_hazard(raw, canonical=True), "general_chart")


class TestAdversarialHygieneAndPriority(unittest.TestCase):
    def test_gnss_jamming_near_rigs_priority(self):
        # GNSS jamming takes priority over platform/rig mentions
        raw = "GPS AND GNSS JAMMING OBSERVED IN VICINITY OF OFFSHORE PLATFORMS AND RIGS."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "service_status")
        self.assertIn("electronic", cats)
        self.assertIn("rig", cats)
        self.assertIn("offshore", cats)

    def test_space_debris_priority_over_drifting(self):
        # Rocket/space debris falls under mil_fire, not drift
        raw = "HAZARD AREA ESTABLISHED FOR FALLING ROCKET DEBRIS AND SPACE DEBRIS RE-ENTRY."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "mil_fire")
        self.assertNotIn("drift", cats)
        self.assertNotIn("drifting", cats)

    def test_demolition_without_ordnance_is_ops(self):
        # Civil marine demolition (e.g. quay wall demolition) without explosives/bombs
        raw = "MARINE DEMOLITION OPERATIONS UNDERWAY AT QUAY WALL 4."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "ops")
        self.assertNotIn("uxo", cats)

    def test_demolition_with_ordnance_is_uxo(self):
        # Demolition of unexploded bomb/warhead
        raw = "CONTROLLED DEMOLITION OF UNEXPLODED ORDNANCE AND TORPEDO WARHEAD."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "uxo")

    def test_floodlights_on_rig_not_aton(self):
        # Working floodlights on a rig should not trigger AtoN (light)
        raw = "OFFSHORE DRILLING RIG EQUIPPED WITH WORKING FLOODLIGHTS."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats[0], "rig")
        self.assertNotIn("aton", cats)

    def test_completed_survey_is_general(self):
        # Survey completed notice stripped of dead hazard
        raw = "SEISMIC SURVEY OPERATIONS COMPLETED. CANCEL THIS NOTICE."
        cats = classify_hazard_categories(raw)
        self.assertEqual(cats, ["general"])


if __name__ == "__main__":
    unittest.main()
