#!/usr/bin/env python3
"""
tests/test_universal_formats.py — Regression tests against the live
coordinator bulletin corpus (uploaded Oct 2026, stored as trimmed
fixtures under tests/fixtures/).

Covers the format quirks the universal parser + shared coordinate
extractor were extended for:
  * 4-digit header years (II '355/2026', XVII/XVIII '90/2026')
  * XIV 'NAVAREA XIV WARNING 287/26' word
  * V bare '0648/26' headers (no NAVAREA numeral)
  * VI 'NAVAREA - 0355-2026' (numeral omitted)
  * VII 'NAVAREA VII 014 OF 2026' (OF form, year behind tabs/newline)
  * XV 'NAVAREA XV 0142' (no year -> bulletin 'YEAR 2026' hint)
  * XIX 'Number:125/26' anchors + glued 'NN-NN.NNE:' coordinate tails
  * coordinate syntaxes: standard DMM, DMS with (decimal) seconds,
    Peru fractional-hyphen (rule-18 pair form), spaced-hyphen with
    separated hemispheres (VII), space/tab-separated DMM (XVIII, IX)
  * CANCEL-prefixed cross-references never split a warning block
  * broadcast tails ('NNNN', '.=') stripped from the last block
  * fail-closed Spanish title translation (XV/XVI)
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.navarea_universal_parser import (
    parse_bulletin_text, resolve_region, split_into_warnings, _region_config,
)
from shared.utils import parse_coordinates, _extract_coord_pairs
from shared.navarea_universal_text import normalize_year, warning_header_re
from shared.translation import looks_spanish, translate_title
from shared.feed_registry import get_text_feed

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


def by_id(parsed: dict, warning_id: str) -> dict:
    for w in parsed["nav_warnings"]:
        if w["warning_id"] == warning_id:
            return w
    raise AssertionError(f"warning {warning_id!r} not parsed; got "
                         f"{[w['warning_id'] for w in parsed['nav_warnings']]}")


class TestHeaderYearNormalization(unittest.TestCase):
    def test_normalize_year(self):
        self.assertEqual(normalize_year("2026"), "26")
        self.assertEqual(normalize_year("26"), "26")
        self.assertIsNone(normalize_year(None))

    def test_default_header_4_digit_year(self):
        self.assertRegex("NAVAREA II 355/2026", warning_header_re("II"))
        self.assertRegex("NAVAREA XVIII 137/2026", warning_header_re("XVIII"))

    def test_default_header_warning_word(self):
        self.assertRegex("NAVAREA XIV WARNING 287/26", warning_header_re("XIV"))


class TestCancelRefNeverSplitsBlock(unittest.TestCase):
    def test_cancel_prefixed_header_is_not_block_start(self):
        cfg = _region_config("ii")
        text = ("NAVAREA II 123/26\n SURVEY IN 48-00.0N 006-00.0W\n"
                " 2. CANCEL NAVAREA II 100/26\n\n"
                "NAVAREA II 124/26\n BISCAY FIRING\n")
        blocks = split_into_warnings(text, cfg)
        self.assertEqual([b["number"] for b in blocks], ["123", "124"])
        # the cancel ref stays inside warning 123 as a cross-reference
        parsed = parse_bulletin_text(text, "ii")
        self.assertEqual(by_id(parsed, "NAVAREA II 123/26")["cross_refs"],
                         [{"number": "100", "year": "26"}])


class TestRegionIIFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_ii_sample.txt"), "ii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA II 355/26", ids)
        self.assertIn("NAVAREA II 349/26", ids)
        # rig list: coordinates resolve, scattered rigs stay markers
        riglist = by_id(parsed, "NAVAREA II 349/26")
        self.assertIsNotNone(riglist["latitude"])
        geom = riglist["spatial"]["features"][0]["geometry"]
        self.assertEqual(geom["type"], "MultiPoint")
        self.assertIn([-2.330167, 4.528167], geom["coordinates"])


class TestRegionIIIFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_iii_sample.txt"), "iii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA III 0157/26", ids)
        self.assertIn("NAVAREA III 0155/26", ids)
        self.assertTrue(any(w["spatial"] for w in parsed["nav_warnings"]))


class TestRegionVFixture(unittest.TestCase):
    """Brazil: bare '0648/26' lines, no NAVAREA numeral anywhere."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_v_sample.txt"), "v")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA V 0648/26", ids)
        self.assertIn("NAVAREA V 0647/26", ids)
        self.assertIn("NAVAREA V 0646/26", ids)
        # in-force index line ('0646/26; 0645/26; ...') must NOT split blocks
        self.assertEqual(len(ids), len(set(ids)))
        adrift = by_id(parsed, "NAVAREA V 0648/26")
        self.assertEqual(adrift["latitude"], -28.131167)
        self.assertEqual(adrift["longitude"], -26.948333)
        self.assertEqual(adrift["spatial"]["features"][0]["geometry"]["type"],
                         "Point")

    def test_cancel_ref_without_numeral(self):
        cfg = _region_config("v")
        refs_text = "CANCEL NAVAREA 0622/26"
        from scripts.navarea_universal_parser import _extract_cross_refs
        self.assertEqual(_extract_cross_refs(refs_text, cfg),
                         [{"number": "0622", "year": "26"}])


