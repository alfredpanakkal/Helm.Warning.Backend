"""Phase B4 regression tests for Python triage and database publication contracts."""

import unittest
from pathlib import Path

from shared.models import (
    CoordinateProvenance,
    DataQuality,
    ParsingMethod,
    TriageRecord,
    TriageTier,
    UNPLOTTED_REASONS,
    build_geometry_payloads,
    build_master_payload,
)
from shared.triage import assign_final_triage


def point_record(**overrides):
    record = {
        "navarea": "NAVAREA I",
        "warning_id": "123/26",
        "title": "Test warning",
        "raw_text": "TEST WARNING",
        "source_id": "test",
        "latitude": 20.0,
        "longitude": 70.0,
        "spatial": {"type": "Point", "coordinates": [70.0, 20.0]},
        "data_quality": "EXPLICIT",
        "parsing_method": "RULE",
        "qa_flags": [],
        "status": "active",
    }
    record.update(overrides)
    return record


def triage_record(**overrides):
    record = TriageRecord(
        coordinates=[
            CoordinateProvenance(
                raw_token="20-00N 070-00E",
                lat=20.0,
                lon=70.0,
            )
        ]
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def db_tier_a_check(row):
    """Simulate chk_tier_a_invariants + the B4 Tier-A QA guard."""
    if row.get("triage_tier") != "A":
        return True
    return (
        row.get("data_quality") == "EXPLICIT"
        and row.get("parsing_method") == "RULE"
        and row.get("unplotted_reason") is None
        and row.get("status", "active") != "superseded"
        and not any(
            flag in (row.get("qa_flags") or [])
            for flag in ("has_incomplete_zone", "has_repairs")
        )
    )


class TestTierAInvariants(unittest.TestCase):
    def test_clean_polygon_is_tier_a(self):
        record = point_record(
            spatial={
                "type": "Polygon",
                "coordinates": [[[70, 20], [71, 20], [71, 21], [70, 21], [70, 20]]],
            }
        )
        self.assertEqual(build_master_payload(record)["triage_tier"], "A")

    def test_clean_corridor_is_tier_a(self):
        record = point_record(
            spatial={
                "type": "LineString",
                "coordinates": [[70, 20], [71, 21]],
                "properties": {"feature_type": "CORRIDOR", "corridor_clearance_nm": 2.0},
            }
        )
        payload = build_geometry_payloads(record)
        self.assertEqual(payload[0]["feature_type"], "CORRIDOR")
        self.assertEqual(payload[0]["corridor_clearance_nm"], 2.0)
        self.assertEqual(build_master_payload(record)["triage_tier"], "A")

    def test_clean_sector_sweep_is_tier_a(self):
        record = point_record(
            spatial={
                "type": "Polygon",
                "coordinates": [[[70, 20], [71, 20], [71, 21], [70, 21], [70, 20]]],
                "properties": {
                    "feature_type": "SWEEP_ARC",
                    "sweep_radius_nm": 10.0,
                    "sweep_start_azimuth": 270.0,
                    "sweep_end_azimuth": 360.0,
                },
            }
        )
        payload = build_geometry_payloads(record)
        self.assertEqual(payload[0]["feature_type"], "SWEEP_ARC")
        self.assertEqual(build_master_payload(record)["triage_tier"], "A")

    def test_feature_collection_preserves_metadata_per_geometry(self):
        record = point_record(
            spatial={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[70, 20], [71, 21]],
                        },
                        "properties": {
                            "zone_label": "Corridor A",
                            "feature_type": "CORRIDOR",
                            "buffer_nm": 0,
                            "corridor_half_width_nm": 1.25,
                            "corridor_clearance_nm": 2.5,
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[72, 20], [73, 20], [73, 21], [72, 20]]],
                        },
                        "properties": {
                            "zone_label": "Sweep B",
                            "feature_type": "SWEEP_ARC",
                            "sweep_radius_nm": 8.0,
                            "sweep_start_azimuth": 270.0,
                            "sweep_end_azimuth": 15.0,
                        },
                    },
                ],
            }
        )
        payloads = build_geometry_payloads(record)
        self.assertEqual([item["zone_label"] for item in payloads], ["Corridor A", "Sweep B"])
        self.assertEqual(payloads[0]["feature_type"], "CORRIDOR")
        self.assertEqual(payloads[0]["buffer_nm"], 0.0)
        self.assertEqual(payloads[0]["corridor_half_width_nm"], 1.25)
        self.assertEqual(payloads[0]["corridor_clearance_nm"], 2.5)
        self.assertEqual(payloads[1]["feature_type"], "SWEEP_ARC")
        self.assertEqual(payloads[1]["sweep_radius_nm"], 8.0)
        self.assertEqual(payloads[1]["sweep_start_azimuth"], 270.0)
        self.assertEqual(payloads[1]["sweep_end_azimuth"], 15.0)
        for key in ("sweep_radius_nm", "sweep_start_azimuth", "sweep_end_azimuth"):
            self.assertNotIn(key, payloads[0])
        for key in ("corridor_half_width_nm", "corridor_clearance_nm"):
            self.assertNotIn(key, payloads[1])

    def test_zero_metadata_is_preserved_and_missing_metadata_is_omitted(self):
        record = point_record(
            spatial={
                "type": "LineString",
                "coordinates": [[70, 20], [71, 21]],
                "properties": {
                    "feature_type": "CORRIDOR",
                    "corridor_half_width_nm": 0,
                },
            }
        )
        payload = build_geometry_payloads(record)[0]
        self.assertIn("corridor_half_width_nm", payload)
        self.assertEqual(payload["corridor_half_width_nm"], 0)
        self.assertNotIn("corridor_clearance_nm", payload)
        self.assertNotIn("sweep_radius_nm", payload)

    def test_informational_geometry_basis_flag_does_not_block_tier_a(self):
        record = point_record(qa_flags=["geometry_basis:keyword:area_bounded"])
        self.assertEqual(build_master_payload(record)["triage_tier"], "A")


