import unittest

from shared.models import build_master_payload
from shared.severity import determine_hazard_severity


class HazardSeverityTests(unittest.TestCase):
    def test_critical_categories_and_terms(self):
        self.assertEqual(determine_hazard_severity("NAVAL FIRING EXERCISE.", ["mil_fire"]), "critical")
        self.assertEqual(determine_hazard_severity("DISTRESS ALERT RECEIVED.", ["sar"]), "critical")
        self.assertEqual(determine_hazard_severity("TSUNAMI WARNING.", ["weather"]), "critical")

    def test_high_hazard_categories(self):
        self.assertEqual(determine_hazard_severity("DERELICT VESSEL ADRIFT.", ["drift", "drifting"]), "high")
        self.assertEqual(determine_hazard_severity("DANGEROUS WRECK.", ["wreck", "subsea"]), "high")
        self.assertEqual(determine_hazard_severity("LIGHT UNLIT.", ["aton"]), "high")

    def test_moderate_operational_notices(self):
        self.assertEqual(determine_hazard_severity("SUBMARINE CABLE OPERATIONS.", ["cable", "subsea"]), "moderate")
        self.assertEqual(determine_hazard_severity("CHART CORRECTION.", ["general_chart", "general"]), "moderate")

    def test_critical_secondary_category_takes_precedence(self):
        self.assertEqual(determine_hazard_severity("Cable operations and military firing.", ["cable", "mil_fire"]), "critical")

    def test_master_payload_persists_derived_severity_without_geometry_guessing(self):
        payload = build_master_payload({
            "navarea": "NAVAREA I",
            "warning_id": "0001/26",
            "raw_text": "NAVAL GUNNERY EXERCISE.",
            "categories": ["mil_fire", "military"],
            "status": "active",
        })
        self.assertEqual(payload["severity"], "critical")
        self.assertEqual(payload["triage_tier"], "C")
        self.assertEqual(payload["unplotted_reason"], "no_valid_geometry")

    def test_valid_explicit_severity_is_preserved(self):
        payload = build_master_payload({
            "navarea": "NAVAREA I",
            "warning_id": "0002/26",
            "raw_text": "NAVAL GUNNERY EXERCISE.",
            "categories": ["mil_fire"],
            "severity": "moderate",
        })
        self.assertEqual(payload["severity"], "moderate")


if __name__ == "__main__":
    unittest.main()