class TestRegionVIFixture(unittest.TestCase):
    """Argentina: 'NAVAREA - 0355-2026' header (numeral omitted)."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_vi_sample.txt"), "vi")
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA VI 0355/26")
        self.assertEqual(w["navarea"], "VI")
        self.assertIsNotNone(w["latitude"])
        self.assertIsNotNone(w["spatial"])


class TestRegionVIIFixture(unittest.TestCase):
    """South Africa: 'n OF yyyy' headers, spaced-hyphen coordinates."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_vii_sample.txt"), "vii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA VII 014/26", ids)
        self.assertIn("NAVAREA VII 221/26", ids)
        self.assertIn("NAVAREA VII 258/26", ids)
        # '28 - 35.8 S 013 - 54.7 E' spaced-hyphen pair resolves
        buoy = by_id(parsed, "NAVAREA VII 221/26")
        self.assertEqual(buoy["latitude"], -28.596667)
        self.assertEqual(buoy["longitude"], 13.911667)
        # rig list: spaced-hyphen pairs, markers not a connected shape
        rigs = by_id(parsed, "NAVAREA VII 258/26")
        geom = rigs["spatial"]["features"][0]["geometry"]
        self.assertEqual(geom["type"], "MultiPoint")
        self.assertIn([14.009167, -22.013333], geom["coordinates"])
        # 'CANCEL NAVAREA VII 374 OF 2025' is a cross-ref, not a block
        self.assertEqual(len(ids), len(set(ids)))


class TestRegionIXFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_ix_sample.txt"), "ix")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA IX 268/26", ids)
        self.assertIn("NAVAREA IX 255/26", ids)
        self.assertIn("NAVAREA IX 254/26", ids)
        dredged = by_id(parsed, "NAVAREA IX 254/26")
        self.assertIsNotNone(dredged["spatial"])
        # tab-separated pairs resolve (P1 24-03.945N / 038-02.827E)
        found = False
        for _kind, lat, lon, _canon in _extract_coord_pairs(
                dredged["raw_text"]):
            if abs(lat - 24.06575) < 1e-6 and abs(lon - 38.047117) < 1e-6:
                found = True
        self.assertTrue(found, "tab-separated P1 pair not extracted")


class TestRegionXFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_x_sample.txt"), "x")
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        w = parsed["nav_warnings"][0]
        self.assertEqual(w["warning_id"], "NAVAREA X 106/26")
        self.assertIsNotNone(w["spatial"])
        # 'A 14-45.98S /159-08.93E' slash-separated pair resolves
        found = False
        for _kind, lat, lon, _canon in _extract_coord_pairs(w["raw_text"]):
            if abs(lat - (-14.766333)) < 1e-6 and abs(lon - 159.148833) < 1e-6:
                found = True
        self.assertTrue(found, "'S /159-08.93E' slash pair not extracted")
        # trailing 'NNNN' broadcast tail must not leak into the raw text
        self.assertNotIn("NNNN", w["raw_text"])


