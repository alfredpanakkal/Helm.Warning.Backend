#!/usr/bin/env python3
"""
tests/test_audit_failure_clustering.py — Phase 3 WP1 clustering tests.

Fully offline (stdlib only, no API key, no DB, no network):
  - determinism: same input -> same cluster ids every run
  - digit masking fixtures (41°20.5'N -> ##°##.#'N)
  - digit-only differences cluster together; wording differences do not
  - whitespace/case normalization
  - excluded codes (protected_conflict, geometry_unknown) never cluster
  - severity mapping + ranking (analyzable first, then active, then size)
  - example diversity (distinct statuses first, capped at 3)
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.audit_failure_clustering import (
    ANALYSIS_SEVERITIES,
    EXCLUDED_ISSUE_CODES,
    cluster_id_for,
    cluster_issues,
    text_signature,
)


def make_issue(code="COORDINATE_OUT_OF_BOUNDS", severity="ERROR",
               wid=None, canonical_id=None, navarea="NA IV"):
    return {
        "code": code,
        "severity": severity,
        "warning_id": wid or "w-0",
        "canonical_id": canonical_id or "NAVAREA IV 001/26",
        "navarea": navarea,
        "field": "geometries[0].coordinates",
        "message": "fixture issue",
        "current_value": None,
    }


def make_record(raw_text=None, status="active", navarea="NA IV", canonical_id=None):
    return {
        "raw_text": raw_text or "1. BOUNDED BY 41-20.5N 011-14.5W",
        "status": status,
        "navarea": navarea,
        "canonical_id": canonical_id or "NAVAREA IV 001/26",
    }


class TestTextSignature(unittest.TestCase):
    # 1. Digit-masking fixture from the plan
    def test_digit_masking(self):
        self.assertEqual(text_signature("41°20.5'N"), "##°##.#'N")

    # 2. Hemisphere letters and keywords stay unmasked
    def test_hemisphere_and_keywords_unmasked(self):
        sig = text_signature("BOUNDED BY 41-20.5N RADIUS 5")
        self.assertEqual(sig, "BOUNDED BY ##-##.#N RADIUS #")

    # 3. Whitespace collapsed, case normalized
    def test_whitespace_and_case_normalized(self):
        a = text_signature("bounded   by\nradius")
        b = text_signature("BOUNDED BY  RADIUS")
        self.assertEqual(a, b)

    # 4. Signature capped
    def test_signature_capped(self):
        self.assertLessEqual(len(text_signature("A " * 2000)), 600)


class TestClusterId(unittest.TestCase):
    # 5. Stable ids: same key -> same id, different key -> different id
    def test_cluster_id_stable_and_distinct(self):
        a = cluster_id_for("CODE_X", "NA IV", "SIG")
        self.assertEqual(a, cluster_id_for("CODE_X", "NA IV", "SIG"))
        self.assertNotEqual(a, cluster_id_for("CODE_X", "NA IV", "SIG "))
        self.assertNotEqual(a, cluster_id_for("CODE_Y", "NA IV", "SIG"))
        self.assertNotEqual(a, cluster_id_for("CODE_X", "NA V", "SIG"))


class TestClustering(unittest.TestCase):
    # 6. Determinism: same input -> same output every run
    def test_same_input_same_output(self):
        issues = [
            make_issue(wid="w-1", canonical_id="NAVAREA IV 001/26"),
            make_issue(wid="w-2", canonical_id="NAVAREA IV 002/26"),
            make_issue(code="INVALID_STATUS", severity="WARNING", wid="w-3"),
        ]
        records = {
            "w-1": make_record(raw_text="1. BOUNDED BY 41-20.5N 011-14.5W"),
            "w-2": make_record(raw_text="1. BOUNDED BY 55-07.3N 012-31.9W"),
            "w-3": make_record(raw_text="CANCEL THIS", status="cancelled"),
        }
        first = cluster_issues(issues, records)
        second = cluster_issues(issues, records)
        self.assertEqual([c["cluster_id"] for c in first], [c["cluster_id"] for c in second])
        self.assertEqual(first, second)

    # 7. Digit-only differences merge into ONE cluster
    def test_digit_only_difference_clusters_together(self):
        issues = [
            make_issue(wid="w-1"),
            make_issue(wid="w-2"),
        ]
        records = {
            "w-1": make_record(raw_text="BOUNDED BY 41-20.5N 011-14.5W RADIUS 3"),
            "w-2": make_record(raw_text="BOUNDED BY 07-11.0S 002-45.8E RADIUS 5"),
        }
        clusters = cluster_issues(issues, records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["count"], 2)
        self.assertEqual(sorted(clusters[0]["affected_warning_ids"]), ["w-1", "w-2"])

    # 8. Different wording does NOT merge
    def test_different_patterns_do_not_merge(self):
        issues = [make_issue(wid="w-1"), make_issue(wid="w-2")]
        records = {
            "w-1": make_record(raw_text="BOUNDED BY POINTS A B C D"),
            "w-2": make_record(raw_text="JOINING THE FOLLOWING LINES"),
        }
        clusters = cluster_issues(issues, records)
        self.assertEqual(len(clusters), 2)
        self.assertNotEqual(clusters[0]["cluster_id"], clusters[1]["cluster_id"])

    # 9. Excluded codes never cluster
    def test_excluded_codes_dropped(self):
        issues = [
            make_issue(code="PROTECTED_CONFLICT", wid="w-1"),
            make_issue(code="GEOMETRY_UNKNOWN", wid="w-2"),
        ]
        records = {"w-1": make_record(), "w-2": make_record()}
        self.assertEqual(cluster_issues(issues, records), [])
        self.assertIn("PROTECTED_CONFLICT", EXCLUDED_ISSUE_CODES)
        self.assertIn("GEOMETRY_UNKNOWN", EXCLUDED_ISSUE_CODES)

    # 10. Interim severity: ERROR -> major (analyzable), WARNING -> minor
    def test_severity_mapping_and_analyzable_flag(self):
        issues = [
            make_issue(code="COORDINATE_OUT_OF_BOUNDS", severity="ERROR", wid="w-1"),
            make_issue(code="DISCREPANCY_UNPLOTTED_WITH_COORDINATES", severity="WARNING", wid="w-2"),
        ]
        records = {
            "w-1": make_record(raw_text="BOUNDED BY X"),
            "w-2": make_record(raw_text="DISCREPANCY TEXT HERE", status="active"),
        }
        clusters = cluster_issues(issues, records)
        by_code = {c["code"]: c for c in clusters}
        self.assertEqual(by_code["COORDINATE_OUT_OF_BOUNDS"]["severity"], "major")
        self.assertTrue(by_code["COORDINATE_OUT_OF_BOUNDS"]["analyzable"])
        self.assertEqual(by_code["DISCREPANCY_UNPLOTTED_WITH_COORDINATES"]["severity"], "minor")
        self.assertFalse(by_code["DISCREPANCY_UNPLOTTED_WITH_COORDINATES"]["analyzable"])
        # Analyzable ranks first
        self.assertEqual(clusters[0]["code"], "COORDINATE_OUT_OF_BOUNDS")
        self.assertEqual(ANALYSIS_SEVERITIES, ("critical", "major"))

    # 11. Ranking within same severity: more active warnings first, then size
    def test_ranking_active_then_size(self):
        issues = [
            make_issue(code="CODE_A", wid="w-1"),
            make_issue(code="CODE_A", wid="w-2"),
            make_issue(code="CODE_B", wid="w-3"),
        ]
        records = {
            "w-1": make_record(raw_text="PATTERN ALPHA", status="active"),
            "w-2": make_record(raw_text="PATTERN ALPHA", status="cancelled"),
            "w-3": make_record(raw_text="PATTERN ALPHA", status="cancelled"),
        }
        clusters = cluster_issues(issues, records)
        # Same code/navarea/signature -> one cluster, but ranking still verifiable:
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["active_count"], 1)
        self.assertEqual(clusters[0]["per_status"], {"active": 1, "cancelled": 2})

    def test_ranking_across_clusters(self):
        issues = [
            make_issue(code="CODE_A", wid="w-1"),
            make_issue(code="CODE_B", wid="w-2"),
            make_issue(code="CODE_B", wid="w-3"),
        ]
        records = {
            "w-1": make_record(raw_text="PATTERN ALPHA ACTIVE", status="active"),
            "w-2": make_record(raw_text="PATTERN BETA CANCELLED", status="cancelled"),
            "w-3": make_record(raw_text="PATTERN BETA CANCELLED", status="cancelled"),
        }
        clusters = cluster_issues(issues, records)
        # A: 1 active; B: 0 active, size 2 -> A first despite B being bigger
        self.assertEqual(clusters[0]["code"], "CODE_A")
        self.assertEqual(clusters[1]["code"], "CODE_B")

    # 12. Example diversity: distinct statuses first, capped at 3
    def test_example_diversity(self):
        issues = [
            make_issue(code="CODE_C", wid="w-1"),
            make_issue(code="CODE_C", wid="w-2"),
            make_issue(code="CODE_C", wid="w-3"),
            make_issue(code="CODE_C", wid="w-4"),
            make_issue(code="CODE_C", wid="w-5"),
        ]
        records = {
            "w-1": make_record(raw_text="PATTERN GAMMA", status="active"),
            "w-2": make_record(raw_text="PATTERN GAMMA", status="active"),
            "w-3": make_record(raw_text="PATTERN GAMMA", status="cancelled"),
            "w-4": make_record(raw_text="PATTERN GAMMA", status="cancelled"),
            "w-5": make_record(raw_text="PATTERN GAMMA", status="expired"),
        }
        clusters = cluster_issues(issues, records)
        self.assertEqual(len(clusters), 1)
        examples = clusters[0]["examples"]
        self.assertLessEqual(len(examples), 3)
        statuses = [e["status"] for e in examples]
        self.assertEqual(len(set(statuses)), 3)  # active, cancelled, expired
        for e in examples:
            self.assertTrue(e["raw_snippet"])
            self.assertIn(e["warning_id"], clusters[0]["affected_warning_ids"])

    # 13. Missing records (no raw_text) still cluster without crashing
    def test_missing_records_no_crash(self):
        issues = [make_issue(wid="w-gone")]
        clusters = cluster_issues(issues, {})
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["signature"], "")


if __name__ == "__main__":
    unittest.main()
