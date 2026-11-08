"""NAVAREA VIII region config in the universal parser (A/B parity).

The 'viii' region key routes NHO India bulletins through the universal
parser with config parity to the legacy scripts/navarea_8_parser.py:
identical warning ids, geometries, cross-refs, titles and validity
dates, so run_navarea_8's VIII_PARSER=universal switch and the legacy
parser's eventual retirement are output-equivalent. Rule-first only by
construction: 'viii' is deliberately NOT in UNIVERSAL_REGIONS, and the
Gemini layer refuses keys outside that dict (same mechanism as the
AUSCOAST pseudo-regions).
"""
import unittest
from datetime import datetime, timezone

from shared.navarea_universal_text import UNIVERSAL_REGIONS, NAVAREA_NAMES
from shared.gemini_navarea_parser import parse_bulletin_with_fallback
from scripts.navarea_universal_parser import (
    _region_config, _normalize_flattened_items,
    parse_bulletin_text as parse_universal,
)
from scripts.navarea_8_parser import parse_bulletin_text as parse_legacy

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)

VIII_1139_BODY = (
    "INDIA WEST COAST - OFF MUMBAI TO DAMAN (.) CHARTS IN 21 292 INT 7021 (.) "
    "POSH NATUNA, POSH PANGLIMA AND POSH ARCTURUS WILL CARRY OUT PIPELINE "
    "REPLACEMENT WORK FROM 30 OCT 26 TO 14 JAN 27 IN AREAS BOUNDED BY "
    "(A) 20-12.94N 072-25.7E, 20-12.83N 072-31.33E, 20-07.98N 072-31.22E, "
    "20-08.09N 072-25.59E (B) 19-41.07N 071-06.86E, 19-40.69N 071-36.43E, "
    "19-12.14N 071-35.97E, 19-12.52N 071-06.49E (C) 19-24.28N 071-55.82E, "
    "19-23.94N 072-16.01E, 19-08.52N 072-15.7E, 19-08.86N 071-55.54E "
    "(D) 20-20.75N 071-41.13E, 20-20.33N 072-06.74E, 20-04.5N 072-06.42E, "
    "20-04.92N 071-40.86E 2. CANCEL THIS MSG 141830 UTC JAN 27"
)

# Mirror-style bulletin: one long line per warning (the SeaLagom mirror
# flattens line breaks), 'NAVAREA VIII -n/yy' dash headers, '(.)'
# prosigns, an 'AS ON' snapshot header, a timed self-cancel dateline,
# a MSG-form cancel cross-ref and an UNTIL date-only stamp.
VIII_BULLETIN = (
    "NAVAREA VIII - WARNINGS IN FORCE AS ON 08 NOVEMBER 2026\n"
    "NAVAREA VIII -1102/26 INDIA WEST COAST - KARWAR (.) CHARTS IN 215 257 "
    "INT 7343 (.) HYDROGRAPHIC SURVEY UNDER PROGRESS IN AREA BOUNDED WITHIN "
    "14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E 2. CANCEL THIS MSG "
    "301000Z NOV 26 3. CANCEL NAVAREA VIII MSG 1024/26\n"
    "NAVAREA VIII -1139/26 " + VIII_1139_BODY + "\n"
    "NAVAREA VIII -1105/26 INDIA EAST COAST (.) FIRING EXERCISE IN AREA "
    "BOUNDED BY 15-00.0N 073-00.0E, 15-00.0N 073-10.0E, 14-50.0N 073-10.0E, "
    "14-50.0N 073-00.0E UNTIL 31 DEC 26"
)

EXPECTED_IDS = ["NAVAREA VIII 1102/26", "NAVAREA VIII 1139/26",
                "NAVAREA VIII 1105/26"]


class TestViiiRegionConfig(unittest.TestCase):
    def test_viii_is_rule_only_by_construction(self):
        # NOT in UNIVERSAL_REGIONS: the Gemini layer refuses keys outside
        # that dict, so NAVAREA VIII can never touch the model.
        self.assertNotIn("viii", UNIVERSAL_REGIONS)
        # The Gemini fallback routes any non-UNIVERSAL_REGIONS key
        # straight to the rule parser with provenance stamped.
        payload = parse_bulletin_with_fallback(
            VIII_BULLETIN, "viii",
            lambda text, key: {"memo": {"region": key}})
        self.assertEqual(payload["memo"].get("parse_provenance"), "rule")

    def test_region_config_matches_legacy_identity(self):
        cfg = _region_config("viii")
        self.assertEqual(cfg["source_id"], "nho-navarea-viii")
        self.assertEqual(cfg["navarea_id"], "VIII")
        self.assertEqual(cfg["id_prefix"], "NAVAREA VIII")
        self.assertTrue(cfg["flatten_items"])
        self.assertTrue(cfg["validity_requires_time"])
        self.assertEqual(NAVAREA_NAMES.get("viii"), "Indian Ocean")

    def test_header_patterns_cover_live_nho_forms(self):
        cfg = _region_config("viii")
        for sample in ("NAVAREA VIII -1102/26", "NAVAREA VIII 1066/26",
                       "NAVAREA VIII MSG 293/26"):
            self.assertTrue(any(r.search(sample) for r in cfg["header_res"]),
                            sample)
        for sample in ("CANCEL NAVAREA VIII MSG 1024/26",
                       "CANCEL NAVAREA VIII -1096/26",
                       "CANCEL NAVAREA VIII 293/26"):
            self.assertTrue(any(r.search(sample) for r in cfg["cancel_res"]),
                            sample)

    def test_flattened_item_normalization(self):
        body = ("SURVEY IN AREA BOUNDED WITHIN 14-47.2N TO 14-50.9N AND "
                "074-02.8E TO 074-08.15E 2. CANCEL THIS MSG 301000Z NOV 26 "
                "RADIUS 2.5NM RESTRICTED")
        normalized = _normalize_flattened_items(body)
        # The item marker gets its own line; coordinate fragments and
        # decimal quantities never match.
        lines = [l for l in normalized.split("\n") if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("2. CANCEL"))


