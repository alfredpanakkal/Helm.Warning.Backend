#!/usr/bin/env python3
"""test_navarea_xi.py — Unit Tests for NAVAREA XI Parser"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.navarea_xi_parser import parse_warning
from shared.utils import compute_differential

import unittest

class TestNavareaXiParser(unittest.TestCase):
    def test_sample_1_okinotori_shima(self):
        header = "NAVAREA XI NO.26-0451"
        raw = """NO.26-0451       Date:2026/10/09 07 UTC
NORTH PACIFIC, OKINOTORI SHIMA.
HATCH COVER ADRIFT IN 16-54.1N 134-39.5E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0451/26")
        self.assertEqual(nav_warn["category"], "drifting")
        self.assertEqual(nav_warn["issued_text"], "2026/10/09 07 UTC")

    def test_sample_2_military(self):
        header = "NAVAREA XI NO.26-0450"
        raw = """NO.26-0450       Date:2026/10/08 12 UTC
MARSHALL ISLANDS. GUNNERY EXERCISES."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0450/26")
        self.assertEqual(nav_warn["category"], "military")


    def test_flexible_date_parsing_with_minutes_and_hyphens(self):
        header = "NAVAREA XI NO.26-0452"
        raw = """NO.26-0452       Date: 2026-10-09 07:30 UTC
NORTH PACIFIC, HONSHU.
UNDERWATER CABLE OPERATION IN 35-12.0N 140-15.0E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0452/26")
        self.assertEqual(nav_warn["issued_text"], "2026-10-09 07:30 UTC")
        self.assertEqual(nav_warn["title"], "NORTH PACIFIC, HONSHU.")

    def test_date_does_not_contaminate_title(self):
        header = "NAVAREA XI NO.26-0453"
        raw = """NO.26-0453
Date: 2026/10/10 14:15 UTC
EAST CHINA SEA.
GUNNERY EXERCISES IN 29-30N 125-00E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0453/26")
        self.assertEqual(nav_warn["issued_text"], "2026/10/10 14:15 UTC")
        self.assertEqual(nav_warn["title"], "EAST CHINA SEA.")

    def test_id_fallback_from_raw_block_if_header_lacks_number(self):
        header = "NAVAREA XI"
        raw = """NO.26-0789       Date:2026/10/11 08 UTC
SOUTH CHINA SEA. SURVEY OPERATIONS."""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertEqual(nav_warn["warning_id"], "NAVAREA XI 0789/26")
        self.assertEqual(nav_warn["title"], "SOUTH CHINA SEA. SURVEY OPERATIONS.")

    def test_spatial_geometry_preserved_in_parsed_warning(self):
        header = "NAVAREA XI NO.26-0454"
        raw = """NO.26-0454       Date:2026/10/09 07 UTC
