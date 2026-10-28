#!/usr/bin/env python3
"""test_navarea_xii.py — NAVAREA XII preprocessing, segmentation, and H05 regression tests.

Fixtures are verbatim captures of the NGA NAVAREA XII daily memo
(msi.nga.mil/apology_objects/DailyMemXII.txt):
  - 148/26: coordinate token wrapped across lines ("34-27.\n00N")
  - 151/26: A./B./C. sub-areas
  - 150/26: header paren refs (21,22)
  - daily_memo_snapshot.txt: full memo (segmentation + cross-ref corpus)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.navarea_xii_text import (
    rejoin_wrapped_coords,
    split_into_warnings,
    extract_cross_refs,
    split_sub_areas,
    get_in_force_dtg,
)
from shared.utils import parse_coordinates, convert_to_decimal

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "navarea_xii")


def _load(name):
    with open(os.path.join(FIXTURE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


class TestRejoinWrappedCoords(unittest.TestCase):
    def setUp(self):
        self.raw_148 = _load("148_26.txt")
        self.raw_150 = _load("150_26.txt")

    def test_148_wrapped_minutes_rejoined(self):
        fixed = rejoin_wrapped_coords(self.raw_148)
        self.assertIn("34-27.\n00N", self.raw_148)          # wrap present in fixture
        self.assertIn("34-27.00N 120-26.00W", fixed)        # token repaired
        self.assertNotIn("34-27.\n00N", fixed)

    def test_idempotent(self):
        fixed = rejoin_wrapped_coords(self.raw_148)
        self.assertEqual(fixed, rejoin_wrapped_coords(fixed))

    def test_clean_text_unchanged(self):
        self.assertEqual(rejoin_wrapped_coords(self.raw_150), self.raw_150)

    def test_prose_word_wraps_untouched(self):
        text = "1. CABLE OPERATIONS IN AREA BO\nUND BY\n02-10.90S 081-12.90W."
        self.assertEqual(rejoin_wrapped_coords(text), text)


class TestMemoSegmentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.memo = _load("daily_memo_snapshot.txt")
        cls.blocks = split_into_warnings(cls.memo)
        cls.ids = [b["warning_id"] for b in cls.blocks]

    def test_block_count(self):
        self.assertEqual(len(self.blocks), 32)

    def test_expected_ids_present(self):
        for wid in ("NAVAREA XII 151/26", "NAVAREA XII 150/26", "NAVAREA XII 148/26",
                    "NAVAREA XII 142/26", "NAVAREA XII 133/26", "NAVAREA XII 718/25",
                    "NAVAREA XII 93/23", "NAVAREA XII 244/22", "NAVAREA XII 243/22"):
            self.assertIn(wid, self.ids)

    def test_first_block_is_newest_warning(self):
        self.assertEqual(self.blocks[0]["warning_id"], "NAVAREA XII 151/26")

    def test_dtg_attached(self):
        by_id = {b["warning_id"]: b for b in self.blocks}
        self.assertEqual(by_id["NAVAREA XII 151/26"]["dtg"], "040124Z MAR 26")
        self.assertEqual(by_id["NAVAREA XII 148/26"]["dtg"], "251304Z FEB 26")

    def test_legacy_msgid_blocks_have_no_dtg(self):
        by_id = {b["warning_id"]: b for b in self.blocks}
        for wid in ("NAVAREA XII 244/22", "NAVAREA XII 243/22"):
            self.assertIn(wid, by_id)
            self.assertIsNone(by_id[wid]["dtg"])
            self.assertTrue(by_id[wid]["raw_text"].startswith("MSGID/"))

    def test_in_force_dtg(self):
        self.assertEqual(get_in_force_dtg(self.memo), "051505Z MAR")

    def test_body_cancel_lines_do_not_split_blocks(self):
        # "2. CANCEL NAVAREA XII 127/26." lives inside 142/26's body
        self.assertNotIn("NAVAREA XII 127/26", self.ids)
        self.assertNotIn("NAVAREA XII 116/26", self.ids)


class TestCrossRefs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blocks = {b["warning_id"]: b for b in split_into_warnings(_load("daily_memo_snapshot.txt"))}

    def test_150_header_paren_refs(self):
        block = self.blocks["NAVAREA XII 150/26"]
        self.assertEqual(block["header_refs"], ["21", "22"])
        refs = extract_cross_refs(block)
        header_refs = [r for r in refs if r["kind"] == "header_ref"]
        self.assertEqual([r["number"] for r in header_refs], ["021", "022"])
        self.assertTrue(all(r["year"] == "26" for r in header_refs))

    def test_142_body_cancellation(self):
        refs = extract_cross_refs(self.blocks["NAVAREA XII 142/26"])
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual(len(cancels), 1)
        self.assertEqual(cancels[0]["number"], "127")
        self.assertEqual(cancels[0]["year"], "26")

    def test_133_cancellation(self):
        refs = extract_cross_refs(self.blocks["NAVAREA XII 133/26"])
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual([r["number"] for r in cancels], ["116"])

    def test_126_cancellation(self):
        refs = extract_cross_refs(self.blocks["NAVAREA XII 126/26"])
        cancels = [r for r in refs if r["kind"] == "cancellation"]
        self.assertEqual([r["number"] for r in cancels], ["118"])

    def test_self_cancel_msg_is_not_a_ref(self):
        refs = extract_cross_refs(self.blocks["NAVAREA XII 151/26"])
        self.assertFalse([r for r in refs if r["kind"] == "cancellation"])

    def test_non_numeric_header_tokens_ignored(self):
        refs = extract_cross_refs(self.blocks["NAVAREA XII 88/26"])
        self.assertEqual(refs, [])  # "(GEN)" is a category code, not a warning ref


class TestSubAreas(unittest.TestCase):
    def setUp(self):
        self.raw_148 = _load("148_26.txt")
        self.raw_150 = _load("150_26.txt")
        self.raw_151 = _load("151_26.txt")

    def test_151_three_sub_areas_with_geometry(self):
        fixed = rejoin_wrapped_coords(self.raw_151)
        subs = split_sub_areas(fixed)
        self.assertEqual([s["label"] for s in subs], ["A", "B", "C"])
        for sub, expected_points in zip(subs, (9, 5, 4)):
            # The 'IN AREAS BOUND BY' keyword lives in the item preamble,
            # outside the sub-area segment: pass the block as classification
            # context, exactly as the parser does via clause "context".
            coords, lat, lon, spatial = parse_coordinates(sub["text"], fixed)
            self.assertEqual(len(coords), expected_points)
            self.assertEqual(spatial["type"], "Polygon")
            self.assertEqual(len(spatial["coordinates"][0]), expected_points + 1)

    def test_148_rejoin_required_for_full_geometry(self):
        # The shared parser rejoins wrapped tokens internally (A1), so even
        # the raw, un-rejoined sub-area text recovers all 6 vertices; the
        # preprocessing rejoin stays for segmentation and grounding.
        subs_raw = split_sub_areas(self.raw_148)
        coords_raw, _, _, _ = parse_coordinates(subs_raw[0]["text"])
        self.assertEqual(len(coords_raw), 6)
        # With rejoin all 6 vertices of sub-area A are recovered
        subs = split_sub_areas(rejoin_wrapped_coords(self.raw_148))
        self.assertEqual([s["label"] for s in subs], ["A", "B"])
        coords_a, lat_a, lon_a, spatial_a = parse_coordinates(subs[0]["text"])
        self.assertEqual(len(coords_a), 6)
        self.assertEqual(spatial_a["type"], "Polygon")
        coords_b, _, _, _ = parse_coordinates(subs[1]["text"])
        self.assertEqual(len(coords_b), 7)

    def test_142_cancel_item_excluded_from_sub_areas(self):
        blocks = {b["warning_id"]: b for b in split_into_warnings(_load("daily_memo_snapshot.txt"))}
        subs = split_sub_areas(rejoin_wrapped_coords(blocks["NAVAREA XII 142/26"]["raw_text"]))
        self.assertEqual([s["label"] for s in subs], ["A", "B"])
        for sub in subs:
            self.assertNotIn("CANCEL NAVAREA XII 127/26", sub["text"])

    def test_no_markers_single_area(self):
        subs = split_sub_areas(self.raw_150)
        self.assertEqual(len(subs), 1)
        self.assertIsNone(subs[0]["label"])


class TestGroundingH05Regression(unittest.TestCase):
    """H05 grounding contract: every coordinate token used for geometry must be
    an exact substring of the normalized source text, and the deterministic
    shared parser must independently reproduce the decimal values."""

    def test_tokens_are_exact_substrings_of_normalized_text(self):
        blocks = split_into_warnings(_load("daily_memo_snapshot.txt"))
        block = blocks[2]  # 148/26
        self.assertEqual(block["warning_id"], "NAVAREA XII 148/26")
        normalized = block["raw_text"]
        for sub in split_sub_areas(normalized):
            coords, _, _, _ = parse_coordinates(sub["text"])
            for token in coords:
                self.assertIn(token, normalized)

    def test_deterministic_parser_reproduces_decimal(self):
        coords, lat, lon, spatial = parse_coordinates("34-27.00N 120-26.00W")
        self.assertEqual(len(coords), 1)
        self.assertAlmostEqual(lat, convert_to_decimal(34, 27, "N"), places=6)
        self.assertAlmostEqual(lon, convert_to_decimal(120, 26, "W"), places=6)
        self.assertAlmostEqual(lat, 34.45, places=5)
        self.assertAlmostEqual(lon, -(120 + 26 / 60), places=5)


if __name__ == "__main__":
    unittest.main()
