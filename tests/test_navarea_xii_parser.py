#!/usr/bin/env python3
"""test_navarea_xii_parser.py — NAVAREA XII deterministic parser tests.

Runs the full parse_memo_text() pipeline over the verbatim live memo fixture
and asserts the master/geometry payload contract:
  - segmentation count/order (delegated to preprocessing, re-verified end-to-end)
  - sub-area FeatureCollection geometry with per-feature zone_label
  - build_geometry_payloads() yields one CHECK-vocabulary row per sub-area
  - cross-references survive into nav_warnings for the sync supersede pass
"""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.navarea_xii_parser import parse_memo_text, SOURCE_ID
from shared.models import build_master_payload, build_geometry_payloads

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "navarea_xii")


def _load(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


class TestFullMemoParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parse_memo_text(_load("daily_memo_snapshot.txt"))
        cls.by_id = {w["warning_id"]: w for w in cls.parsed["nav_warnings"]}

    def test_counts(self):
        self.assertEqual(len(self.parsed["nav_warnings"]), 32)
        self.assertEqual(len(self.parsed["raw_messages"]), 32)
        self.assertEqual(len(self.by_id), 32)  # all unique

    def test_newest_first(self):
        self.assertEqual(self.parsed["nav_warnings"][0]["warning_id"], "NAVAREA XII 151/26")

    def test_memo_marker(self):
        self.assertEqual(self.parsed["memo"]["in_force_dtg"], "051505Z MAR")

    def test_source_and_navarea(self):
        for w in self.parsed["nav_warnings"]:
            self.assertEqual(w["source_id"], SOURCE_ID)
            self.assertEqual(w["navarea"], "XII")
            self.assertEqual(w["status"], "active")

    def test_checksum_matches_raw_text(self):
        for w, m in zip(self.parsed["nav_warnings"], self.parsed["raw_messages"]):
            self.assertEqual(m["checksum_sha256"], hashlib.sha256(w["raw_text"].encode()).hexdigest())

    def test_dtg_carried_as_issued_text(self):
        self.assertEqual(self.by_id["NAVAREA XII 151/26"]["issued_text"], "040124Z MAR 26")
        self.assertIsNone(self.by_id["NAVAREA XII 244/22"]["issued_text"])

    def test_titles(self):
        self.assertEqual(self.by_id["NAVAREA XII 151/26"]["title"], "NORTH PACIFIC. CALIFORNIA.")
        self.assertTrue(self.by_id["NAVAREA XII 140/26"]["title"].startswith("NORTH PACIFIC. COLOMBIA."))


class TestSubAreaGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {w["warning_id"]: w for w in
                     parse_memo_text(_load("daily_memo_snapshot.txt"))["nav_warnings"]}

    def test_151_three_subarea_features(self):
        w = self.by_id["NAVAREA XII 151/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B", "C"])
        self.assertEqual(w["spatial"]["type"], "FeatureCollection")
        features = w["spatial"]["features"]
        self.assertEqual([f["properties"]["zone_label"] for f in features], ["A", "B", "C"])
        for f in features:
            self.assertEqual(f["geometry"]["type"], "Polygon")

    def test_148_two_subarea_features_after_rejoin(self):
        w = self.by_id["NAVAREA XII 148/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B"])
        features = w["spatial"]["features"]
        # sub-area A: 6 vertices + closing point
        self.assertEqual(len(features[0]["geometry"]["coordinates"][0]), 7)
        self.assertEqual(len(features[1]["geometry"]["coordinates"][0]), 8)

    def test_140_single_point(self):
        w = self.by_id["NAVAREA XII 140/26"]
        self.assertEqual(w["spatial"]["type"], "FeatureCollection")
        self.assertEqual(len(w["spatial"]["features"]), 1)
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Point")

    def test_88_dsc_facility_points(self):
        w = self.by_id["NAVAREA XII 88/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B", "C"])
        for f in w["spatial"]["features"]:
            self.assertEqual(f["geometry"]["type"], "Point")

    def test_133_meta_list_has_no_geometry(self):
        w = self.by_id["NAVAREA XII 133/26"]
        self.assertIsNone(w["spatial"])
        self.assertIsNone(w["latitude"])


class TestGeometryPayloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {w["warning_id"]: w for w in
                     parse_memo_text(_load("daily_memo_snapshot.txt"))["nav_warnings"]}

    def test_one_row_per_sub_area_with_check_vocabulary(self):
        w = self.by_id["NAVAREA XII 148/26"]
        geoms = build_geometry_payloads(w)
        self.assertEqual(len(geoms), 2)
        self.assertEqual([g["zone_label"] for g in geoms], ["A", "B"])
        for g in geoms:
            self.assertEqual(g["feature_type"], "POLYGON")

    def test_master_payload_triage(self):
        w = self.by_id["NAVAREA XII 151/26"]
        master = build_master_payload(w)
        self.assertEqual(master["canonical_id"], "NAVAREA XII 151/26")
        self.assertEqual(master["triage_tier"], "A")
        self.assertIsNone(master["unplotted_reason"])

        meta = build_master_payload(self.by_id["NAVAREA XII 133/26"])
        self.assertEqual(meta["triage_tier"], "C")
        self.assertEqual(meta["unplotted_reason"], "no_valid_geometry")

    def test_master_strips_legacy_columns(self):
        master = build_master_payload(self.by_id["NAVAREA XII 140/26"])
        for legacy in ("latitude", "longitude", "spatial", "issued_text", "cross_refs"):
            self.assertNotIn(legacy, master)
        self.assertEqual(master["source_id"], SOURCE_ID)


class TestCrossRefsInParsedWarnings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {w["warning_id"]: w for w in
                     parse_memo_text(_load("daily_memo_snapshot.txt"))["nav_warnings"]}

    def test_142_cancellation_ref(self):
        refs = self.by_id["NAVAREA XII 142/26"]["cross_refs"]
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual([(c["number"], c["year"]) for c in cancels], [("127", "26")])

    def test_150_header_refs(self):
        refs = self.by_id["NAVAREA XII 150/26"]["cross_refs"]
        header = [r for r in refs if r["kind"] == "header_ref"]
        self.assertEqual([r["number"] for r in header], ["021", "022"])

    def test_151_self_cancel_not_a_ref(self):
        refs = self.by_id["NAVAREA XII 151/26"]["cross_refs"]
        self.assertFalse([r for r in refs if r["kind"] == "cancellation"])

    def test_88_gen_ignored(self):
        self.assertEqual(self.by_id["NAVAREA XII 88/26"]["cross_refs"], [])


class TestEmptyAndEdgeInputs(unittest.TestCase):
    def test_empty_memo(self):
        parsed = parse_memo_text("")
        self.assertEqual(parsed["nav_warnings"], [])
        self.assertEqual(parsed["spatial_features"], [])
        self.assertIsNone(parsed["memo"]["in_force_dtg"])

    def test_single_warning_fixture(self):
        parsed = parse_memo_text(_load("150_26.txt"))
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA XII 150/26")
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Polygon")


if __name__ == "__main__":
    unittest.main()