NORTH PACIFIC.
GUNNERY FIRING WITHIN AREA BOUNDED BY:
35-00N 140-00E, 35-00N 141-00E, 34-00N 141-00E, 34-00N 140-00E"""
        raw_msg, nav_warn, spatial = parse_warning(raw, header)
        self.assertIsNotNone(spatial)
        self.assertIn("type", spatial)
        self.assertEqual(nav_warn["spatial"], spatial)


class TestNavareaXiScraperLeadingLines(unittest.TestCase):
    def test_leading_anchor_or_header_does_not_drop_notice(self):
        from scripts.navarea_xi_scraper import _collect_from_text_lines
        html_blocks = [
            """
            <a name="warning_26_0500"></a>
            JCG NAVIGATIONAL BULLETIN
            NO.26-0500 Date:2026/10/12 09 UTC
            SEA OF JAPAN.
            LIGHT BUOY UNLIT IN 37-15.0N 136-40.0E
            """
        ]
        collected = _collect_from_text_lines(html_blocks)
        self.assertIn("NAVAREA XI NO.26-0500", collected)
        warn = collected["NAVAREA XI NO.26-0500"]
        self.assertIn("NO.26-0500", warn["date_line"])
        self.assertIn("SEA OF JAPAN.", warn["body"])
        # Ensure leading header artifact does not contaminate body
        self.assertNotIn("JCG NAVIGATIONAL BULLETIN", warn["body"])


class TestNavareaXiSpatialSync(unittest.TestCase):
    """Schema 20261019/20: per-script VALID_NAV_COLUMNS was removed; all syncs now
    delegate to shared.sync_engine, and spatial data flows into nav_warning_geometries
    via shared.models.build_geometry_payloads."""

    def test_spatial_flows_into_geometry_payloads(self):
        from shared.models import build_geometry_payloads
        record = {
            "title": "OKINOTORI SHIMA",
            "spatial": {"type": "Point", "coordinates": [134.6583, 16.9017]},
        }
        geoms = build_geometry_payloads(record)
        self.assertEqual(len(geoms), 1)
        self.assertEqual(geoms[0]["feature_type"], "point")
        self.assertEqual(geoms[0]["geojson"], record["spatial"])

    def test_spatial_feature_geometry_preserved(self):
        from shared.models import build_geometry_payloads
        record = {
            "title": "FIRING AREA",
            "spatial": {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[140.0, 35.0], [141.0, 35.0], [141.0, 34.0], [140.0, 34.0], [140.0, 35.0]]]},
                "properties": {"buffer_nm": 3},
            },
        }
        geoms = build_geometry_payloads(record)
        self.assertEqual(len(geoms), 1)
        self.assertEqual(geoms[0]["feature_type"], "polygon")
        self.assertEqual(geoms[0]["buffer_nm"], 3.0)
        self.assertEqual(geoms[0]["geojson"]["type"], "Polygon")

    def test_legacy_flat_columns_stripped_from_master_payload(self):
        from shared.models import build_master_payload
        master = build_master_payload({
            "navarea": "NAVAREA XI",
            "warning_id": "NAVAREA XI 0451/26",
            "title": "OKINOTORI",
            "spatial": {"type": "Point", "coordinates": [134.6583, 16.9017]},
            "latitude": 16.9017,
            "longitude": 134.6583,
            "issued_text": "2026/10/09 07 UTC",
            "category": "drifting",
        })
        # Legacy flat columns are stripped; spatial lives only in geometry payloads
        self.assertNotIn("spatial", master)
        self.assertNotIn("latitude", master)
        self.assertNotIn("longitude", master)
        self.assertNotIn("issued_text", master)
        self.assertNotIn("category", master)
        self.assertIn("drifting", master["categories"])
        self.assertEqual(master["triage_tier"], "A")

    def test_all_sync_scripts_delegate_to_shared_engine(self):
        import scripts.navarea_xi_sync as xi_sync
        import scripts.navarea_1_sync as uk_sync
        import scripts.baltic_sync as baltic_sync
        from shared.sync_engine import run_differential_sync
        self.assertIs(xi_sync.run_differential_sync, run_differential_sync)
        self.assertIs(uk_sync.run_differential_sync, run_differential_sync)
        self.assertIs(baltic_sync.run_differential_sync, run_differential_sync)


class TestNavareaXiDifferentialSync(unittest.TestCase):
    def setUp(self):
        self.scraped_warnings = [
            {"warning_id": "NAVAREA XI 0451/26", "title": "OKINOTORI"},
            {"warning_id": "NAVAREA XI 0450/26", "title": "MARSHALLS"},
            {"warning_id": "NAVAREA XI 0999/26", "title": "New"}
        ]
        self.scraped_messages = [
            {"warning_id": "NAVAREA XI 0451/26", "checksum_sha256": "hash_451_unchanged"},
            {"warning_id": "NAVAREA XI 0450/26", "checksum_sha256": "hash_450_new"},
            {"warning_id": "NAVAREA XI 0999/26", "checksum_sha256": "hash_999_new"}
        ]
        self.existing_warnings = {
            "NAVAREA XI 0451/26": {"warning_id": "NAVAREA XI 0451/26", "status": "active"},
            "NAVAREA XI 0450/26": {"warning_id": "NAVAREA XI 0450/26", "status": "active"},
            "NAVAREA XI 0100/26": {"warning_id": "NAVAREA XI 0100/26", "status": "active"}
        }
        self.existing_checksums = {
            ("NAVAREA XI 0451/26", "hash_451_unchanged"),
            ("NAVAREA XI 0450/26", "hash_450_old"),
            ("NAVAREA XI 0100/26", "hash_100_old")
        }

    def test_differential_bucketing(self):
        diff = compute_differential(
            self.scraped_warnings, self.scraped_messages,
            self.existing_warnings, self.existing_checksums
        )
        self.assertIn("NAVAREA XI 0451/26", diff["skip"])
        self.assertEqual(len(diff["skip"]), 1)
        new_ids = [w["warning_id"] for w, m in diff["new"]]
        self.assertIn("NAVAREA XI 0999/26", new_ids)
        self.assertEqual(len(diff["new"]), 1)
        update_ids = [w["warning_id"] for w, m in diff["update"]]
        self.assertIn("NAVAREA XI 0450/26", update_ids)
        self.assertEqual(len(diff["update"]), 1)
        self.assertIn("NAVAREA XI 0100/26", diff["cancel"])
        self.assertEqual(len(diff["cancel"]), 1)


if __name__ == "__main__":
    unittest.main()
