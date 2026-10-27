#!/usr/bin/env python3
"""tests/test_navarea_v_scraper.py — NAVAREA V (Brazil CHM) JSON scraper
tests.

Verifies the discover-link -> records -> synthesize -> universal-parser
chain end to end, offline, against a miniature clone of the live CHM
JSON snapshot (schema verified 2026-10-27: 'atualizado' + 'avisos[]'
with numero / costa / tipo / textoPT / textoEN / geometry).
"""
import json
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_v_scraper import (
    find_latest_avradio_url,
    parse_aviso_records,
    synthesize_bulletin,
)
from scripts.navarea_universal_parser import parse_bulletin_text, resolve_region
from shared.feed_registry import get_text_feed

# Miniature clone of the live CHM JSON: one bare-numbered NAVAREA V
# warning with a live-format coordinate pair and a 'CANCEL NAVAREA
# 0622/26' cross-ref, the weekly in-force index warning (its
# ';'-terminated lists must never split blocks), one SAR and one
# costeiro record (national series -> skipped loudly), and one bare
# record without English text (skipped loudly).
_MINI_AVISOS = [
    {
        "numero": "0648/26",
        "costa": "",
        "tipo": "L",
        "textoPT": "A LESTE DE SANTA CATARINA ...",
        "textoEN": ("EAST OF SANTA CATARINA\nCHART 30 (INT 201)\n"
                    "MV ESPIRITO SANTO EXPRESS, SET ON FIRE, ABANDONED AND "
                    "ADRIFT. LAST POSITION IN 28-07.87S 026-56.90W\n"
                    "AT 151906 UTC OCT 26\n"
                    "CANCEL NAVAREA 0622/26.\n"
                    "CANCEL THIS WARNING 182025 UTC OCT 26."),
        "geometry": "new google.maps.Marker({position: new google.maps.LatLng(-28.131167, -26.948333)})",
    },
    {
        "numero": "0647/26",
        "costa": "",
        "tipo": "Z",
        "textoPT": "NAVAREA V ...",
        "textoEN": ("NAVAREA V\nRADIO NAVIGATIONAL WARNINGS AND SAR IN FORCE\n"
                    "SAR:\nSAR 0155/26; SAR 0150/26\n"
                    "NAVAREAS:\n0646/26; 0645/26; 0644/26\n"
                    "COSTEIROS:\nE 0606/26; N 0599/26\n"
                    "CANCEL THIS WARNING 160300 UTC OCT 26."),
        "geometry": "",
    },
    {
        "numero": "SAR 0105/26",
        "costa": "SAR",
        "tipo": "Z",
        "textoPT": "HOMEM AO MAR ...",
        "textoEN": ("MAN OVERBOARD, LAST POSITION IN 19-24.32S 039-39.48W "
                    "AT 12 JUN 26"),
        "geometry": "new google.maps.Marker({position: new google.maps.LatLng(-19.405333, -39.658)})",
    },
    {
        "numero": "E 0606/26",
        "costa": "E",
        "tipo": "Z",
        "textoPT": "BÓIA FORA DE POSIÇÃO ...",
        "textoEN": "RIO DE JANEIRO APPROACHES. BUOY OFF STATION.",
        "geometry": "",
    },
    {
        "numero": "0645/26",
        "costa": "",
        "tipo": "C",
        "textoPT": "SOMENTE PORTUGUES",
        "textoEN": "",
        "geometry": "",
    },
]

_MINI_JSON = json.dumps(
    {"atualizado": "27/10/2026 04:00", "avisos": _MINI_AVISOS},
    ensure_ascii=False)

# Miniature clone of the listing page: two Drupal file attachments; the
# publish number increments, so avradio_79.json (541.53 KB) must win over
# the older snapshot (relative and absolute href forms both occur).
_MINI_LISTING_HTML = (
    '<a href="/chm/sites/www.marinha.mil.br.chm/files/avradio_78.json">'
    "avradio_78.json (538.11 KB)</a>"
    '<a href="https://assets.marinha.mil.br/chm/sites/www.marinha.mil.br.chm'
    '/files/2026-10/avradio_79.json">avradio_79.json (541.53 KB)</a>'
)


