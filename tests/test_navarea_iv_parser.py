#!/usr/bin/env python3
"""test_navarea_iv_parser.py — NAVAREA IV deterministic parser tests.

Runs the full parse_memo_text() pipeline over the verbatim live memo fixture
and asserts the master/geometry payload contract (mirrors
test_navarea_xii_parser.py). All expected values verified against the
DailyMemIV.txt snapshot of 051505Z MAR.
"""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.navarea_iv_parser import parse_memo_text, SOURCE_ID
from shared.models import build_master_payload, build_geometry_payloads

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "navarea_iv")


def _load(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


class TestFullMemoParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parse_memo_text(_load("daily_memo_snapshot.txt"))
        cls.by_id = {w["warning_id"]: w for w in cls.parsed["nav_warnings"]}

    def test_counts(self):
        self.assertEqual(len(self.parsed["nav_warnings"]), 108)
        self.assertEqual(len(self.parsed["raw_messages"]), 108)
        self.assertEqual(len(self.by_id), 108)  # all unique

    def test_newest_first(self):
        self.assertEqual(self.parsed["nav_warnings"][0]["warning_id"], "NAVAREA IV 207/26")

    def test_memo_marker(self):
        self.assertEqual(self.parsed["memo"]["in_force_dtg"], "051505Z MAR")

    def test_source_and_navarea(self):
        for w in self.parsed["nav_warnings"]:
            self.assertEqual(w["source_id"], SOURCE_ID)
            self.assertEqual(w["navarea"], "IV")
            self.assertEqual(w["status"], "active")

    def test_checksum_matches_raw_text(self):
        for w, m in zip(self.parsed["nav_warnings"], self.parsed["raw_messages"]):
            self.assertEqual(m["checksum_sha256"], hashlib.sha256(w["raw_text"].encode()).hexdigest())

    def test_dtg_carried_as_issued_text(self):
        self.assertEqual(self.by_id["NAVAREA IV 207/26"]["issued_text"], "040658Z MAR 26")
        self.assertIsNone(self.by_id["NAVAREA IV 367/22"]["issued_text"])  # MSGID legacy block

    def test_titles(self):
        self.assertEqual(self.by_id["NAVAREA IV 207/26"]["title"], "NORTH ATLANTIC. FLORIDA.")
        self.assertEqual(self.by_id["NAVAREA IV 16/26"]["title"], "GULF OF AMERICA. TEXAS.")

    def test_unpadded_canonical_ids(self):
        self.assertIn("NAVAREA IV 7/26", self.by_id)
        self.assertIn("NAVAREA IV 12/25", self.by_id)

    def test_categories(self):
        self.assertEqual(self.by_id["NAVAREA IV 161/26"]["category"], "aton")
        self.assertEqual(self.by_id["NAVAREA IV 204/26"]["category"], "offshore")


class TestSubAreaGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {w["warning_id"]: w for w in
                     parse_memo_text(_load("daily_memo_snapshot.txt"))["nav_warnings"]}

    def test_207_two_polygon_subareas(self):
        w = self.by_id["NAVAREA IV 207/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B"])
        features = w["spatial"]["features"]
        self.assertEqual([f["properties"]["zone_label"] for f in features], ["A", "B"])
        for f in features:
            self.assertEqual(f["geometry"]["type"], "Polygon")
        # A: 6 vertices + closing point; B: 4 vertices + closing point
        self.assertEqual(len(features[0]["geometry"]["coordinates"][0]), 7)
        self.assertEqual(len(features[1]["geometry"]["coordinates"][0]), 5)

    def test_206_sea_ice_limits_including_wrapped_coord(self):
        w = self.by_id["NAVAREA IV 206/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B", "C"])
        features = w["spatial"]["features"]
        self.assertEqual([len(f["geometry"]["coordinates"][0]) for f in features], [11, 9, 9])

    def test_204_modu_list_95_point_subareas(self):
        w = self.by_id["NAVAREA IV 204/26"]
        self.assertEqual(len(w["geometry_sub_areas"]), 95)
        self.assertEqual(w["geometry_sub_areas"][0], "A")
        self.assertEqual(w["geometry_sub_areas"][-1], "AAAQ")
        for f in w["spatial"]["features"]:
            self.assertEqual(f["geometry"]["type"], "Point")

    def test_1292_moorings_22_points(self):
        w = self.by_id["NAVAREA IV 1292/25"]
        self.assertEqual(len(w["geometry_sub_areas"]), 22)
        for f in w["spatial"]["features"]:
            self.assertEqual(f["geometry"]["type"], "Point")

    def test_1170_depths_after_rejoin(self):
        w = self.by_id["NAVAREA IV 1170/25"]
        self.assertEqual(len(w["geometry_sub_areas"]), 12)
        for f in w["spatial"]["features"]:
            self.assertEqual(f["geometry"]["type"], "Point")

    def test_466_wrapped_degrees_hyphen(self):
        # "12-\n28.85N" -> Point at 12-28.85N 081-43.83W
        w = self.by_id["NAVAREA IV 466/25"]
        self.assertEqual(len(w["spatial"]["features"]), 1)
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Point")

    def test_1524_title_line_not_subarea(self):
        # "ST. KITTS AND NEVIS." rejected as a marker: 13-vertex polygon
        w = self.by_id["NAVAREA IV 1524/24"]
        self.assertEqual(len(w["spatial"]["features"]), 1)
        geom = w["spatial"]["features"][0]["geometry"]
        self.assertEqual(geom["type"], "Polygon")
        self.assertEqual(len(geom["coordinates"][0]), 14)  # 13 + closing

    def test_133_trackline_linestring(self):
        w = self.by_id["NAVAREA IV 133/26"]
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "LineString")
        self.assertEqual(len(w["spatial"]["features"][0]["geometry"]["coordinates"]), 2)

    def test_7_four_polygon_subareas(self):
        w = self.by_id["NAVAREA IV 7/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B", "C", "D"])
        for f in w["spatial"]["features"]:
            self.assertEqual(f["geometry"]["type"], "Polygon")

    def test_158_lowercase_dtg_three_point_lights(self):
        w = self.by_id["NAVAREA IV 158/26"]
        self.assertEqual(w["geometry_sub_areas"], ["A", "B", "C"])
        for f in w["spatial"]["features"]:
            self.assertEqual(f["geometry"]["type"], "Point")

    def test_113_header_continuation_point(self):
        w = self.by_id["NAVAREA IV 113/26"]
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Point")

    def test_no_geometry_warnings(self):
        # Meta list, prose-only, and legacy deg-min-sec warnings
        expected_tier_c = {
            "NAVAREA IV 190/26", "NAVAREA IV 190/25",
            "NAVAREA IV 1157/21", "NAVAREA IV 278/21", "NAVAREA IV 277/21",
        }
        actual = {wid for wid, w in self.by_id.items() if w["spatial"] is None}
        self.assertEqual(actual, expected_tier_c)

    def test_153_closed_trackline_polygon(self):
        w = self.by_id["NAVAREA IV 153/26"]
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Polygon")


class TestGeometryPayloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {w["warning_id"]: w for w in
                     parse_memo_text(_load("daily_memo_snapshot.txt"))["nav_warnings"]}

    def test_one_row_per_sub_area_with_check_vocabulary(self):
        w = self.by_id["NAVAREA IV 207/26"]
        geoms = build_geometry_payloads(w)
        self.assertEqual(len(geoms), 2)
        self.assertEqual([g["zone_label"] for g in geoms], ["A", "B"])
        for g in geoms:
            self.assertEqual(g["feature_type"], "POLYGON")

    def test_linestring_maps_to_line(self):
        w = self.by_id["NAVAREA IV 133/26"]
        geoms = build_geometry_payloads(w)
        self.assertEqual(len(geoms), 1)
        self.assertEqual(geoms[0]["feature_type"], "LINE")

    def test_master_payload_triage(self):
        w = self.by_id["NAVAREA IV 207/26"]
        master = build_master_payload(w)
        self.assertEqual(master["canonical_id"], "NAVAREA IV 207/26")
        self.assertEqual(master["triage_tier"], "A")
        self.assertIsNone(master["unplotted_reason"])

        meta = build_master_payload(self.by_id["NAVAREA IV 190/26"])
        self.assertEqual(meta["triage_tier"], "C")
        self.assertEqual(meta["unplotted_reason"], "no_valid_geometry")

    def test_master_strips_legacy_columns(self):
        master = build_master_payload(self.by_id["NAVAREA IV 161/26"])
        for legacy in ("latitude", "longitude", "spatial", "issued_text", "cross_refs"):
            self.assertNotIn(legacy, master)
        self.assertEqual(master["source_id"], SOURCE_ID)


class TestCrossRefsInParsedWarnings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {w["warning_id"]: w for w in
                     parse_memo_text(_load("daily_memo_snapshot.txt"))["nav_warnings"]}

    def test_16_multi_cancellation_refs(self):
        refs = self.by_id["NAVAREA IV 16/26"]["cross_refs"]
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual([(c["number"], c["year"]) for c in cancels], [("964", "25"), ("1110", "25")])

    def test_161_cancel_with_paren_suffix(self):
        refs = self.by_id["NAVAREA IV 161/26"]["cross_refs"]
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual([(c["number"], c["year"]) for c in cancels], [("1008", "25")])

    def test_113_header_ref_from_continuation(self):
        refs = self.by_id["NAVAREA IV 113/26"]["cross_refs"]
        self.assertEqual([(r["number"], r["kind"]) for r in refs], [("26", "header_ref")])

    def test_207_header_refs_and_no_self_cancel(self):
        refs = self.by_id["NAVAREA IV 207/26"]["cross_refs"]
        self.assertEqual([(r["number"], r["kind"]) for r in refs],
                         [("11", "header_ref"), ("26", "header_ref")])


class TestEmptyAndEdgeInputs(unittest.TestCase):
    def test_empty_memo(self):
        parsed = parse_memo_text("")
        self.assertEqual(parsed["nav_warnings"], [])
        self.assertEqual(parsed["spatial_features"], [])
        self.assertIsNone(parsed["memo"]["in_force_dtg"])

    def test_single_warning_fixture_16(self):
        parsed = parse_memo_text(_load("16_26.txt"))
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA IV 16/26")
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Polygon")

    def test_single_warning_fixture_466(self):
        parsed = parse_memo_text(_load("466_25.txt"))
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA IV 466/25")
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Point")

    def test_single_warning_fixture_113(self):
        parsed = parse_memo_text(_load("113_26.txt"))
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA IV 113/26")
        self.assertEqual([r["number"] for r in w["cross_refs"]], ["26"])

    def test_single_warning_fixture_1524(self):
        parsed = parse_memo_text(_load("1524_24.txt"))
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA IV 1524/24")
        self.assertEqual(w["spatial"]["features"][0]["geometry"]["type"], "Polygon")


if __name__ == "__main__":
    unittest.main()