class TestRegionXIIIFixture(unittest.TestCase):
    """Russia NW Pacific: DMS-with-seconds coordinate pairs."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xiii_sample.txt"), "xiii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XIII 22/26", ids)
        self.assertIn("NAVAREA XIII 48/26", ids)
        buoy = by_id(parsed, "NAVAREA XIII 48/26")
        self.assertEqual(buoy["latitude"], 51.375556)
        self.assertEqual(buoy["longitude"], 144.236111)
        self.assertEqual(buoy["spatial"]["features"][0]["geometry"]["type"],
                         "Point")
        works = by_id(parsed, "NAVAREA XIII 22/26")
        self.assertIsNotNone(works["spatial"])


class TestRegionXIVFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xiv_sample.txt"), "xiv")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XIV 287/26", ids)
        self.assertIn("NAVAREA XIV 286/26", ids)


class TestRegionXVFixture(unittest.TestCase):
    """Chile: 'NAVAREA XV 0142' (no year), LAT./LONG. wording, Spanish."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xv_sample.txt"), "xv")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        # year resolved from the bulletin 'YEAR 2026' hint
        self.assertIn("NAVAREA XV 0142/26", ids)
        self.assertIn("NAVAREA XV 0140/26", ids)
        platforms = by_id(parsed, "NAVAREA XV 0140/26")
        self.assertIsNotNone(platforms["latitude"])
        # 'LAT. 52-20.10S. LONG. 069-04.60W.' pair resolves
        found = False
        for _kind, lat, lon, _canon in _extract_coord_pairs(
                platforms["raw_text"]):
            if abs(lat - (-52.335)) < 1e-6 and abs(lon - (-69.076667)) < 1e-6:
                found = True
        self.assertTrue(found, "'LAT./LONG.' separated pair not extracted")

    def test_spanish_title_translated_with_mock(self):
        text = ("NAVAREA XV 0142 \n"
                "PACÍFICO SUR. \n"
                "ZONA TEMPORALMENTE PROHIBIDA A LA NAVEGACIÓN. \n"
                "CANCEL THIS MESSAGE 270539 UTC OCT/26.\n")
        with mock.patch("shared.translation.translate_title",
                        return_value="SOUTH PACIFIC. AREA TEMPORARILY "
                                    "PROHIBITED TO NAVIGATION."):
            parsed = parse_bulletin_text(text, "xv")
        w = parsed["nav_warnings"][0]
        self.assertIn("PROHIBITED", w["title"])
        self.assertNotIn("PROHIBIDA", w["title"])
        # raw text keeps the original Spanish
        self.assertIn("PROHIBIDA", w["raw_text"])

    def test_spanish_title_kept_when_translation_fails(self):
        text = ("NAVAREA XV 0142 \n"
                "PACÍFICO SUR. ZONA TEMPORALMENTE PROHIBIDA. \n")
        with mock.patch("shared.translation.translate_title", return_value=None):
            parsed = parse_bulletin_text(text, "xv")
        w = parsed["nav_warnings"][0]
        self.assertIn("PROHIBIDA", w["title"])


class TestRegionXVIFixture(unittest.TestCase):
    """Peru: DMS with decimal seconds + fractional-hyphen (rule 18) pairs."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xvi_sample.txt"), "xvi")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XVI 083/26", ids)
        self.assertIn("NAVAREA XVI 084/26", ids)
        self.assertIn("NAVAREA XVI 090/26", ids)
        self.assertIn("NAVAREA XVI 092/26", ids)
        # DMS with decimal seconds: 12-01-53.4S 077-10-29.1W
        buoy = by_id(parsed, "NAVAREA XVI 083/26")
        self.assertEqual(buoy["latitude"], -12.0315)
        self.assertEqual(buoy["longitude"], -77.17475)
        # rule-18 pair form: A.11-49-992S 077-28-025W -> 11-49.992S
        gunnery = by_id(parsed, "NAVAREA XVI 092/26")
        found = False
        for _kind, lat, lon, _canon in _extract_coord_pairs(gunnery["raw_text"]):
            if abs(lat - (-11.8332)) < 1e-6 and abs(lon - (-77.467083)) < 1e-6:
                found = True
        self.assertTrue(found, "Peru fractional-hyphen pair not extracted")


class TestRegionXVIIFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xvii_sample.txt"), "xvii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XVII 90/26", ids)
        self.assertIn("NAVAREA XVII 7/25", ids)


class TestRegionXVIIIFixture(unittest.TestCase):
    """Canada Arctic East: 4-digit years, space-separated DMM pairs."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xviii_sample.txt"), "xviii")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XVIII 137/26", ids)
        self.assertIn("NAVAREA XVIII 121/26", ids)
        moorings = by_id(parsed, "NAVAREA XVIII 121/26")
        # '68 27.660N 113 23.366W' space-separated pair resolves
        found = False
        for _kind, lat, lon, _canon in _extract_coord_pairs(moorings["raw_text"]):
            if abs(lat - 68.461) < 1e-6 and abs(lon - (-113.389433)) < 1e-6:
                found = True
        self.assertTrue(found, "space-separated pair not extracted")
        self.assertIsNotNone(moorings["spatial"])