class TestLinkDiscovery(unittest.TestCase):
    def test_highest_publish_number_wins(self):
        url = find_latest_avradio_url(_MINI_LISTING_HTML)
        self.assertIsNotNone(url)
        self.assertIn("avradio_79.json", url)
        self.assertTrue(url.startswith("https://"),
                        "relative hrefs must resolve against the listing page")

    def test_no_link_fails_closed(self):
        self.assertIsNone(
            find_latest_avradio_url("<html>no file links here</html>"))


class TestParseRecords(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_aviso_records(_MINI_JSON)

    def test_keeps_only_bare_navarea_numbers(self):
        numbers = [r["number"] + "/" + r["year"]
                   for r in self.parsed["records"]]
        self.assertEqual(numbers, ["0648/26", "0647/26"])

    def test_skips_sar_costeiros_and_textless_loudly(self):
        skipped = self.parsed["skipped"]
        self.assertEqual(skipped.get("SAR"), 1)
        self.assertEqual(skipped.get("E"), 1)
        self.assertEqual(skipped.get("without_english_text"), 1)

    def test_snapshot_timestamp_carried(self):
        self.assertEqual(self.parsed["atualizado"], "27/10/2026 04:00")

    def test_non_json_raises(self):
        with self.assertRaises(ValueError):
            parse_aviso_records("<html>not json</html>")

    def test_missing_avisos_array_raises(self):
        with self.assertRaises(ValueError):
            parse_aviso_records(json.dumps({"atualizado": "27/10/2026 04:00"}))


class TestSynthesizedBulletin(unittest.TestCase):
    def setUp(self):
        self.records = parse_aviso_records(_MINI_JSON)["records"]
        self.bulletin = synthesize_bulletin(self.records)

    def test_block_layout_matches_fixture_format(self):
        first = self.bulletin.split("\n\n\n")[0]
        lines = first.split("\n")
        # bare header line — no NAVAREA numeral (the Brazil quirk)
        self.assertEqual(lines[0], "0648/26")
        self.assertIn("28-07.87S 026-56.90W", first)

    def test_non_navarea_text_never_leaks(self):
        self.assertNotIn("MAN OVERBOARD", self.bulletin)
        self.assertNotIn("BUOY OFF STATION", self.bulletin)
        # google.maps geometry snippets are archived, never synthesized
        self.assertNotIn("google.maps", self.bulletin)

    def test_universal_parser_ingests_the_bulletin(self):
        parsed = parse_bulletin_text(self.bulletin, "v")
        ids = [w["warning_id"] for w in parsed["nav_warnings"]]
        self.assertEqual(sorted(ids),
                         ["NAVAREA V 0647/26", "NAVAREA V 0648/26"])
        # in-force index lines ('0646/26; 0645/26; ...') never split blocks
        self.assertEqual(len(ids), len(set(ids)))
        adrift = [w for w in parsed["nav_warnings"]
                  if w["warning_id"] == "NAVAREA V 0648/26"][0]
        self.assertEqual(adrift["latitude"], -28.131167)
        self.assertEqual(adrift["longitude"], -26.948333)
        self.assertEqual(
            adrift["spatial"]["features"][0]["geometry"]["type"], "Point")
        # 'CANCEL NAVAREA 0622/26' is a cross-ref, never a block split
        self.assertEqual(adrift["cross_refs"],
                         [{"number": "0622", "year": "26"}])


class TestRegionResolution(unittest.TestCase):
    def test_harvest_path_resolves_region_v(self):
        # The bare-number bulletin carries no NAVAREA numeral: region
        # resolution must come from the harvest dir name.
        bulletin = synthesize_bulletin(
            parse_aviso_records(_MINI_JSON)["records"])
        region_key, error = resolve_region(
            os.path.join("navareas", "navarea_v", "latest_raw.txt"), bulletin)
        self.assertEqual(region_key, "v")
        self.assertIsNone(error)

    def test_feed_registry_stays_fail_closed_for_v(self):
        # The CHM JSON feed is reference_only: the generic url_text
        # scraper must keep refusing it.
        self.assertIsNone(get_text_feed("v"))


if __name__ == "__main__":
    unittest.main()