class TestTierBInvariants(unittest.TestCase):
    def test_inferred_geometry_routes_to_b(self):
        rec = triage_record(data_quality=DataQuality.INFERRED)
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_incomplete_zone_with_valid_geometry_routes_to_b(self):
        rec = triage_record(
            data_quality=DataQuality.AMBIGUOUS,
            qa_flags=["has_incomplete_zone"],
        )
        rec.spatial = {"type": "Point", "coordinates": [70.0, 20.0]}
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

        master = build_master_payload(
            point_record(
                data_quality="AMBIGUOUS",
                qa_flags=["has_incomplete_zone"],
            )
        )
        self.assertEqual(master["triage_tier"], "B")

    def test_partial_validation_failure_with_valid_geometry_routes_to_b(self):
        rec = triage_record(qa_flags=["VALIDATION_FAILED"])
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_has_repairs_flag_with_valid_geometry_routes_to_b(self):
        rec = triage_record(qa_flags=["has_repairs"])
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_repaired_coordinate_routes_to_b(self):
        rec = triage_record()
        rec.coordinates[0].repairs = ["rule18"]
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_superseded_geometry_routes_to_b(self):
        rec = triage_record(status="superseded")
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

        master = build_master_payload(point_record(status="superseded"))
        self.assertEqual(master["triage_tier"], "B")

    def test_ai_parsed_geometry_routes_to_b(self):
        rec = triage_record(parsing_method=ParsingMethod.AI)
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

        master = build_master_payload(point_record(parsing_method="AI"))
        self.assertEqual(master["triage_tier"], "B")


class TestTierCInvariants(unittest.TestCase):
    def test_zero_geometry_routes_to_c(self):
        master = build_master_payload(point_record(spatial=None, latitude=None, longitude=None))
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "no_valid_geometry")

    def test_record_triage_maps_missing_hemisphere_without_geometry(self):
        rec = triage_record(qa_flags=["MISSING_HEM"], coordinates=[])
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.C)
        self.assertEqual(rec.unplotted_reason, "missing_hemisphere")

    def test_geometry_bearing_missing_hemisphere_is_review_not_quarantine(self):
        rec = triage_record(qa_flags=["MISSING_HEM"])
        assign_final_triage(rec)
        self.assertEqual(rec.triage_tier, TriageTier.B)

    def test_missing_hemisphere_routes_to_c_with_specific_reason(self):
        master = build_master_payload(
            point_record(
                spatial=None, latitude=None, longitude=None,
                qa_flags=["MISSING_HEM"],
            )
        )
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "missing_hemisphere")

    def test_invalid_polygon_routes_to_c_with_validation_reason(self):
        master = build_master_payload(
            point_record(
                spatial=None, latitude=None, longitude=None,
                qa_flags=["VALIDATION_FAILED"],
            )
        )
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "validation_failed")

    def test_all_incomplete_zones_route_to_c(self):
        master = build_master_payload(
            point_record(
                spatial=None, latitude=None, longitude=None,
                data_quality="AMBIGUOUS",
                qa_flags=["has_incomplete_zone"],
            )
        )
        self.assertEqual(master["triage_tier"], "C")
        self.assertEqual(master["unplotted_reason"], "no_valid_geometry")

    def test_unknown_unplotted_reason_is_normalized(self):
        master = build_master_payload(
            point_record(unplotted_reason="not_a_database_reason")
        )
        self.assertEqual(master["triage_tier"], "B")
        self.assertEqual(master["unplotted_reason"], "no_valid_geometry")

    def test_every_emitted_reason_is_database_whitelisted(self):
        for flags, expected in (
            ([], "no_valid_geometry"),
            (["MISSING_HEM"], "missing_hemisphere"),
            (["VALIDATION_FAILED"], "validation_failed"),
        ):
            master = build_master_payload(
                point_record(spatial=None, latitude=None, longitude=None, qa_flags=flags)
            )
            self.assertIn(master["unplotted_reason"], UNPLOTTED_REASONS)
            self.assertEqual(master["unplotted_reason"], expected)


