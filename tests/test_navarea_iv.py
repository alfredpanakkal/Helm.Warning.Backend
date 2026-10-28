#!/usr/bin/env python3
"""test_navarea_iv.py — NAVAREA IV (NGA Daily Memo) preprocessing tests.

Run against the verbatim live memo fixture (msi.nga.mil DailyMemIV.txt
snapshot). Covers IV-specific edge cases absent from XII:
  - integer-minute coordinates ("44-20N")
  - wrapped-token variants: "57\n-00N", "12-\n28.85N", "27-09\n.1N"
  - lowercase month DTGs ("200632Z Feb 26")
  - header parens wrapped to the next line ("NAVAREA IV 113/26\\n(26).")
  - multi-ref cancels ("CANCEL NAVAREA IV 964/25, 1110/25.")
  - multi-letter sub-area labels (MODU list A..AAAQ in 204/26)
  - title-line false-positive marker rejection ("ST. KITTS AND NEVIS.")
  - geometry-clause segmentation incl. trackline classification (206/26)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.navarea_iv_text import (
    rejoin_wrapped_coords,
    get_in_force_dtg,
    split_into_warnings,
    extract_cross_refs,
    split_sub_areas,
    extract_geometry_clauses,
    ring_to_trackline,
)

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "navarea_iv")


def _load(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


class TestRejoinWrappedCoords(unittest.TestCase):
    def test_xii_style_wrap(self):
        # "58-10.\n50N" (1170/25 depths list)
        self.assertEqual(rejoin_wrapped_coords("58-10.\n50N 068-19.17W."), "58-10.50N 068-19.17W.")

    def test_degrees_then_minutes_next_line(self):
        # "57\n-00N" (206/26 sea-ice limit sub-area B)
        self.assertEqual(rejoin_wrapped_coords("57\n-00N 056-00W,"), "57-00N 056-00W,")

    def test_decimal_part_next_line(self):
        # "27-09\n.1N" (204/26 MODU list)
        self.assertEqual(rejoin_wrapped_coords("27-09\n.1N 091-12.7W."), "27-09.1N 091-12.7W.")

    def test_degrees_hyphen_next_line(self):
        # "12-\n28.85N" (466/25)
        self.assertEqual(rejoin_wrapped_coords("IN 12-\n28.85N 081-43.83W."), "IN 12-28.85N 081-43.83W.")

    def test_prose_wraps_untouched(self):
        self.assertEqual(rejoin_wrapped_coords("IN AREA BO\nUND BY"), "IN AREA BO\nUND BY")
        self.assertEqual(rejoin_wrapped_coords("C-CONFIDEN\nCE"), "C-CONFIDEN\nCE")

    def test_invalid_merge_rejected(self):
        # minutes >= 60 must not merge
        self.assertEqual(rejoin_wrapped_coords("57\n-99N 056-00W,"), "57\n-99N 056-00W,")

    def test_idempotent(self):
        once = rejoin_wrapped_coords("58-10.\n50N 068-19.17W.")
        self.assertEqual(rejoin_wrapped_coords(once), once)


class TestSegmentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.memo = _load("daily_memo_snapshot.txt")
        cls.blocks = split_into_warnings(cls.memo)
        cls.by_id = {b["warning_id"]: b for b in cls.blocks}

    def test_in_force_marker(self):
        self.assertEqual(get_in_force_dtg(self.memo), "051505Z MAR")

    def test_count_and_order(self):
        self.assertEqual(len(self.blocks), 108)
        self.assertEqual(self.blocks[0]["warning_id"], "NAVAREA IV 207/26")
        self.assertEqual(len(self.by_id), 108)  # all unique

    def test_unpadded_ids(self):
        self.assertIn("NAVAREA IV 7/26", self.by_id)
        self.assertIn("NAVAREA IV 12/25", self.by_id)
        self.assertIn("NAVAREA IV 1431/25", self.by_id)

    def test_lowercase_month_dtg(self):
        self.assertEqual(self.by_id["NAVAREA IV 158/26"]["dtg"], "200632Z Feb 26")
        self.assertEqual(self.by_id["NAVAREA IV 153/26"]["dtg"], "191839Z Feb 26")

    def test_msgid_legacy_blocks(self):
        self.assertIsNone(self.by_id["NAVAREA IV 367/22"]["dtg"])
        self.assertIn("MSGID/GENADMIN", self.by_id["NAVAREA IV 367/22"]["raw_text"])

    def test_header_parens_continuation_line(self):
        # "NAVAREA IV 113/26\n(26)."
        block = self.by_id["NAVAREA IV 113/26"]
        self.assertEqual(block["header_refs"], ["26"])
        self.assertEqual(block["dtg"], "061649Z FEB 26")

    def test_wrapped_coords_merged_in_blocks(self):
        # 466/25 raw block must contain the repaired coordinate
        self.assertIn("12-28.85N 081-43.83W", self.by_id["NAVAREA IV 466/25"]["raw_text"])
        # 1170/25 depths list
        self.assertIn("58-10.50N 068-19.17W", self.by_id["NAVAREA IV 1170/25"]["raw_text"])
        # 206/26 sea-ice limit
        self.assertIn("57-00N 056-00W", self.by_id["NAVAREA IV 206/26"]["raw_text"])


class TestCrossRefs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {b["warning_id"]: b for b in split_into_warnings(_load("daily_memo_snapshot.txt"))}

    def _cancels(self, wid):
        block = self.by_id[wid]
        return [(r["number"], r["year"]) for r in extract_cross_refs(block)
                if r["kind"] == "cancellation"]

    def test_multi_ref_cancel(self):
        # "2. CANCEL NAVAREA IV 964/25, 1110/25."
        self.assertEqual(self._cancels("NAVAREA IV 16/26"), [("964", "25"), ("1110", "25")])

    def test_cancel_with_header_paren_suffix(self):
        # "2. CANCEL NAVAREA IV 1008/25(24)."
        self.assertEqual(self._cancels("NAVAREA IV 161/26"), [("1008", "25")])

    def test_plain_cancels(self):
        self.assertEqual(self._cancels("NAVAREA IV 133/26"), [("91", "26")])
        self.assertEqual(self._cancels("NAVAREA IV 204/26"), [("149", "26")])
        self.assertEqual(self._cancels("NAVAREA IV 190/26"), [("159", "26")])

    def test_numbers_not_padded(self):
        self.assertEqual(self._cancels("NAVAREA IV 19/26"), [("57", "23")])
        # stored ids are unpadded ("NAVAREA IV 7/26"), so refs must be too
        self.assertEqual(self._cancels("NAVAREA IV 133/26"), [("91", "26")])

    def test_self_cancel_never_a_ref(self):
        # "2. CANCEL THIS MSG 160736Z MAR 26."
        self.assertEqual(self._cancels("NAVAREA IV 207/26"), [])

    def test_header_refs_numeric_only(self):
        block = self.by_id["NAVAREA IV 207/26"]
        refs = [(r["number"], r["year"], r["kind"]) for r in extract_cross_refs(block)]
        self.assertEqual(refs, [("11", "26", "header_ref"), ("26", "26", "header_ref")])

    def test_gen_ignored(self):
        block = self.by_id["NAVAREA IV 206/26"]
        self.assertEqual(extract_cross_refs(block), [])


class TestSubAreas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_id = {b["warning_id"]: b for b in split_into_warnings(_load("daily_memo_snapshot.txt"))}

    def test_modu_list_multi_letter_labels(self):
        subs = split_sub_areas(self.by_id["NAVAREA IV 204/26"]["raw_text"])
        labels = [s["label"] for s in subs]
        self.assertEqual(len(labels), 95)
        self.assertEqual(labels[0], "A")
        self.assertEqual(labels[-1], "AAAQ")
        self.assertIn("AA", labels)
        self.assertIn("AAZ", labels)

    def test_moorings_list(self):
        subs = split_sub_areas(self.by_id["NAVAREA IV 1292/25"]["raw_text"])
        self.assertEqual([s["label"] for s in subs], list("ABCDEFGHIJKLMNOPQRSTUV"))

    def test_column_zero_markers(self):
        subs = split_sub_areas(self.by_id["NAVAREA IV 180/26"]["raw_text"])
        self.assertEqual([s["label"] for s in subs], ["A", "B"])

    def test_title_line_false_positive_rejected(self):
        # "ST. KITTS AND NEVIS." must not become a sub-area (1524/24)
        subs = split_sub_areas(self.by_id["NAVAREA IV 1524/24"]["raw_text"])
        self.assertEqual(subs, [{"label": None, "text": self.by_id["NAVAREA IV 1524/24"]["raw_text"]}])

    def test_marker_with_wrapped_coords_kept(self):
        # "R. (NEW POSITION) DEEPWATER PONTUS\n 27-35.9N ..." — coords on next line
        subs = split_sub_areas(self.by_id["NAVAREA IV 204/26"]["raw_text"])
        seg_r = [s for s in subs if s["label"] == "R"][0]
        self.assertIn("27-35.9N 092-18.0W", seg_r["text"])

    def test_unmarked_warning_single_area(self):
        subs = split_sub_areas(self.by_id["NAVAREA IV 53/26"]["raw_text"])
        self.assertEqual(len(subs), 1)
        self.assertIsNone(subs[0]["label"])

    def test_item_line_terminates_subarea(self):
        # 204/26: sub-area segments must not bleed into "2. TO REPORT..."
        subs = split_sub_areas(self.by_id["NAVAREA IV 204/26"]["raw_text"])
        for s in subs:
            self.assertNotIn("TO REPORT A MOBILE OFFSHORE", s["text"])


class TestGeometryClauses(unittest.TestCase):
    """Clause-level geometry segmentation (extract_geometry_clauses).

    Unlike split_sub_areas(), clauses cover UNMARKED numbered items too, so
    NAVAREA IV 206/26's iceberg limits (items 2-4) become their own geometry
    records instead of being silently dropped, and clauses matching
    "TRACKLINE(S) JOINING" are flagged so the parser renders open lines.
    """

    @classmethod
    def setUpClass(cls):
        cls.by_id = {b["warning_id"]: b for b in split_into_warnings(_load("daily_memo_snapshot.txt"))}

    def test_206_items_and_marks_are_clauses(self):
        # 9 numbered items; item 5 carries marks A/B/C -> 11 clauses total.
        # Trackline clauses: items 2-4 (iceberg limits) + A/B/C (sea ice
        # limit, via the item preamble "SEA ICE LIMIT ALONG TRACKLINES
        # JOINING:").
        clauses = extract_geometry_clauses(self.by_id["NAVAREA IV 206/26"]["raw_text"])
        self.assertEqual(len(clauses), 11)
        self.assertEqual([c["label"] for c in clauses],
                         ["Item 1", "Item 2", "Item 3", "Item 4",
                          "A", "B", "C", "Item 6", "Item 7", "Item 8", "Item 9"])
        trackline = [c["label"] for c in clauses if c["is_trackline"]]
        self.assertEqual(trackline, ["Item 2", "Item 3", "Item 4", "A", "B", "C"])

    def test_158_markers_before_items_use_implicit_item(self):
        # "LIGHTS UNLIT:\nA. ..." — markers before any numbered item get an
        # implicit item context and keep their plain letter labels.
        clauses = extract_geometry_clauses(self.by_id["NAVAREA IV 158/26"]["raw_text"])
        self.assertEqual([c["label"] for c in clauses], ["A", "B", "C"])
        for c in clauses:
            self.assertFalse(c["is_trackline"])

    def test_1524_items_only_no_st_clause(self):
        # "ST. KITTS AND NEVIS." is a title line: it forms a marker event,
        # but the coordinate-less segment is rejected and the implicit item
        # falls back to a whole-block clause labeled None. The numbered items
        # 1-4 follow; no clause is ever labeled "ST".
        clauses = extract_geometry_clauses(self.by_id["NAVAREA IV 1524/24"]["raw_text"])
        self.assertEqual([c["label"] for c in clauses],
                         [None, "Item 1", "Item 2", "Item 3", "Item 4"])
        self.assertIn("ST. KITTS AND NEVIS.", clauses[0]["text"])

    def test_204_marks_plus_prose_items(self):
        clauses = extract_geometry_clauses(self.by_id["NAVAREA IV 204/26"]["raw_text"])
        # Item 1 holds the 95 MODU marks (so no "Item 1" clause); items 2
        # ("TO REPORT...") and 3 ("CANCEL...") are prose items.
        self.assertEqual(len(clauses), 97)  # 95 MODU marks + Item 2 + Item 3
        labels = [c["label"] for c in clauses]
        self.assertEqual([l for l in labels if str(l).startswith("Item ")],
                         ["Item 2", "Item 3"])
        marks = [l for l in labels if not str(l).startswith("Item ")]
        self.assertEqual(len(marks), 95)
        self.assertEqual(marks[0], "A")
        self.assertEqual(marks[-1], "AAAQ")

    def test_markerless_itemless_warning_single_clause(self):
        raw = self.by_id["NAVAREA IV 53/26"]["raw_text"]
        clauses = extract_geometry_clauses(raw)
        self.assertEqual(clauses, [{"label": None, "text": raw, "context": raw,
                                    "is_trackline": False}])

    def test_empty_text_returns_no_clauses(self):
        self.assertEqual(extract_geometry_clauses(""), [])


class TestRingToTrackline(unittest.TestCase):
    def test_closed_ring_opened_to_linestring(self):
        spatial = {"type": "Polygon",
                   "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        self.assertEqual(
            ring_to_trackline(spatial),
            {"type": "LineString", "coordinates": [[0, 0], [1, 0], [1, 1]]},
        )

    def test_open_polygon_becomes_linestring(self):
        # Non-closed rings are already open lines: same coordinates, but the
        # type always flips Polygon -> LineString for trackline clauses.
        spatial = {"type": "Polygon",
                   "coordinates": [[[0, 0], [1, 0], [1, 1]]]}
        self.assertEqual(
            ring_to_trackline(spatial),
            {"type": "LineString", "coordinates": [[0, 0], [1, 0], [1, 1]]},
        )

    def test_point_none_and_non_dict_passthrough(self):
        pt = {"type": "Point", "coordinates": [1, 2]}
        self.assertEqual(ring_to_trackline(pt), pt)
        self.assertIsNone(ring_to_trackline(None))
        self.assertEqual(ring_to_trackline("not-a-dict"), "not-a-dict")

    def test_empty_ring_becomes_empty_linestring(self):
        spatial = {"type": "Polygon", "coordinates": [[]]}
        self.assertEqual(ring_to_trackline(spatial),
                         {"type": "LineString", "coordinates": []})

    def test_no_rings_passthrough(self):
        spatial = {"type": "Polygon", "coordinates": []}
        self.assertEqual(ring_to_trackline(spatial), spatial)


if __name__ == "__main__":
    unittest.main()