class TestRegionXIXFixture(unittest.TestCase):
    """Norway: 'Number:n/yy' anchors, glued 'NN-NN.NNE:' coordinate tails."""

    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xix_sample.txt"), "xix")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XIX 123/26", ids)
        self.assertIn("NAVAREA XIX 122/26", ids)
        survey = by_id(parsed, "NAVAREA XIX 123/26")
        # glued '64-33.50N 006-04.80EB:' tail must still extract the pair
        found = False
        for _kind, lat, lon, _canon in _extract_coord_pairs(survey["raw_text"]):
            if abs(lat - 64.558333) < 1e-6 and abs(lon - 6.08) < 1e-6:
                found = True
        self.assertTrue(found, "glued coordinate tail not extracted")
        self.assertIsNotNone(survey["spatial"])


class TestRegionXXFixture(unittest.TestCase):
    def test_parse(self):
        parsed = parse_bulletin_text(fixture("navarea_xx_sample.txt"), "xx")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertIn("NAVAREA XX 160/26", ids)
        self.assertIn("NAVAREA XX 102/26", ids)
        missile = by_id(parsed, "NAVAREA XX 160/26")
        self.assertIsNotNone(missile["spatial"])
        self.assertNotIn("NNNN", missile["raw_text"])


class TestCoordinateExtractorUnits(unittest.TestCase):
    def test_dms_pair(self):
        pairs = _extract_coord_pairs("51-27-57N 143-26-43E")
        self.assertEqual(len(pairs), 1)
        _kind, lat, lon, _canon = pairs[0]
        self.assertEqual(lat, 51.465833)
        self.assertEqual(lon, 143.445278)

    def test_spaced_hyphen_pair(self):
        pairs = _extract_coord_pairs("06 - 07.3 S 011 - 14.0 E")
        self.assertEqual(len(pairs), 1)
        _kind, lat, lon, _canon = pairs[0]
        self.assertEqual(lat, -6.121667)
        self.assertEqual(lon, 11.233333)

    def test_out_of_range_pair_skipped(self):
        # 99 degrees of latitude is invalid: skipped, never clamped
        pairs = _extract_coord_pairs("99-45.98S 159-08.93E")
        self.assertEqual(pairs, [])

    def test_date_text_not_matched(self):
        pairs = _extract_coord_pairs(
            "13 OCT 26 TO 24 OCT 26 BY TOWING 12 CABLES WITH 1500 METERS")
        self.assertEqual(pairs, [])

    def test_parse_coordinates_point(self):
        _coords, lat, lon, spatial = parse_coordinates("IN 28-07.87S 026-56.90W")
        self.assertEqual(spatial["type"], "Point")
        self.assertEqual(lat, -28.131167)


class TestTranslationModule(unittest.TestCase):
    def test_looks_spanish(self):
        self.assertTrue(looks_spanish("ZONA PROHIBIDA A LA NAVEGACIÓN"))
        self.assertFalse(looks_spanish("SEISMIC SURVEY IN PROGRESS"))

    def test_translate_title_fails_closed_without_key(self):
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(translate_title("ZONA PROHIBIDA"))


class TestFeedRegistry(unittest.TestCase):
    def test_no_verified_text_feed_fails_closed(self):
        # reference_only / html entries must never be scrapable
        for key in ("iii", "x", "xix"):
            self.assertIsNone(get_text_feed(key))
        self.assertIsNone(get_text_feed("ii"))


if __name__ == "__main__":
    unittest.main()