class TestDatabaseConstraintAlignment(unittest.TestCase):
    def test_database_tier_a_check_accepts_clean_row(self):
        self.assertTrue(db_tier_a_check({
            "triage_tier": "A",
            "data_quality": "EXPLICIT",
            "parsing_method": "RULE",
            "unplotted_reason": None,
            "status": "active",
            "qa_flags": [],
        }))

    def test_database_tier_a_check_rejects_each_invariant_violation(self):
        clean = {
            "triage_tier": "A",
            "data_quality": "EXPLICIT",
            "parsing_method": "RULE",
            "unplotted_reason": None,
            "status": "active",
            "qa_flags": [],
        }
        invalid_rows = (
            {"data_quality": "INFERRED"},
            {"parsing_method": "AI"},
            {"unplotted_reason": "no_valid_geometry"},
            {"status": "superseded"},
            {"qa_flags": ["has_incomplete_zone"]},
            {"qa_flags": ["has_repairs"]},
        )
        for change in invalid_rows:
            with self.subTest(change=change):
                row = {**clean, **change}
                self.assertFalse(db_tier_a_check(row))

    def test_non_a_rows_are_not_subject_to_tier_a_check(self):
        for tier in ("B", "C"):
            self.assertTrue(db_tier_a_check({"triage_tier": tier}))



class TestMigrationContract(unittest.TestCase):

    def test_geometry_metadata_rpc_insert_mapping_is_complete(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261112_triage_contract_alignment.sql"
        ).read_text(encoding="utf-8")
        insert_start = migration.index("INSERT INTO public.nav_warning_geometries")
        insert_end = migration.index("RETURNING geom_id", insert_start)
        rpc_insert = migration[insert_start:insert_end]
        normalized_insert = " ".join(rpc_insert.split())
        expected_mapping = (
            "(warning_id, zone_label, feature_type, buffer_nm, corridor_half_width_nm, "
            "corridor_clearance_nm, sweep_start_azimuth, sweep_end_azimuth, "
            "sweep_radius_nm, geom_postgis) VALUES "
            "(v_id, g->>'zone_label', v_ftype, COALESCE((g->>'buffer_nm')::numeric, 0), "
            "NULLIF(g->>'corridor_half_width_nm', '')::double precision, "
            "NULLIF(g->>'corridor_clearance_nm', '')::double precision, "
            "NULLIF(g->>'sweep_start_azimuth', '')::double precision, "
            "NULLIF(g->>'sweep_end_azimuth', '')::double precision, "
            "NULLIF(g->>'sweep_radius_nm', '')::double precision, "
            "ST_SetSRID(ST_GeomFromGeoJSON(g->'geojson'), 4326)::geography)"
        )
        self.assertIn(expected_mapping, normalized_insert)

    def test_migration_persists_and_exposes_geometry_metadata(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261112_triage_contract_alignment.sql"
        ).read_text(encoding="utf-8")
        for contract in (
            "corridor_clearance_nm DOUBLE PRECISION",
            "g.corridor_clearance_nm",
            "g.sweep_radius_nm",
            "g.sweep_start_azimuth",
            "g.sweep_end_azimuth",
            "g.zone_label",
            "g->>'corridor_clearance_nm'",
            "chk_tier_a_qa_flags",
            "CREATE OR REPLACE VIEW public.nav_warnings_review_queue",
            "w.status IN ('active', 'superseded')",
            "w.parsing_method",
            "w.qa_flags",
            "w.unplotted_reason",
        ):
            self.assertIn(contract, migration)
        self.assertIn("SET triage_tier = 'B'", migration)
        self.assertNotIn("SET triage_tier = 'A'", migration)


if __name__ == "__main__":
    unittest.main()