class TestViiiUniversalParse(unittest.TestCase):
    def test_e2e_three_warnings_no_phantom(self):
        parsed = parse_universal(VIII_BULLETIN, "viii", now_utc=NOW)
        warnings = parsed["nav_warnings"]
        self.assertEqual([w["warning_id"] for w in warnings], EXPECTED_IDS)
        for w in warnings:
            self.assertEqual(w["source_id"], "nho-navarea-viii")
            self.assertEqual(w["navarea"], "VIII")
        # The MSG-form cancel cross-ref must NOT create a phantom block.
        self.assertEqual(
            parsed["memo"]["in_force_as_on"], "2026-11-08T00:00:00")

    def test_1139_four_separate_polygons(self):
        parsed = parse_universal(VIII_BULLETIN, "viii", now_utc=NOW)
        w1139 = parsed["nav_warnings"][1]
        self.assertEqual(w1139["geometry_sub_areas"], ["A", "B", "C", "D"])
        features = w1139["spatial"]["features"]
        self.assertEqual(len(features), 4)
        for feature in features:
            self.assertEqual(feature["geometry"]["type"], "Polygon")
            self.assertEqual(len(feature["geometry"]["coordinates"][0]), 5)
        first = features[0]["geometry"]["coordinates"][0][0]
        self.assertAlmostEqual(first[0], 72.428333, places=5)
        self.assertAlmostEqual(first[1], 20.215667, places=5)

    def test_validity_time_of_day_contract(self):
        parsed = parse_universal(VIII_BULLETIN, "viii", now_utc=NOW)
        by_id = {w["warning_id"]: w for w in parsed["nav_warnings"]}
        # Timed self-cancel dateline is kept (carries a time of day).
        self.assertEqual(by_id["NAVAREA VIII 1102/26"]["valid_to"],
                         "2026-11-30T10:00:00Z")
        # Date-only 'UNTIL 31 DEC 26' is dropped — no time is invented.
        self.assertIsNone(by_id["NAVAREA VIII 1105/26"]["valid_to"])

    def test_cancel_cross_refs_extracted(self):
        parsed = parse_universal(VIII_BULLETIN, "viii", now_utc=NOW)
        w1102 = parsed["nav_warnings"][0]
        self.assertEqual(w1102["cross_refs"],
                         [{"number": "1024", "year": "26"}])

    def test_dash_cancel_ref_never_splits_phantom(self):
        # Legacy VIII split_into_warnings has NO cancel-prefix guard, so a
        # dash-form cross-ref ('CANCEL NAVAREA VIII -1096/26') creates a
        # phantom warning there. The universal path guards it: the same
        # text yields ONE warning.
        text = ("NAVAREA VIII -1102/26 INDIA WEST COAST - KARWAR (.) "
                "CANCEL NAVAREA VIII -1096/26")
        parsed = parse_universal(text, "viii", now_utc=NOW)
        self.assertEqual(len(parsed["nav_warnings"]), 1)
        # Documents the legacy bug this migration fixes.
        legacy = parse_legacy(text, now_utc=NOW)
        self.assertEqual(len(legacy["nav_warnings"]), 2)


class TestViiiLegacyParity(unittest.TestCase):
    """A/B parity: universal 'viii' output vs the legacy VIII parser.

    Compared per warning: id, source, navarea, title, categories,
    cross-refs, validity dates, geometry (type + coordinates) and
    geometry sub-area labels. NOT compared: qa_flags / data_quality /
    zone_label props (the universal path is deliberately richer).
    """

    def test_parity_on_mirror_bulletin(self):
        universal = parse_universal(VIII_BULLETIN, "viii", now_utc=NOW)
        legacy = parse_legacy(VIII_BULLETIN, now_utc=NOW)
        self.assertEqual([w["warning_id"] for w in universal["nav_warnings"]],
                         [w["warning_id"] for w in legacy["nav_warnings"]])
        for uw, lw in zip(universal["nav_warnings"], legacy["nav_warnings"]):
            for key in ("warning_id", "canonical_id", "source_id", "navarea",
                        "title", "categories", "cross_refs", "valid_from",
                        "valid_to", "geometry_sub_areas"):
                self.assertEqual(uw[key], lw[key],
                                 uw["warning_id"] + " " + key)
            self.assertEqual(uw["spatial"], lw["spatial"],
                             uw["warning_id"] + " spatial")


if __name__ == "__main__":
    unittest.main()
