#!/usr/bin/env python3
"""Tests for scripts/parsing_audit.py — manual Supabase parsing audit &
Gemini-assisted correction engine.

Pure unit tests: no network, no Supabase, no Gemini API. All external
services are faked (FakeClient mimics the chainable supabase-py query
builder) or mocked. CI runs `python -m unittest discover tests` without
installing requirements, so nothing here may import supabase/requests.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import parsing_audit as pa  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
RAW_POINT = "DRIFTING CONTAINER REPORTED AT 52-45.1N 002-12.4E."
RAW_PLAIN = "SUBSEA CABLE MAINTENANCE OPERATIONS IN PROGRESS IN THE CHANNEL."

NOW_ISO = "2026-10-26T00:00:00+00:00"


def make_row(**over):
    """A clean, fully populated nav_warnings row (tier B, no geometry)."""
    row = {
        "id": "00000000-0000-4000-8000-000000000001",
        "canonical_id": "NAVAREA XI 001/26",
        "navarea": "NAVAREA XI",
        "source_id": "2026001XI",
        "title": "CABLE MAINTENANCE",
        "area_text": "AREA XI",
        "categories": ["general"],
        "status": "active",
        "triage_tier": "B",
        "data_quality": "EXPLICIT",
        "parsing_method": "RULE",
        "qa_flags": [],
        "unplotted_reason": None,
        "valid_from": "2026-10-01T00:00:00+00:00",
        "valid_to": "2027-01-01T00:00:00+00:00",
        "issued_at": "2026-10-01T00:00:00+00:00",
        "created_at": "2026-10-01T00:00:00+00:00",
        "updated_at": "2026-10-01T00:00:00+00:00",
        "duplicate_of_id": None,
        "raw_text": RAW_PLAIN,
    }
    row.update(over)
    return row


def make_geom_row(rec, feature_type="POINT"):
    return {"geom_id": "g1", "warning_id": rec["id"], "feature_type": feature_type,
            "zone_label": None, "buffer_nm": 0}


def make_issue(rec, code, severity="high", detail="test issue"):
    return {"canonical_id": rec["canonical_id"], "record_id": rec["id"],
            "code": code, "severity": severity, "detail": detail}


def make_proposal(rec, field, proposed, current=None, quote=None, snap=None):
    return {
        "proposal_id": pa._pid("run-1", rec["id"], field, proposed),
        "audit_run_id": "run-1",
        "record_id": rec["id"],
        "canonical_id": rec["canonical_id"],
        "navarea": rec["navarea"],
        "field": field,
        "current_value": current if current is not None else rec.get(field),
        "proposed_value": proposed,
        "evidence_quote": quote,
        "reason": "evidence-based correction from raw text",
        "source": "gemini",
        "model": "gemini-3.8-flash",
        "confidence": 0.9,
        "snapshot_updated_at": snap or rec["updated_at"],
        "status": "approved",
    }


def quiet(*_a, **_k):
    pass


# ---------------------------------------------------------------------------
# Fakes: supabase-py chainable client
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    """Chainable query builder. Records any mutating call so read-only
    enforcement can be asserted in tests."""

    def __init__(self, client, table):
        self._client = client
        self._table = table
        self._filters = []
        self._count = None
        self._range = None
        self._limit = None
        self._order = None

    def select(self, *_cols, count=None):
        self._count = count
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, set(vals)))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def update(self, *a, **k):  # pragma: no cover - should never run
        self._client.write_attempts.append(("update", self._table))
        return self

    def insert(self, *a, **k):  # pragma: no cover - should never run
        self._client.write_attempts.append(("insert", self._table))
        return self

    def delete(self, *a, **k):  # pragma: no cover - should never run
        self._client.write_attempts.append(("delete", self._table))
        return self

    def execute(self):
        client = self._client
        if self._table in client.fail_tables:
            raise RuntimeError("simulated table failure")
        if self._range and self._range[0] in client.fail_pages:
            raise RuntimeError("simulated page fetch failure")
        if self._count and client.fail_count_query:
            raise RuntimeError("simulated count query failure")
        rows = list(client.tables.get(self._table, []))
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if r.get(col) == val]
            else:
                rows = [r for r in rows if r.get(col) in val]
        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: (r.get(col) is None, str(r.get(col))),
                          reverse=desc)
        count = len(rows) if self._count else None
        if self._range:
            lo, hi = self._range
            rows = rows[lo:hi + 1]
        if self._limit is not None:
            rows = rows[:self._limit]
        return FakeResponse(rows, count)


class FakeClient:
    def __init__(self, tables=None):
        self.tables = tables if tables is not None else {}
        self.rpc_calls = []
        self.write_attempts = []
        self.rpc_errors = []      # exceptions raised by rpc().execute(), in order
        self.fail_pages = set()   # range offsets that raise on .execute()
        self.fail_tables = set()  # table names that raise on .execute()
        self.fail_count_query = False

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        client = self

        class _Rpc:
            def execute(self):
                if client.rpc_errors:
                    raise client.rpc_errors.pop(0)
                return FakeResponse([{"ok": True}], None)

        return _Rpc()


def ids_rows(n, navarea="NAVAREA XI"):
    return [{"id": "r%05d" % i, "canonical_id": "NAVAREA XI %d/26" % i,
             "navarea": navarea} for i in range(n)]


# ---------------------------------------------------------------------------
# resolve_navarea
# ---------------------------------------------------------------------------
class TestResolveNavarea(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(pa.resolve_navarea("xi"), "NAVAREA XI")
        self.assertEqual(pa.resolve_navarea("XI"), "NAVAREA XI")
        self.assertEqual(pa.resolve_navarea("baltic"), "NAVAREA BALTIC")
        self.assertEqual(pa.resolve_navarea("NAVAREA IV"), "NAVAREA IV")
        self.assertEqual(pa.resolve_navarea("I"), "NAVAREA I")

    def test_all_variants_return_none(self):
        self.assertIsNone(pa.resolve_navarea("ALL"))
        self.assertIsNone(pa.resolve_navarea("all"))
        self.assertIsNone(pa.resolve_navarea(""))
        self.assertIsNone(pa.resolve_navarea(None))

    def test_unknown_raises(self):
        for bad in ("XXII", "KAPPA", "NAVAREA 11"):
            with self.assertRaises(ValueError):
                pa.resolve_navarea(bad)


# ---------------------------------------------------------------------------
# Complete-coverage pagination
# ---------------------------------------------------------------------------
class TestFetchAllWarnings(unittest.TestCase):
    def test_complete_pagination_2501_rows(self):
        client = FakeClient({"nav_warnings": ids_rows(2501)})
        rows, expected, complete, page_errors = pa.fetch_all_warnings(
            client, None, None, 500, log=quiet)
        self.assertEqual(len(rows), 2501)
        self.assertEqual(expected, 2501)
        self.assertTrue(complete)
        self.assertEqual(page_errors, 0)

    def test_partial_page_failure_is_not_complete(self):
        client = FakeClient({"nav_warnings": ids_rows(2501)})
        client.fail_pages = {1500}
        rows, expected, complete, page_errors = pa.fetch_all_warnings(
            client, None, None, 500, log=quiet)
        self.assertEqual(len(rows), 1500)
        self.assertEqual(expected, 2501)
        self.assertFalse(complete)
        self.assertEqual(page_errors, 1)

    def test_count_query_failure_degrades_to_page_draining(self):
        client = FakeClient({"nav_warnings": ids_rows(30)})
        client.fail_count_query = True
        rows, expected, complete, page_errors = pa.fetch_all_warnings(
            client, None, None, 10, log=quiet)
        self.assertEqual(len(rows), 30)
        self.assertIsNone(expected)
        self.assertTrue(complete)
        self.assertEqual(page_errors, 0)

    def test_navarea_filter(self):
        rows = ids_rows(2, "NAVAREA XI") + ids_rows(1, "NAVAREA I")
        client = FakeClient({"nav_warnings": rows})
        got, expected, complete, _ = pa.fetch_all_warnings(
            client, "NAVAREA XI", None, 500, log=quiet)
        self.assertEqual(len(got), 2)
        self.assertEqual(expected, 2)
        self.assertTrue(complete)

    def test_warning_id_filter(self):
        rec = make_row()
        client = FakeClient({"nav_warnings": [rec, make_row(id="00000000-0000-4000-8000-000000000002",
                                                            canonical_id="NAVAREA XI 002/26")]})
        got, expected, complete, _ = pa.fetch_all_warnings(
            client, None, "NAVAREA XI 001/26", 500, log=quiet)
        self.assertEqual(len(got), 1)
        self.assertEqual(expected, 1)
        self.assertTrue(complete)

    def test_warning_id_accepts_record_uuid(self):
        rec = make_row()
        other = make_row(id="00000000-0000-4000-8000-000000000002",
                         canonical_id="NAVAREA XI 002/26")
        client = FakeClient({"nav_warnings": [rec, other]})
        got, expected, complete, _ = pa.fetch_all_warnings(
            client, None, rec["id"], 500, log=quiet)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["id"], rec["id"])
        self.assertEqual(expected, 1)
        self.assertTrue(complete)


# ---------------------------------------------------------------------------
# GeoJSON checks
# ---------------------------------------------------------------------------
class TestCheckGeojson(unittest.TestCase):
    def test_out_of_bounds_longitude(self):
        issues = pa.check_geojson({"type": "Point", "coordinates": [200.0, 10.0]}, None)
        self.assertIn("geojson_coordinate_violation", [i[0] for i in issues])

    def test_out_of_bounds_latitude(self):
        issues = pa.check_geojson({"type": "Point", "coordinates": [10.0, -95.0]}, None)
        self.assertIn("geojson_coordinate_violation", [i[0] for i in issues])

    def test_malformed_coordinate_structure(self):
        issues = pa.check_geojson({"type": "Point", "coordinates": "foo"}, None)
        self.assertIn("geojson_coordinate_violation", [i[0] for i in issues])

    def test_not_a_dict(self):
        issues = pa.check_geojson("not-json", None)
        self.assertEqual(issues[0][0], "invalid_geojson")

    def test_unclosed_polygon_ring(self):
        gj = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0]]]}
        issues = pa.check_geojson(gj, None)
        self.assertIn("polygon_ring_unclosed", [i[0] for i in issues])

    def test_short_polygon_ring(self):
        gj = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}
        issues = pa.check_geojson(gj, None)
        self.assertIn("polygon_ring_too_short", [i[0] for i in issues])

    def test_hemisphere_mismatch(self):
        gj = {"type": "Point", "coordinates": [2.20, -52.75]}
        issues = pa.check_geojson(gj, (52.75, 2.20))
        self.assertIn("hemisphere_mismatch", [i[0] for i in issues])

    def test_suspected_lat_lon_swap(self):
        gj = {"type": "Point", "coordinates": [5.5, 100.5]}
        issues = pa.check_geojson(gj, (5.5, 100.5))
        self.assertIn("suspected_lat_lon_swap", [i[0] for i in issues])

    def test_matching_point_no_issue(self):
        gj = {"type": "Point", "coordinates": [100.5, 5.5]}
        self.assertEqual(pa.check_geojson(gj, (5.5, 100.5)), [])

    def test_position_mismatch(self):
        gj = {"type": "Point", "coordinates": [21.0, 11.0]}
        issues = pa.check_geojson(gj, (10.0, 20.0))
        self.assertIn("geometry_position_mismatch", [i[0] for i in issues])


# ---------------------------------------------------------------------------
# Record checks
# ---------------------------------------------------------------------------
class TestCheckRecord(unittest.TestCase):
    def codes(self, rec, geom_rows=None, spatial_rows=None):
        return [i["code"] for i in pa.check_record(
            rec, geom_rows or [], spatial_rows or [], NOW_ISO)]

    def test_clean_row_has_no_issues(self):
        self.assertEqual(self.codes(make_row()), [])

    def test_tier_a_without_geometry(self):
        rec = make_row(triage_tier="A")
        self.assertIn("tier_a_without_geometry", self.codes(rec))

    def test_tier_a_with_unplotted_reason(self):
        rec = make_row(triage_tier="A", unplotted_reason="no coordinates")
        codes = self.codes(rec, geom_rows=[make_geom_row(rec)])
        self.assertIn("tier_a_with_unplotted_reason", codes)

    def test_missing_geometry_but_coordinates_in_text(self):
        rec = make_row(triage_tier="B", raw_text=RAW_POINT)
        codes = self.codes(rec, geom_rows=[])
        self.assertIn("missing_geometry_but_coordinates_in_text", codes)
        # With geometry present the issue must not fire (legitimate state).
        clean = make_row(triage_tier="B", raw_text=RAW_POINT)
        self.assertNotIn("missing_geometry_but_coordinates_in_text",
                          self.codes(clean, geom_rows=[make_geom_row(clean)]))

    def test_geometry_without_text_coordinates(self):
        rec = make_row(triage_tier="C", raw_text=RAW_PLAIN)
        codes = self.codes(rec, geom_rows=[make_geom_row(rec)])
        self.assertIn("geometry_without_text_coordinates", codes)

    def test_canonical_id_navarea_mismatch(self):
        rec = make_row(canonical_id="BA 001/26")
        self.assertIn("canonical_id_navarea_mismatch", self.codes(rec))

    def test_stale_active_past_validity(self):
        rec = make_row(valid_to="2026-01-01T00:00:00+00:00")
        self.assertIn("stale_active_past_validity", self.codes(rec))

    def test_validity_range_inverted(self):
        rec = make_row(valid_from="2026-12-01T00:00:00+00:00",
                       valid_to="2026-01-01T00:00:00+00:00")
        self.assertIn("validity_range_inverted", self.codes(rec))

    def test_invalid_status(self):
        self.assertIn("invalid_status", self.codes(make_row(status="live")))

    def test_invalid_triage_tier(self):
        self.assertIn("invalid_triage_tier", self.codes(make_row(triage_tier="D")))

    def test_invalid_data_quality(self):
        self.assertIn("invalid_data_quality", self.codes(make_row(data_quality="BAD")))

    def test_invalid_parsing_method(self):
        self.assertIn("invalid_parsing_method",
                      self.codes(make_row(parsing_method="MAGIC")))

    def test_missing_required_field(self):
        codes = self.codes(make_row(title=""))
        self.assertIn("missing_required_field:title", codes)

    def test_categories_empty_and_out_of_vocabulary(self):
        self.assertIn("categories_empty", self.codes(make_row(categories=[])))
        self.assertIn("categories_out_of_vocabulary",
                      self.codes(make_row(categories=["Military"])))

    def test_geometry_matching_source_text_has_no_issue(self):
        _c, lat, lon, spatial = pa.parse_coordinates(RAW_POINT)
        self.assertIsNotNone(spatial, "fixture raw text must parse deterministically")
        rec = make_row(triage_tier="A", raw_text=RAW_POINT)
        spatial_rows = [{"geojson_blob": spatial, "feature_type": "POINT",
                         "zone_label": None, "buffer_nm": 0}]
        self.assertEqual(self.codes(rec, geom_rows=[make_geom_row(rec)],
                                   spatial_rows=spatial_rows), [])


class TestDetectDuplicates(unittest.TestCase):
    def test_duplicate_title_candidate(self):
        a = make_row()
        b = make_row(id="00000000-0000-4000-8000-000000000002",
                     canonical_id="NAVAREA XI 002/26")
        issues = pa.detect_duplicates([a, b])
        self.assertIn("duplicate_title_candidate", [i["code"] for i in issues])

    def test_duplicate_raw_text(self):
        a = make_row()
        b = make_row(id="00000000-0000-4000-8000-000000000002",
                     canonical_id="NAVAREA XI 002/26", title="DIFFERENT TITLE")
        issues = pa.detect_duplicates([a, b])
        self.assertIn("duplicate_raw_text", [i["code"] for i in issues])

    def test_unique_rows_produce_no_duplicates(self):
        a = make_row()
        b = make_row(id="00000000-0000-4000-8000-000000000002",
                     canonical_id="NAVAREA XI 002/26", title="DIFFERENT TITLE",
                     raw_text="TOTALLY DIFFERENT WARNING TEXT.")
        self.assertEqual(pa.detect_duplicates([a, b]), [])


# ---------------------------------------------------------------------------
# Deterministic geometry proposals
# ---------------------------------------------------------------------------
class TestGeometryEwkt(unittest.TestCase):
    def test_point(self):
        feats = pa.geojson_to_ewkt_features(
            {"type": "Point", "coordinates": [2.206667, 52.751667]})
        self.assertEqual(feats[0]["ewkt"], "SRID=4326;POINT(2.206667 52.751667)")
        self.assertEqual(feats[0]["feature_type"], "POINT")

    def test_multipoint(self):
        feats = pa.geojson_to_ewkt_features(
            {"type": "MultiPoint", "coordinates": [[2.0, 3.0], [4.0, 5.0]]})
        self.assertEqual(feats[0]["ewkt"], "SRID=4326;MULTIPOINT((2 3), (4 5))")

    def test_linestring(self):
        feats = pa.geojson_to_ewkt_features(
            {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]})
        self.assertEqual(feats[0]["ewkt"], "SRID=4326;LINESTRING(0 0, 1 1)")
        self.assertEqual(feats[0]["feature_type"], "LINE")

    def test_polygon_ring_is_closed(self):
        feats = pa.geojson_to_ewkt_features(
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0]]]})
        self.assertEqual(feats[0]["ewkt"], "SRID=4326;POLYGON((0 0, 1 1, 1 0, 0 0))")
        self.assertEqual(feats[0]["feature_type"], "POLYGON")

    def test_unsupported_type_returns_empty(self):
        self.assertEqual(
            pa.geojson_to_ewkt_features({"type": "GeometryCollection", "coordinates": []}), [])


class TestBuildGeometryProposal(unittest.TestCase):
    def test_proposal_from_parsed_coordinates(self):
        rec = make_row(triage_tier="B", raw_text=RAW_POINT)
        prop = pa.build_geometry_proposal(rec, "run-1")
        self.assertIsNotNone(prop)
        self.assertEqual(prop["field"], "geometry")
        self.assertEqual(prop["source"], "deterministic_parser")
        self.assertEqual(prop["confidence"], 0.95)
        self.assertTrue(prop["requires_human_review"])
        feats = prop["proposed_value"]
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]["feature_type"], "POINT")
        self.assertIn("SRID=4326;POINT(", feats[0]["ewkt"])
        # Geometry must match the source position (lon 2.2067, lat 52.7517).
        import re
        m = re.match(r"SRID=4326;POINT\(([-\d.]+) ([-\d.]+)\)$", feats[0]["ewkt"])
        self.assertIsNotNone(m, feats[0]["ewkt"])
        self.assertAlmostEqual(float(m.group(1)), 2.206667, places=4)
        self.assertAlmostEqual(float(m.group(2)), 52.751667, places=4)

    def test_no_proposal_without_parsable_coordinates(self):
        rec = make_row(triage_tier="B", raw_text=RAW_PLAIN)
        self.assertIsNone(pa.build_geometry_proposal(rec, "run-1"))

    def test_proposal_id_is_deterministic(self):
        rec = make_row(triage_tier="B", raw_text=RAW_POINT)
        a = pa.build_geometry_proposal(rec, "run-1")
        b = pa.build_geometry_proposal(rec, "run-1")
        self.assertEqual(a["proposal_id"], b["proposal_id"])


# ---------------------------------------------------------------------------
# Gemini validation
# ---------------------------------------------------------------------------
class TestValidateAiCorrection(unittest.TestCase):
    def base_correction(self, **over):
        c = {"field": "categories", "current_value": ["general"],
             "proposed_value": ["subsea"], "evidence_quote": "SUBSEA CABLE",
             "reason": "text mentions subsea cable", "confidence": 0.9}
        c.update(over)
        return c

    def test_valid_correction_normalizes(self):
        rec = make_row(raw_text=RAW_PLAIN)
        norm, err = pa.validate_ai_correction(rec, self.base_correction())
        self.assertIsNone(err)
        self.assertEqual(norm["field"], "categories")
        self.assertEqual(norm["proposed_value"], ["subsea"])
        self.assertEqual(norm["confidence"], 0.9)
        self.assertIsInstance(norm["deterministic_agreement"], bool)

    def test_non_correctable_field_rejected(self):
        rec = make_row(raw_text=RAW_PLAIN)
        for field in ("status", "raw_text", "title", "valid_to", "geometry"):
            norm, err = pa.validate_ai_correction(
                rec, self.base_correction(field=field))
            self.assertIsNone(norm, field)
            self.assertIn("not correctable", err)

    def test_quote_must_be_exact_substring(self):
        rec = make_row(raw_text=RAW_PLAIN)
        norm, err = pa.validate_ai_correction(
            rec, self.base_correction(evidence_quote="NOT PRESENT IN TEXT"))
        self.assertIsNone(norm)
        self.assertIn("exact substring", err)

    def test_confidence_range(self):
        rec = make_row(raw_text=RAW_PLAIN)
        for conf in (1.5, -0.1, True, "high"):
            norm, err = pa.validate_ai_correction(
                rec, self.base_correction(confidence=conf))
            self.assertIsNone(norm, conf)
            self.assertIn("confidence", err)

    def test_proposed_equals_current_rejected(self):
        rec = make_row(raw_text=RAW_PLAIN, categories=["subsea"])
        norm, err = pa.validate_ai_correction(
            rec, self.base_correction(current_value=["subsea"]))
        self.assertIsNone(norm)
        self.assertIn("equals the current value", err)

    def test_triage_tier_vocabulary(self):
        rec = make_row(raw_text=RAW_PLAIN, triage_tier="B")
        norm, err = pa.validate_ai_correction(
            rec, self.base_correction(field="triage_tier", proposed_value="A"))
        self.assertIsNone(err)
        self.assertEqual(norm["proposed_value"], "A")
        _norm2, err2 = pa.validate_ai_correction(
            rec, self.base_correction(field="triage_tier", proposed_value="D"))
        self.assertIsNone(_norm2)
        self.assertIn("A, B or C", err2)

    def test_data_quality_vocabulary(self):
        rec = make_row(raw_text=RAW_PLAIN, data_quality="EXPLICIT")
        norm, err = pa.validate_ai_correction(
            rec, self.base_correction(field="data_quality", proposed_value="AMBIGUOUS"))
        self.assertIsNone(err)
        _norm2, err2 = pa.validate_ai_correction(
            rec, self.base_correction(field="data_quality", proposed_value="BAD"))
        self.assertIsNone(_norm2)
        self.assertIn("vocabulary", err2)

    def test_categories_vocabulary(self):
        rec = make_row(raw_text=RAW_PLAIN)
        norm, err = pa.validate_ai_correction(
            rec, self.base_correction(proposed_value=["Subsea"]))
        self.assertIsNone(norm)
        self.assertIn("vocabulary", err)
        _norm2, _err2 = pa.validate_ai_correction(
            rec, self.base_correction(proposed_value=["drifting", "drifting"]))
        self.assertIsNotNone(_norm2)
        self.assertEqual(_norm2["proposed_value"], ["drifting"])  # deduped


class TestGeminiPlumbing(unittest.TestCase):
    def test_extract_json_plain(self):
        self.assertEqual(pa._extract_json('{"a": 1}'), {"a": 1})

    def test_extract_json_fenced(self):
        self.assertEqual(pa._extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_extract_json_embedded(self):
        self.assertEqual(pa._extract_json('Here you go: {"a": 1} — done.'), {"a": 1})

    def test_extract_json_no_json_raises(self):
        with self.assertRaises(pa.GeminiError):
            pa._extract_json("no json here")


# ---------------------------------------------------------------------------
# generate_proposals (model fail-closed, malformed output, happy path)
# ---------------------------------------------------------------------------
class TestGenerateProposals(unittest.TestCase):
    def test_model_not_verified_fails_closed(self):
        client = FakeClient()
        rec = make_row(raw_text=RAW_PLAIN)
        with mock.patch.object(pa, "gemini_verify_model",
                               return_value=(False, "model 'bogus' does not exist")):
            proposals, notes = pa.generate_proposals(
                client, [rec], {rec["id"]: [make_issue(rec, "categories_empty")]},
                "run-1", "bogus", "key", 5, log=quiet)
        self.assertIsNone(proposals)
        self.assertTrue(notes and notes[0].startswith("model_not_verified"))
        self.assertEqual(client.rpc_calls, [])
        self.assertEqual(client.write_attempts, [])

    def test_malformed_gemini_output_is_a_note_not_a_crash(self):
        client = FakeClient()
        rec = make_row(raw_text=RAW_PLAIN)
        with mock.patch.object(pa, "gemini_verify_model", return_value=(True, None)), \
             mock.patch.object(pa, "gemini_generate",
                               side_effect=pa.GeminiError("malformed gemini response (KeyError)")):
            proposals, notes = pa.generate_proposals(
                client, [rec], {rec["id"]: [make_issue(rec, "categories_empty")]},
                "run-1", "gemini-3.8-flash", "key", 5, log=quiet)
        self.assertEqual(proposals, [])
        self.assertTrue(any("AI escalation failed" in n for n in notes))

    def test_happy_path_produces_validated_field_correction(self):
        client = FakeClient()
        rec = make_row(raw_text=RAW_PLAIN, categories=["general"])
        model_out = {"corrections": [self._correction()]}
        with mock.patch.object(pa, "gemini_verify_model", return_value=(True, None)), \
             mock.patch.object(pa, "gemini_generate", return_value=model_out):
            proposals, _notes = pa.generate_proposals(
                client, [rec], {rec["id"]: [make_issue(rec, "categories_out_of_vocabulary")]},
                "run-1", "gemini-3.8-flash", "key", 5, log=quiet)
        self.assertEqual(len(proposals), 1)
        p = proposals[0]
        self.assertEqual(p["type"], "field_correction")
        self.assertEqual(p["field"], "categories")
        self.assertEqual(p["proposed_value"], ["subsea"])
        self.assertEqual(p["model"], "gemini-3.8-flash")
        self.assertTrue(p["requires_human_review"])
        self.assertEqual(p["status"], "proposed")
        self.assertEqual(p["snapshot_updated_at"], rec["updated_at"])
        self.assertEqual(client.rpc_calls, [])
        self.assertEqual(client.write_attempts, [])

    def test_rejected_correction_becomes_note(self):
        client = FakeClient()
        rec = make_row(raw_text=RAW_PLAIN)
        bad = self._correction(evidence_quote="NOT IN TEXT")
        with mock.patch.object(pa, "gemini_verify_model", return_value=(True, None)), \
             mock.patch.object(pa, "gemini_generate", return_value={"corrections": [bad]}):
            proposals, notes = pa.generate_proposals(
                client, [rec], {rec["id"]: [make_issue(rec, "categories_empty")]},
                "run-1", "gemini-3.8-flash", "key", 5, log=quiet)
        self.assertEqual(proposals, [])
        self.assertTrue(any("rejected" in n for n in notes))

    def test_frozen_rows_skip_ai(self):
        client = FakeClient()
        rec = make_row(raw_text=RAW_PLAIN, qa_flags=["verified_by_admin"])
        gen = mock.MagicMock()
        with mock.patch.object(pa, "gemini_verify_model", return_value=(True, None)), \
             mock.patch.object(pa, "gemini_generate", gen):
            proposals, notes = pa.generate_proposals(
                client, [rec], {rec["id"]: [make_issue(rec, "categories_empty")]},
                "run-1", "gemini-3.8-flash", "key", 5, log=quiet)
        gen.assert_not_called()
        self.assertTrue(any("admin-frozen" in n for n in notes))

    def test_ai_cap_reached(self):
        client = FakeClient()
        rec = make_row(raw_text=RAW_PLAIN)
        with mock.patch.object(pa, "gemini_verify_model", return_value=(True, None)):
            proposals, notes = pa.generate_proposals(
                client, [rec], {rec["id"]: [make_issue(rec, "categories_empty")]},
                "run-1", "gemini-3.8-flash", "key", 0, log=quiet)
        self.assertEqual(proposals, [])
        self.assertTrue(any("cap" in n for n in notes))

    def test_geometry_trigger_creates_deterministic_proposal(self):
        client = FakeClient()
        rec = make_row(triage_tier="B", raw_text=RAW_POINT)
        issues = {rec["id"]: [make_issue(rec, "missing_geometry_but_coordinates_in_text")]}
        with mock.patch.object(pa, "gemini_verify_model", return_value=(True, None)), \
             mock.patch.object(pa, "gemini_generate", return_value={"corrections": []}):
            proposals, _notes = pa.generate_proposals(
                client, [rec], issues, "run-1", "gemini-3.8-flash", "key", 5, log=quiet)
        geoms = [p for p in proposals if p["type"] == "geometry_reparse"]
        self.assertEqual(len(geoms), 1)
        self.assertEqual(geoms[0]["source"], "deterministic_parser")
        self.assertIsNone(geoms[0]["model"])

    def _correction(self, **over):
        c = {"field": "categories", "current_value": ["general"],
             "proposed_value": ["subsea"], "evidence_quote": "SUBSEA CABLE",
             "reason": "raw text mentions subsea cable maintenance",
             "confidence": 0.9}
        c.update(over)
        return c


# ---------------------------------------------------------------------------
# apply_approved (the only mode that writes)
# ---------------------------------------------------------------------------
class TestApplyApproved(unittest.TestCase):
    def client_with(self, rec):
        return FakeClient({"nav_warnings": [rec]})

    def test_requires_explicit_confirmation(self):
        client = self.client_with(make_row())
        results, err = pa.apply_approved(
            client, [{"field": "categories", "record_id": "x"}], 50, "run-1", False, log=quiet)
        self.assertEqual(results, [])
        self.assertIn("confirmation", err)
        self.assertEqual(client.rpc_calls, [])

    def test_rejects_non_list_or_empty(self):
        client = self.client_with(make_row())
        for bad in (None, [], "notalist", {}):
            results, err = pa.apply_approved(client, bad, 50, "run-1", True, log=quiet)
            self.assertEqual(results, [])
            self.assertIsNotNone(err)

    def test_non_dict_entry_rejected_not_crash(self):
        client = self.client_with(make_row())
        results, err = pa.apply_approved(client, ["oops", 42], 50, "run-1", True, log=quiet)
        self.assertIsNone(err)
        self.assertEqual([r["status"] for r in results], ["rejected", "rejected"])
        self.assertEqual(client.rpc_calls, [])

    def test_bad_field_rejected(self):
        rec = make_row()
        client = self.client_with(rec)
        p = make_proposal(rec, "status", "cancelled")
        p["field"] = "status"
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "rejected")
        self.assertEqual(client.rpc_calls, [])

    def test_successful_apply_uses_rpc_with_whitelisted_keys(self):
        rec = make_row(categories=["general"], qa_flags=["ingested"])
        client = self.client_with(rec)
        p = make_proposal(rec, "categories", ["subsea"], current=["general"])
        results, err = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertIsNone(err)
        self.assertEqual(results[0]["status"], "applied")
        self.assertEqual(len(client.rpc_calls), 1)
        fn, params = client.rpc_calls[0]
        self.assertEqual(fn, "admin_save_nav_warning")
        self.assertEqual(params["p_warning_id"], rec["id"])
        self.assertEqual(params["p_action"], "AI_CORRECTION_APPLIED")
        self.assertEqual(params["p_update"]["categories"], ["subsea"])
        flags = params["p_update"]["qa_flags"]
        self.assertIn("edited_by_admin", flags)
        self.assertIn("ai_correction_applied", flags)
        self.assertIn("ingested", flags)
        self.assertIsNone(params["p_geometries"])
        self.assertEqual(params["p_expected_updated_at"], rec["updated_at"])
        patch = params["p_diff_patch"]
        self.assertEqual(patch["field"], "categories")
        self.assertEqual(patch["before"], ["general"])
        self.assertEqual(patch["after"], ["subsea"])
        # Whitelist enforcement: lifecycle/source fields must never be touched.
        for forbidden in ("status", "raw_text", "title", "valid_to", "issued_at",
                          "canonical_id", "navarea"):
            self.assertNotIn(forbidden, params["p_update"])

    def test_idempotent_skip_when_value_already_correct(self):
        rec = make_row(categories=["subsea"])
        client = self.client_with(rec)
        p = make_proposal(rec, "categories", ["subsea"], current=["subsea"])
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "already_applied")
        self.assertEqual(client.rpc_calls, [])

    def test_stale_snapshot_skipped(self):
        rec = make_row()
        client = self.client_with(rec)
        p = make_proposal(rec, "categories", ["subsea"],
                          snap="2020-01-01T00:00:00+00:00")
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "skipped_stale")
        self.assertEqual(client.rpc_calls, [])

    def test_current_value_conflict_skipped(self):
        rec = make_row(categories=["drifting"])
        client = self.client_with(rec)
        p = make_proposal(rec, "categories", ["subsea"], current=["general"])
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "skipped_conflict")
        self.assertEqual(client.rpc_calls, [])

    def test_missing_evidence_quote_rejected(self):
        rec = make_row(raw_text=RAW_PLAIN)
        client = self.client_with(rec)
        p = make_proposal(rec, "categories", ["subsea"], quote="NOT IN TEXT ANYMORE")
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "rejected")
        self.assertIn("evidence quote", results[0]["reason"])
        self.assertEqual(client.rpc_calls, [])

    def test_warning_not_found_rejected(self):
        rec = make_row()
        client = self.client_with(rec)
        p = make_proposal(rec, "categories", ["subsea"])
        p["record_id"] = "00000000-0000-4000-8000-00000000dead"
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "rejected")
        self.assertEqual(results[0]["reason"], "WARNING_NOT_FOUND")
        self.assertEqual(client.rpc_calls, [])

    def test_rpc_optimistic_lock_error_is_skipped_stale(self):
        rec = make_row(categories=["general"])
        client = self.client_with(rec)
        client.rpc_errors = [RuntimeError("P0001 STALE_UPDATED_AT: row changed")]
        p = make_proposal(rec, "categories", ["subsea"], current=["general"])
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "skipped_stale")

    def test_rpc_generic_failure_is_recorded_and_continues(self):
        rec1 = make_row(categories=["general"])
        rec2 = make_row(id="00000000-0000-4000-8000-000000000002",
                        canonical_id="NAVAREA XI 002/26", title="OTHER",
                        raw_text="OTHER WARNING.", categories=["general"])
        client = FakeClient({"nav_warnings": [rec1, rec2]})
        client.rpc_errors = [RuntimeError("permission denied for role")]
        p1 = make_proposal(rec1, "categories", ["subsea"], current=["general"])
        p2 = make_proposal(rec2, "categories", ["subsea"], current=["general"])
        results, err = pa.apply_approved(client, [p1, p2], 50, "run-1", True, log=quiet)
        self.assertIsNone(err)
        self.assertEqual(results[0]["status"], "failed")
        self.assertIn("write failed", results[0]["reason"])
        self.assertEqual(results[1]["status"], "applied")

    def test_max_corrections_cap(self):
        rec1 = make_row(categories=["general"])
        rec2 = make_row(id="00000000-0000-4000-8000-000000000002",
                        canonical_id="NAVAREA XI 002/26", title="OTHER",
                        raw_text="OTHER WARNING.", categories=["general"])
        client = FakeClient({"nav_warnings": [rec1, rec2]})
        p1 = make_proposal(rec1, "categories", ["subsea"], current=["general"])
        p2 = make_proposal(rec2, "categories", ["subsea"], current=["general"])
        results, _ = pa.apply_approved(client, [p1, p2], 1, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "applied")
        self.assertEqual(results[1]["status"], "skipped_cap")

    def test_geometry_apply_passes_features_to_rpc(self):
        _c, _lat, _lon, spatial = pa.parse_coordinates(RAW_POINT)
        self.assertIsNotNone(spatial)
        feats = pa.geojson_to_ewkt_features(spatial)
        rec = make_row(triage_tier="B", raw_text=RAW_POINT)
        client = self.client_with(rec)  # spatial views empty -> no stored geometry
        p = make_proposal(rec, "geometry", feats, current=None)
        p["type"] = "geometry_reparse"
        p["proposed_geojson"] = spatial
        p["source"] = "deterministic_parser"
        results, err = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertIsNone(err)
        self.assertEqual(results[0]["status"], "applied")
        self.assertEqual(len(client.rpc_calls), 1)
        fn, params = client.rpc_calls[0]
        self.assertEqual(fn, "admin_save_nav_warning")
        self.assertEqual(params["p_geometries"], feats)
        self.assertEqual(set(params["p_update"].keys()), {"qa_flags"})

    def test_geometry_idempotent_when_view_matches_proposal(self):
        _c, _lat, _lon, spatial = pa.parse_coordinates(RAW_POINT)
        feats = pa.geojson_to_ewkt_features(spatial)
        rec = make_row(triage_tier="B", raw_text=RAW_POINT)
        view_row = {"warning_id": rec["id"], "feature_type": "POINT",
                    "zone_label": None, "buffer_nm": 0, "geojson_blob": spatial}
        client = FakeClient({"nav_warnings": [rec],
                             "nav_warnings_active_spatial": [view_row]})
        p = make_proposal(rec, "geometry", feats, current=None)
        p["proposed_geojson"] = spatial
        results, _ = pa.apply_approved(client, [p], 50, "run-1", True, log=quiet)
        self.assertEqual(results[0]["status"], "already_applied")
        self.assertEqual(client.rpc_calls, [])


# ---------------------------------------------------------------------------
# Orchestration: run_audit, read-only enforcement, reports
# ---------------------------------------------------------------------------
class TestRunAudit(unittest.TestCase):
    def test_complete_audit_of_clean_dataset(self):
        rows = [make_row(), make_row(id="00000000-0000-4000-8000-000000000002",
                                      canonical_id="NAVAREA XI 002/26", title="OTHER",
                                      raw_text="OTHER WARNING."),
                make_row(id="00000000-0000-4000-8000-000000000003",
                         canonical_id="NAVAREA XI 003/26", title="THIRD",
                         raw_text="THIRD WARNING.")]
        client = FakeClient({"nav_warnings": rows})
        audit = pa.run_audit(client, None, None, 2, log=quiet)
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["expected"], 3)
        self.assertEqual(len(audit["rows"]), 3)
        self.assertEqual(audit["issues"], [])
        self.assertTrue(audit["geo_ok"])
        # Read-only enforcement: no RPC and no mutating query in audit mode.
        self.assertEqual(client.rpc_calls, [])
        self.assertEqual(client.write_attempts, [])

    def test_issues_grouped_by_record(self):
        bad = make_row(canonical_id="BA 001/26")
        client = FakeClient({"nav_warnings": [bad, make_row(
            id="00000000-0000-4000-8000-000000000002",
            canonical_id="NAVAREA XI 002/26", title="OTHER",
            raw_text="OTHER WARNING.")]})
        audit = pa.run_audit(client, None, None, 100, log=quiet)
        self.assertEqual(len(audit["issues"]), 1)
        self.assertEqual(audit["issues_by_record"][bad["id"]][0]["code"],
                         "canonical_id_navarea_mismatch")

    def test_spatial_view_failure_degrades_but_audit_stays_complete(self):
        client = FakeClient({"nav_warnings": [make_row()]})
        client.fail_tables = {"nav_warnings_active_spatial",
                              "nav_warnings_unverified_spatial"}
        audit = pa.run_audit(client, None, None, 100, log=quiet)
        self.assertTrue(audit["complete"])
        self.assertFalse(audit["geo_ok"])
        self.assertTrue(any("GeoJSON" in n for n in audit["notes"]))


class TestReports(unittest.TestCase):
    def _audit_stub(self, complete=True, issues=None, rows=None):
        rows = rows if rows is not None else [make_row()]
        return {"rows": rows, "expected": len(rows), "complete": complete,
                "page_errors": 0 if complete else 1, "geo_ok": True,
                "issues": issues or [], "issues_by_record": {}, "notes": []}

    def _write(self, report):
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = pa.write_reports(report, tmp, log=quiet)
            with open(json_path, encoding="utf-8") as f:
                loaded = json.load(f)
            with open(md_path, encoding="utf-8") as f:
                md = f.read()
        return loaded, md

    def test_json_and_markdown_reports(self):
        report = pa.build_report("audit-test", "audit_only", None, None, None,
                                 500, 50, self._audit_stub(), None, [], None, None)
        loaded, md = self._write(report)
        self.assertEqual(loaded["audit_run_id"], "audit-test")
        self.assertEqual(loaded["coverage"]["retrieved_records"], 1)
        self.assertTrue(loaded["coverage"]["complete"])
        self.assertIn("Complete dataset audited: YES", md)
        self.assertNotIn(RAW_PLAIN, md)  # no raw text in the human summary

    def test_incomplete_audit_report_says_partial(self):
        report = pa.build_report("audit-test", "audit_only", None, None, None,
                                 500, 50, self._audit_stub(complete=False),
                                 None, [], None, None)
        loaded, md = self._write(report)
        self.assertFalse(loaded["coverage"]["complete"])
        self.assertIn("NO — partial scan", md)

    def test_proposal_summary_in_report(self):
        rec = make_row(raw_text=RAW_PLAIN)
        proposal = {"field": "categories", "confidence": 0.95,
                    "requires_human_review": True}
        report = pa.build_report("audit-test", "propose_corrections",
                                 "gemini-3.8-flash", None, None, 500, 50,
                                 self._audit_stub(), [proposal], [], None, None)
        loaded, md = self._write(report)
        self.assertEqual(loaded["proposal_summary"]["total"], 1)
        self.assertEqual(loaded["proposal_summary"]["high_confidence"], 1)
        self.assertIn("Correction proposals", md)

    def test_apply_summary_in_report(self):
        apply_results = [{"canonical_id": "NAVAREA XI 001/26", "field": "categories",
                          "status": "applied", "reason": None}]
        report = pa.build_report("audit-test", "apply_approved",
                                 "gemini-3.8-flash", None, None, 500, 50,
                                 self._audit_stub(), None, [], apply_results, None)
        loaded, md = self._write(report)
        self.assertEqual(loaded["apply_summary"]["by_status"], {"applied": 1})
        self.assertIn("Applied corrections", md)


class TestMisc(unittest.TestCase):
    def test_pid_deterministic(self):
        a = pa._pid("run", "rec", "categories", ["subsea"])
        b = pa._pid("run", "rec", "categories", ["subsea"])
        c = pa._pid("run", "rec", "categories", ["drifting"])
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_normalize_flags(self):
        self.assertEqual(pa._normalize_flags(None), [])
        self.assertEqual(pa._normalize_flags(["a", 1, "b"]), ["a", "b"])
        self.assertEqual(pa._normalize_flags('["x", "y"]'), ["x", "y"])
        self.assertEqual(pa._normalize_flags("not-json"), [])


if __name__ == "__main__":
    unittest.main()
