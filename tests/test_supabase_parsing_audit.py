#!/usr/bin/env python3
"""
tests/test_supabase_parsing_audit.py — Unit Tests for Supabase Parsing Audit & AI Correction Engine

Covers:
  - Keyset pagination (id > last_id) across multiple pages.
  - Midway pagination failure marking run as partial/incomplete.
  - Deterministic validation of coordinates, missing hemispheres, and Tier A invariants.
  - Malformed GeoJSON and geometry validation.
  - Safe Gemini handling on malformed JSON or model failure.
  - Audit-only mode ensuring zero database mutations and zero Gemini calls.
  - Proposal generation mode creating proposals without altering nav_warnings.
  - Apply mode requiring explicit approval status.
  - Optimistic concurrency conflict detection (stale proposal marking).
  - Duplicate apply is a safe no-op.
  - Non-UUID proposal IDs rejected without any database query.
  - Geometry fields blocked by the allowlist.
  - Two overlapping applies change the row only once.
  - Geometry validation and preservation of historical/inactive warnings.
  - Apply goes through the admin_save_nav_warning RPC (atomic audit row, freeze
    flags, optimistic lock) and never a direct nav_warnings update.
  - audit_only makes ZERO database writes of any kind (no run-ledger row).
  - Allowlist enforcement: title/dates are not AI-correctable.
  - Model verification fail-closed: unknown model aborts (exit 3) before any write.
  - Gemini rate control: only AI-fixable records are assessed, hard-capped and
    throttled; a 429 stops the AI pass and never retries through the REST fallback.
"""

from datetime import datetime, timezone
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Keep the suite fast: the real throttle (default AUDIT_AI_MAX_RPM=10, i.e. one
# 6-second gap between Gemini calls) must not run inside unit tests. The
# dedicated throttle test overrides AI_MAX_RPM and mocks time itself.
os.environ.setdefault("AUDIT_AI_MAX_RPM", "1000000")

from scripts import audit_supabase_parsing
from scripts.audit_supabase_parsing import (
    GeminiRateLimited,
    GeminiUnavailable,
    GeometryFetchError,
    GeometrySchemaError,
    fetch_all_warnings,
    fetch_geometries_for_warnings,
    validate_warning_record,
    validate_warning_geometry,
    assess_warning_with_gemini,
    create_correction_proposals,
    apply_approved_corrections,
    run_audit,
    _throttle,
)


class MockResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class MockTableQueryBuilder:
    def __init__(self, table_name: str, client: "MockSupabaseClient"):
        self.table_name = table_name
        self.client = client
        self._action = "select"
        self._select_cols = "*"
        self._filters = {}
        self._gt_filters = {}
        self._is_filters = {}
        self._limit = 999999
        self._order_by = None
        self._in_filters = {}
        self._update_patch = None
        self._insert_payload = None
        self._count = None

    def select(self, cols="*", count=None):
        self._action = "select"
        self._select_cols = cols
        self._count = count
        return self

    def order(self, col):
        self._order_by = col
        return self

    def limit(self, count):
        self._limit = count
        return self

    def range(self, start, end):
        self._limit = end - start + 1
        return self

    def gt(self, col, val):
        self._gt_filters[col] = val
        return self

    def is_(self, col, val):
        self._is_filters[col] = val
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, values):
        self._in_filters[col] = values
        return self

    def insert(self, payload):
        self._action = "insert"
        self._insert_payload = payload if isinstance(payload, list) else [payload]
        return self

    def update(self, patch):
        self._action = "update"
        self._update_patch = patch
        return self

    def execute(self):
        self.client.query_history.append({
            "table": self.table_name,
            "action": self._action,
            "filters": dict(self._filters),
            "gt_filters": dict(self._gt_filters),
            "is_filters": dict(self._is_filters),
            "patch": dict(self._update_patch) if self._update_patch else None
        })

        if self._action == "select":
            if self.table_name in self.client.fail_on_select_tables:
                raise RuntimeError("Simulated geometry fetch failure")
            rows = self.client.tables.get(self.table_name, [])
            if self._order_by:
                rows = sorted(rows, key=lambda x: str(x.get(self._order_by, "")))

            filtered = []
            for r in rows:
                match = True
                for k, v in self._filters.items():
                    if r.get(k) != v:
                        match = False
                        break
                for k, v in self._gt_filters.items():
                    if str(r.get(k, "")) <= str(v):
                        match = False
                        break
                for k, v in self._is_filters.items():
                    if v == "null" and r.get(k) is not None:
                        match = False
                        break
                for k, vals in self._in_filters.items():
                    if r.get(k) not in vals:
                        match = False
                        break
                if match:
                    filtered.append(r)

            sliced = filtered[:self._limit]

            # WP2: emulate PostgREST count="exact". count_overrides[table] is
            # either a list (consumed in order, simulating counts that differ
            # from the actual rows) or an int; default is the true row count.
            if self._count is not None:
                if self.client.fail_on_count:
                    raise RuntimeError("Simulated count query failure")
                override = self.client.count_overrides.get(self.table_name)
                if isinstance(override, list):
                    value = override.pop(0) if override else len(sliced)
                else:
                    value = override if override is not None else len(sliced)
                return MockResult(sliced, count=int(value))

            return MockResult(sliced)

        elif self._action == "insert":
            if self.client.fail_on_insert:
                raise RuntimeError("Simulated DB insert failure")
            target_list = self.client.tables.setdefault(self.table_name, [])
            inserted = []
            for item in self._insert_payload:
                row = dict(item)
                if "id" not in row:
                    row["id"] = f"gen-{len(target_list) + 1}"
                target_list.append(row)
                inserted.append(row)
                self.client.recorded_inserts.setdefault(self.table_name, []).append(row)
            return MockResult(inserted)

        elif self._action == "update":
            if self.client.fail_on_update:
                raise RuntimeError("Simulated DB update failure")
            target_list = self.client.tables.get(self.table_name, [])
            updated = []
            for r in target_list:
                match = True
                for k, v in self._filters.items():
                    if isinstance(v, (dict, list)) or isinstance(r.get(k), (dict, list)):
                        if json.dumps(r.get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
                            match = False
                            break
                    elif r.get(k) != v:
                        match = False
                        break
                for k, v in self._is_filters.items():
                    if v == "null" and r.get(k) is not None:
                        match = False
                        break
                if match:
                    r.update(self._update_patch)
                    updated.append(dict(r))
                    self.client.recorded_updates.setdefault(self.table_name, []).append({
                        "filter": dict(self._filters),
                        "patch": dict(self._update_patch)
                    })
            return MockResult(updated)

        return MockResult([])


class MockSupabaseClient:
    def __init__(self, initial_tables=None):
        self.tables = initial_tables or {}
        self.recorded_inserts = {}
        self.recorded_updates = {}
        self.recorded_rpcs = []
        self.query_history = []
        self.fail_on_insert = False
        self.fail_on_update = False
        self.count_overrides = {}
        self.fail_on_count = False
        self.fail_on_select_tables = set()

    def table(self, table_name):
        return MockTableQueryBuilder(table_name, self)

    def rpc(self, fn: str, params: dict = None):
        """Minimal emulation of PostgREST rpc(). Implements the
        admin_save_nav_warning contract: optimistic lock, whitelisted
        p_update fields, atomic nav_warning_audits row."""
        return MockRpcCall(self, fn, params or {})


class MockRpcCall:
    def __init__(self, client: "MockSupabaseClient", fn: str, params: dict):
        self.client = client
        self.fn = fn
        self.params = params

    def execute(self):
        client, params, fn = self.client, self.params, self.fn
        client.recorded_rpcs.append({"fn": fn, "params": params})
        if fn != "admin_save_nav_warning":
            raise RuntimeError(f"Unexpected RPC '{fn}'")

        target = None
        for r in client.tables.get("nav_warnings", []):
            if r.get("id") == params.get("p_warning_id"):
                target = r
                break
        if target is None:
            raise RuntimeError("WARNING_NOT_FOUND")

        expected = params.get("p_expected_updated_at")
        if expected is not None and target.get("updated_at") != expected:
            raise RuntimeError("STALE_UPDATED_AT")

        for k, v in (params.get("p_update") or {}).items():
            target[k] = v
        target["updated_at"] = "rpc-now"

        # Atomic audit row in the SAME transaction
        client.tables.setdefault("nav_warning_audits", []).append({
            "warning_id": params.get("p_warning_id"),
            "operator_id": params.get("p_operator"),
            "action": params.get("p_action"),
            "diff_patch": params.get("p_diff_patch"),
        })
        return MockResult([{"warning": dict(target), "geometry": "unchanged"}])


class TestSupabaseParsingAudit(unittest.TestCase):

    def setUp(self):
        self.sample_active_warning = {
            "id": "11111111-1111-1111-1111-111111111111",
            "canonical_id": "NAVAREA IV 1042/26",
            "navarea": "IV",
            "title": "GULF OF MEXICO. DRILLING RIG OPERATIONS.",
            "area_text": "GULF OF MEXICO",
            "raw_text": "NAVAREA IV 1042/26\nGULF OF MEXICO.\nDRILLING RIG AT 27-45.0N 091-15.0W. WIDE BERTH REQUESTED.",
            "status": "active",
            "triage_tier": "A",
            "data_quality": "EXPLICIT",
            "parsing_method": "RULE",
            "unplotted_reason": None,
            "valid_from": "2026-10-20T12:00:00Z",
            "valid_to": "2026-10-30T12:00:00Z",
            "categories": ["offshore"],
            "qa_flags": [],
            "updated_at": "2026-10-26T00:00:00Z",
        }

        self.sample_geometry = {
            "geom_id": "22222222-2222-2222-2222-222222222222",
            "warning_id": "11111111-1111-1111-1111-111111111111",
            "zone_label": "Centroid",
            "feature_type": "POINT",
            "geojson": {
                "type": "Point",
                "coordinates": [-91.25, 27.75]
            }
        }

    # 1. Multiple database pages test using keyset pagination
    def test_pagination_multiple_pages(self):
        rows = []
        for i in range(15):
            rows.append({
                "id": f"00000000-0000-0000-0000-{i:012d}",
                "canonical_id": f"NAVAREA I {i+1}/26",
                "navarea": "I",
                "status": "active",
                "raw_text": f"NAVAREA I {i+1}/26 TEST",
            })
        client = MockSupabaseClient({"nav_warnings": rows})

        warnings, is_complete, err = fetch_all_warnings(client, batch_size=5)
        self.assertTrue(is_complete)
        self.assertIsNone(err)
        self.assertEqual(len(warnings), 15)
        # Verify every record was examined exactly once
        ids = [w["canonical_id"] for w in warnings]
        self.assertEqual(len(set(ids)), 15)

    # 2. Query failure midway through keyset pagination
    def test_pagination_failure_midway_marks_incomplete(self):
        client = MagicMock()
        first_page = MockResult([{"id": "00000000-0000-0000-0000-000000000001", "canonical_id": "NA I 1/26"}])

        query_mock = MagicMock()
        query_mock.order.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.gt.return_value = query_mock
        # First call succeeds with 1 item, second call raises DB connection error
        query_mock.execute.side_effect = [
            first_page,
            RuntimeError("Database connection lost"),
        ]
        client.table.return_value.select.return_value = query_mock

        warnings, is_complete, err = fetch_all_warnings(client, batch_size=1)
        self.assertFalse(is_complete)
        self.assertIsNotNone(err)
        self.assertIn("Database connection lost", err)
        self.assertEqual(len(warnings), 1)

    # 3. Invalid coordinate reported; no invented replacement
    def test_invalid_coordinate_validation(self):
        record = dict(self.sample_active_warning)
        bad_geom = {
            "geom_id": "g-bad",
            "warning_id": record["id"],
            "feature_type": "POINT",
            "geojson": {
                "type": "Point",
                "coordinates": [-91.25, 95.0]
            }
        }
        issues = validate_warning_geometry(record, [bad_geom])
        self.assertTrue(any(iss["code"] == "COORDINATE_OUT_OF_BOUNDS" for iss in issues))

    # 4. Missing hemisphere requires review (unresolved)
    def test_missing_hemisphere_flagged_unresolved(self):
        record = dict(self.sample_active_warning)
        record["raw_text"] = "KATTEGAT. SUBSEA HAZARD AT 57-12.0 011-30.0. WIDE BERTH."
        issues = validate_warning_record(record)
        self.assertTrue(any(iss["code"] == "MISSING_HEMISPHERE_UNRESOLVED" for iss in issues))

    # 5. Malformed GeoJSON rejected
    def test_malformed_geojson_rejected(self):
        record = dict(self.sample_active_warning)
        bad_geom = {
            "geom_id": "g-bad",
            "warning_id": record["id"],
            "feature_type": "POLYGON",
            "geojson": {
                "type": "Polygon",
                "coordinates": [
                    [[-91.0, 27.0], [-91.0, 28.0], [-90.0, 28.0]] # Unclosed, only 3 points
                ]
            }
        }
        issues = validate_warning_geometry(record, [bad_geom])
        self.assertTrue(
            any(iss["code"] in ("POLYGON_UNDERSIZED_RING", "POLYGON_UNCLOSED_RING") for iss in issues)
        )

    # 6. Gemini returns malformed JSON - fails safely without crashing
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_gemini_malformed_json_fails_safely(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{
                "content": {"parts": [{"text": "THIS IS NOT JSON AT ALL"}]}
            }]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        proposals = assess_warning_with_gemini(
            self.sample_active_warning,
            model_name="gemini-3.8-flash",
            issues=[{"code": "TEST_ISSUE"}]
        )
        self.assertEqual(proposals, [])

    # 7. Gemini unavailable / connection error: no response could be
    # obtained, so the record is UNASSESSED — GeminiUnavailable (change B),
    # never a silent empty-proposal success.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen", side_effect=RuntimeError("503 Service Unavailable"))
    def test_gemini_unavailable_fails_safely(self, mock_urlopen):
        with self.assertRaises(GeminiUnavailable):
            assess_warning_with_gemini(
                self.sample_active_warning,
                model_name="gemini-3.8-flash",
                issues=[{"code": "TEST_ISSUE"}]
            )

    # 8. Audit-only mode ensures ZERO mutations and ZERO Gemini calls
    @patch("scripts.audit_supabase_parsing.assess_warning_with_gemini")
    def test_audit_only_mode_zero_mutations(self, mock_gemini):
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "nav_warning_geometries": [dict(self.sample_geometry)],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            report = run_audit(mode="audit_only", client=client, report_dir=tmp_dir)
        self.assertEqual(report["mode"], "audit_only")
        # In audit_only, nav_warnings should have zero recorded updates
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)
        # Proposals table should have zero inserts
        self.assertEqual(len(client.recorded_inserts.get("parsing_correction_proposals", [])), 0)
        # audit_only is fully read-only: no run-ledger row, no RPC, no inserts at all
        self.assertEqual(len(client.recorded_inserts.get("parsing_audit_runs", [])), 0)
        self.assertEqual(len(client.recorded_inserts), 0)
        self.assertEqual(len(client.recorded_rpcs), 0)
        self.assertIsNone(report.get("audit_run_id"))
        # Gemini assessment must NOT be called in audit_only
        mock_gemini.assert_not_called()

    # 9. Proposal mode: proposal stored, warning UNCHANGED
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_proposal_mode_creates_pending_proposal_without_modifying_warning(self, mock_urlopen):
        raw_snippet = "GULF OF MEXICO"
        llm_output = json.dumps([{
            "canonical_id": self.sample_active_warning["canonical_id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",
            "proposed_value": "EXPLICIT",
            "raw_evidence": raw_snippet,
            "explanation": "Coordinates are explicitly stated in the bulletin",
            "confidence": 0.95,
            "requires_review": True
        }])

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{
                "content": {"parts": [{"text": llm_output}]}
            }]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        rec = dict(self.sample_active_warning)
        rec["unplotted_reason"] = "no_coordinates"

        client = MockSupabaseClient({
            "nav_warnings": [rec],
            "nav_warning_geometries": [dict(self.sample_geometry)],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            report = run_audit(mode="propose_corrections", client=client, report_dir=tmp_dir)

        # Warnings must NOT have been updated
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)
        # Proposals table must contain the proposal with status='pending'
        proposals = client.tables.get("parsing_correction_proposals", [])
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["status"], "pending")
        self.assertEqual(proposals[0]["field_name"], "data_quality")

    # 10. Proposal not approved: apply is REJECTED
    def test_apply_rejected_if_not_approved(self):
        proposal = {
            "id": "33333333-3333-3333-3333-333333333333",
            "status": "pending",  # NOT approved
            "warning_record_id": self.sample_active_warning["id"],
            "field_name": "title",
            "original_value": "Old Title",
            "proposed_value": "New Title",
            "raw_evidence": "GULF OF MEXICO",
        }
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "parsing_correction_proposals": [proposal],
        })

        res = apply_approved_corrections(client, [proposal["id"]])
        self.assertEqual(len(res["rejected"]), 1)
        self.assertEqual(len(res["applied"]), 0)
        # Ensure warning was not updated
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)

    # 11. Optimistic concurrency: original value changed marks proposal STALE
    def test_apply_marks_stale_when_db_value_changed(self):
        current_warn = dict(self.sample_active_warning)
        current_warn["data_quality"] = "AMBIGUOUS"  # changed concurrently

        proposal = {
            "id": "44444444-4444-4444-4444-444444444444",
            "status": "approved",
            "warning_record_id": current_warn["id"],
            "field_name": "data_quality",
            "original_value": "EXPLICIT",  # Does not match DB!
            "proposed_value": "INVALID",
            "raw_evidence": "GULF OF MEXICO",
        }
        client = MockSupabaseClient({
            "nav_warnings": [current_warn],
            "parsing_correction_proposals": [proposal],
        })

        res = apply_approved_corrections(client, [proposal["id"]])
        self.assertEqual(len(res["stale"]), 1)
        self.assertEqual(len(res["applied"]), 0)
        self.assertEqual(proposal["status"], "stale")
        # No RPC, no direct update was issued
        self.assertEqual(len(client.recorded_rpcs), 0)
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)

    # 12. Successful apply goes through admin_save_nav_warning (RPC) with audit row
    def test_apply_approved_success(self):
        current_warn = dict(self.sample_active_warning)
        current_warn["data_quality"] = "AMBIGUOUS"

        proposal = {
            "id": "55555555-5555-5555-5555-555555555555",
            "status": "approved",
            "canonical_id": current_warn["canonical_id"],
            "warning_record_id": current_warn["id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",
            "proposed_value": "EXPLICIT",
            "raw_evidence": "DRILLING RIG AT 27-45.0N 091-15.0W",
        }
        client = MockSupabaseClient({
            "nav_warnings": [current_warn],
            "parsing_correction_proposals": [proposal],
        })

        res = apply_approved_corrections(client, [proposal["id"]])
        self.assertEqual(len(res["applied"]), 1)
        self.assertEqual(proposal["status"], "applied")
        self.assertEqual(current_warn["data_quality"], "EXPLICIT")
        # The write MUST go through the RPC, never a direct table update
        self.assertEqual(len(client.recorded_rpcs), 1)
        self.assertEqual(client.recorded_rpcs[0]["fn"], "admin_save_nav_warning")
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)
        # An atomic nav_warning_audits row must exist in the same transaction
        audits = client.tables.get("nav_warning_audits", [])
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["action"], "AI_CORRECTION_APPLIED")
        self.assertEqual(audits[0]["operator_id"], "supabase-parsing-audit")
        # Freeze flags appended so the scraper overwrite guard keeps the correction
        self.assertIn("edited_by_admin", current_warn["qa_flags"])
        self.assertIn("ai_correction_applied", current_warn["qa_flags"])

    # 12b. Allowlist enforcement: title/dates are NOT AI-correctable
    def test_apply_rejects_non_allowlisted_field(self):
        proposal = {
            "id": "55555555-5555-5555-5555-555555555556",
            "status": "approved",
            "warning_record_id": self.sample_active_warning["id"],
            "field_name": "title",
            "original_value": "OLD TITLE",
            "proposed_value": "AI-PROPOSED TITLE",
            "raw_evidence": "GULF OF MEXICO",
        }
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "parsing_correction_proposals": [proposal],
        })

        res = apply_approved_corrections(client, [proposal["id"]])
        self.assertEqual(len(res["applied"]), 0)
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(proposal["status"], "failed")
        self.assertIn("allowlist", str(proposal.get("error_message", "")))
        self.assertEqual(len(client.recorded_rpcs), 0)

    # 12c. Model verification is fail-closed: unknown model aborts before any DB write
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_propose_mode_fails_closed_on_unknown_model(self, mock_urlopen):
        import io
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "https://api", 404, "Not Found", None, io.BytesIO(b"{}")
        )
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "nav_warning_geometries": [dict(self.sample_geometry)],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(SystemExit) as ctx:
                run_audit(
                    mode="propose_corrections", client=client, report_dir=tmp_dir,
                    model_name="gemini-9.9-nonexistent",
                )
        self.assertEqual(ctx.exception.code, 3)
        # Fail-closed: no ledger row, no inserts, no writes at all
        self.assertEqual(len(client.recorded_inserts.get("parsing_audit_runs", [])), 0)
        self.assertEqual(len(client.recorded_rpcs), 0)

    # 13. Historical/inactive warning remains preserved
    def test_historical_warning_preserved(self):
        cancelled_warn = dict(self.sample_active_warning)
        cancelled_warn["status"] = "cancelled"
        cancelled_warn["id"] = "99999999-9999-9999-9999-999999999999"

        client = MockSupabaseClient({
            "nav_warnings": [cancelled_warn],
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            report = run_audit(mode="audit_only", client=client, report_dir=tmp_dir)
        self.assertEqual(cancelled_warn["status"], "cancelled")
        self.assertEqual(report["examined_count"], 1)

    # 14. Tier A Invariant violation detection
    def test_tier_a_invariant_violations_flagged(self):
        bad_record = dict(self.sample_active_warning)
        bad_record["triage_tier"] = "A"
        bad_record["data_quality"] = "INFERRED"
        bad_record["unplotted_reason"] = "no_valid_geometry"

        issues = validate_warning_record(bad_record)
        invariants = [iss for iss in issues if iss["code"] == "TIER_A_INVARIANT_VIOLATION"]
        self.assertGreaterEqual(len(invariants), 2)

    # 15. NEW TEST: duplicate apply is a no-op
    def test_duplicate_apply_is_noop(self):
        current_warn = dict(self.sample_active_warning)
        current_warn["data_quality"] = "AMBIGUOUS"
        prop_id = "66666666-6666-6666-6666-666666666666"
        proposal = {
            "id": prop_id,
            "status": "approved",
            "canonical_id": current_warn["canonical_id"],
            "warning_record_id": current_warn["id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",
            "proposed_value": "EXPLICIT",
            "raw_evidence": "DRILLING RIG AT 27-45.0N 091-15.0W",
        }
        client = MockSupabaseClient({
            "nav_warnings": [current_warn],
            "parsing_correction_proposals": [proposal],
        })

        # First apply succeeds
        res1 = apply_approved_corrections(client, [prop_id])
        self.assertEqual(len(res1["applied"]), 1)
        self.assertEqual(proposal["status"], "applied")
        initial_rpcs = len(client.recorded_rpcs)

        # Second apply on the exact same proposal ID must be a no-op
        res2 = apply_approved_corrections(client, [prop_id])
        self.assertEqual(len(res2["applied"]), 0)
        self.assertEqual(len(res2["rejected"]), 1)
        # Ensure no additional RPC write was issued
        self.assertEqual(len(client.recorded_rpcs), initial_rpcs)

    # 16. NEW TEST: non-UUID IDs rejected without a DB call
    def test_non_uuid_proposal_id_rejected_without_db_call(self):
        client = MockSupabaseClient({
            "nav_warnings": [],
            "parsing_correction_proposals": [],
        })
        bad_ids = ["not-a-valid-uuid", "12345", "'; DROP TABLE nav_warnings;--", ""]
        res = apply_approved_corrections(client, bad_ids)
        self.assertEqual(len(res["failed"]), 3) # Non-empty bad IDs
        self.assertEqual(len(res["applied"]), 0)
        # Verify no database queries were issued to parsing_correction_proposals
        proposal_queries = [q for q in client.query_history if q["table"] == "parsing_correction_proposals"]
        self.assertEqual(len(proposal_queries), 0)

    # 17. NEW TEST: geometry fields blocked by the allowlist
    def test_geometry_fields_blocked_by_allowlist(self):
        prop_id = "77777777-7777-7777-7777-777777777777"
        proposal = {
            "id": prop_id,
            "status": "approved",
            "canonical_id": self.sample_active_warning["canonical_id"],
            "warning_record_id": self.sample_active_warning["id"],
            "field_name": "spatial",  # Geometry field NOT in allowlist
            "original_value": None,
            "proposed_value": {"type": "Point", "coordinates": [-90.0, 25.0]},
            "raw_evidence": "GULF OF MEXICO",
        }
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "parsing_correction_proposals": [proposal],
        })

        res = apply_approved_corrections(client, [prop_id])
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(len(res["applied"]), 0)
        self.assertIn("not in allowlist", res["failed"][0]["reason"])
        self.assertEqual(proposal["status"], "failed")
        # Ensure nav_warnings was not updated
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)

    # 18. NEW TEST: two overlapping applies change the row once
    def test_two_overlapping_applies_change_row_once(self):
        current_warn = dict(self.sample_active_warning)
        current_warn["data_quality"] = "AMBIGUOUS"
        prop1_id = "88888888-8888-8888-8888-888888888881"
        prop2_id = "88888888-8888-8888-8888-888888888882"
        # Both proposals target the same original data_quality concurrently
        proposal1 = {
            "id": prop1_id,
            "status": "approved",
            "canonical_id": current_warn["canonical_id"],
            "warning_record_id": current_warn["id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",
            "proposed_value": "EXPLICIT",
            "raw_evidence": "DRILLING RIG AT 27-45.0N 091-15.0W",
        }
        proposal2 = {
            "id": prop2_id,
            "status": "approved",
            "canonical_id": current_warn["canonical_id"],
            "warning_record_id": current_warn["id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",
            "proposed_value": "INVALID",
            "raw_evidence": "DRILLING RIG AT 27-45.0N 091-15.0W",
        }
        client = MockSupabaseClient({
            "nav_warnings": [current_warn],
            "parsing_correction_proposals": [proposal1, proposal2],
        })

        # Apply both proposals sequentially in one batch
        res = apply_approved_corrections(client, [prop1_id, prop2_id])
        # First proposal succeeds
        self.assertEqual(len(res["applied"]), 1)
        self.assertEqual(res["applied"][0]["proposal_id"], prop1_id)
        # Second proposal is detected as stale because DB was updated by proposal1
        self.assertEqual(len(res["stale"]), 1)
        self.assertEqual(res["stale"][0]["proposal_id"], prop2_id)
        # Warning row reflects proposal1 and was never overwritten by proposal2
        self.assertEqual(current_warn["data_quality"], "EXPLICIT")
        # Exactly one RPC write was made; no direct updates at all
        self.assertEqual(len(client.recorded_rpcs), 1)
        self.assertEqual(len(client.recorded_updates.get("nav_warnings", [])), 0)


    # 19. If the row already has the proposed value, mark proposal applied without writing
    def test_apply_marks_applied_when_row_already_has_proposed_value(self):
        current_warn = dict(self.sample_active_warning)
        # Warning already has the proposed data_quality in the DB
        current_warn["data_quality"] = "EXPLICIT"

        prop_id = "99999999-9999-9999-9999-999999999991"
        proposal = {
            "id": prop_id,
            "status": "approved",
            "canonical_id": current_warn["canonical_id"],
            "warning_record_id": current_warn["id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",  # Stale snapshot: field already moved on
            "proposed_value": "EXPLICIT",
            "raw_evidence": "DRILLING RIG AT 27-45.0N 091-15.0W",
        }
        client = MockSupabaseClient({
            "nav_warnings": [current_warn],
            "parsing_correction_proposals": [proposal],
        })

        res = apply_approved_corrections(client, [prop_id])
        self.assertEqual(len(res["applied"]), 1)
        self.assertEqual(proposal["status"], "applied")
        self.assertIsNotNone(proposal.get("applied_at"))
        # Idempotent: no RPC write was issued for an already-correct value
        self.assertEqual(len(client.recorded_rpcs), 0)


    # 20. Geometry fetch consumes the geom_geojson computed column (real
    # schema has no geojson column; geometry lives in PostGIS geom_postgis).
    # The select must use NO function-call syntax: st_asgeojson(geom_postgis)
    # trips PGRST200 in PostgREST.
    def test_geometry_fetch_accepts_geom_geojson_computed_key(self):
        self.assertIn("geom_geojson", audit_supabase_parsing.GEOMETRY_SELECT_COLS)
        self.assertNotIn("st_asgeojson(", audit_supabase_parsing.GEOMETRY_SELECT_COLS)
        geom_row = {
            "warning_id": self.sample_active_warning["id"],
            "zone_label": "Centroid",
            "feature_type": "POINT",
            "geom_geojson": {
                "type": "Point",
                "coordinates": [-91.25, 95.0]  # out of bounds on purpose
            },
        }
        client = MockSupabaseClient({"nav_warning_geometries": [geom_row]})
        geoms = fetch_geometries_for_warnings(client, [self.sample_active_warning["id"]])
        self.assertEqual(len(geoms[self.sample_active_warning["id"]]), 1)
        # The validator must consume the geom_geojson payload
        issues = validate_warning_geometry(
            dict(self.sample_active_warning),
            geoms[self.sample_active_warning["id"]],
        )
        self.assertTrue(any(iss["code"] == "COORDINATE_OUT_OF_BOUNDS" for iss in issues))

    # 21. Geometry rows without any GeoJSON payload key fail loudly instead of
    # letting every geometry check silently no-op.
    def test_geometry_fetch_fails_loudly_without_geojson_key(self):
        geom_row = {
            "warning_id": self.sample_active_warning["id"],
            "zone_label": "Centroid",
            "feature_type": "POINT",
            "geom_postgis": "0101000000000000000000F03F",  # raw WKB hex, no payload
        }
        client = MockSupabaseClient({"nav_warning_geometries": [geom_row]})
        with self.assertRaises(GeometrySchemaError):
            fetch_geometries_for_warnings(client, [self.sample_active_warning["id"]])

    # 21b. Missing payload key on a NON-first row aborts too: the schema guard
    # checks every fetched row, not just the first one.
    def test_geometry_fetch_fails_loudly_when_non_first_row_lacks_key(self):
        good_row = {
            "warning_id": self.sample_active_warning["id"],
            "zone_label": "Centroid",
            "feature_type": "POINT",
            "geom_geojson": {"type": "Point", "coordinates": [-91.25, 27.75]},
        }
        bad_row = {
            "warning_id": self.sample_active_warning["id"],
            "zone_label": "Area A",
            "feature_type": "POLYGON",
            "geom_postgis": "010600000000000000",  # raw hex, no payload key
        }
        client = MockSupabaseClient({"nav_warning_geometries": [good_row, bad_row]})
        with self.assertRaises(GeometrySchemaError):
            fetch_geometries_for_warnings(client, [self.sample_active_warning["id"]])

    # 21c. A null geometry payload is FLAGGED (needs review), never skipped,
    # never defaulted: no clamping, no reprojection, no coordinate edits.
    def test_null_geometry_payload_flagged_not_skipped(self):
        null_geom = {
            "geom_id": "g-null",
            "warning_id": self.sample_active_warning["id"],
            "zone_label": "Centroid",
            "feature_type": "POINT",
            "geom_geojson": None,
        }
        client = MockSupabaseClient({"nav_warning_geometries": [null_geom]})
        geoms = fetch_geometries_for_warnings(client, [self.sample_active_warning["id"]])
        self.assertEqual(len(geoms[self.sample_active_warning["id"]]), 1)
        issues = validate_warning_geometry(
            dict(self.sample_active_warning),
            geoms[self.sample_active_warning["id"]],
        )
        self.assertTrue(any(iss["code"] == "MISSING_GEOMETRY_PAYLOAD" for iss in issues))
        payload_issue = next(
            iss for iss in issues if iss["code"] == "MISSING_GEOMETRY_PAYLOAD"
        )
        self.assertEqual(payload_issue["severity"], "ERROR")

    # 21d. A geometry fetch abort inside run_audit must produce
    # status=failed AND scan_complete=False — never both failed and complete.
    def test_run_audit_geometry_abort_forces_scan_complete_false(self):
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "nav_warning_geometries": [dict(self.sample_geometry)],
        })
        client.fail_on_select_tables = {"nav_warning_geometries"}
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = run_audit(mode="audit_only", client=client, report_dir=tmp_dir)
        self.assertEqual(res["status"], "failed")
        self.assertFalse(res["scan_complete"])
        self.assertIn("Geometry batch fetch failed", str(res.get("error")))

    # 22. Legacy geojson key still honored (backwards compatibility of the lookup)
    def test_validator_still_accepts_legacy_geojson_key(self):
        record = dict(self.sample_active_warning)
        legacy_geom = {
            "geom_id": "g-legacy",
            "warning_id": record["id"],
            "feature_type": "POINT",
            "geojson": {
                "type": "Point",
                "coordinates": [-91.25, 95.0]
            }
        }
        issues = validate_warning_geometry(record, [legacy_geom])
        self.assertTrue(any(iss["code"] == "COORDINATE_OUT_OF_BOUNDS" for iss in issues))


    # 23. WP1 (report schema v2): every v1 key still present, new sections exist
    def test_report_v2_backward_compatible(self):
        client = MockSupabaseClient({
            "nav_warnings": [dict(self.sample_active_warning)],
            "nav_warning_geometries": [dict(self.sample_geometry)],
        })
        res = run_audit(mode="audit_only", client=client, report_dir=tempfile.mkdtemp())
        v1_keys = [
            "audit_run_id", "mode", "navarea_filter", "model_name", "started_at",
            "scan_complete", "examined_count", "issue_count", "proposal_count",
            "applied_count", "failed_count", "issues", "proposals", "apply_summary",
            "completed_at", "status",
        ]
        for key in v1_keys:
            self.assertIn(key, res, f"v1 key {key!r} missing from v2 report")
        self.assertEqual(res["report_version"], 2)
        # New sections exist and are empty at first (populated by WP2-WP4)
        self.assertIn("coverage", res)
        # WP2 populates coverage.
        self.assertEqual(res["coverage"]["scan_status"], "complete")
        # Change D: failures/issue_summary are now populated from data the
        # run already collected — {} only when nothing actually failed.
        self.assertIn("failures", res)
        self.assertEqual(res["failures"], {"ai": {}})
        self.assertIn("issue_summary", res)
        self.assertEqual(res["issue_summary"]["total"], res["issue_count"])
        self.assertEqual(sum(res["issue_summary"]["by_code"].values()),
                         res["issue_count"])
        self.assertIn("records_with_issues", res["issue_summary"])
        self.assertIn("limitations", res)
        self.assertEqual(res["limitations"], [])

    # 24. WP2: exactly batch_size rows is the pagination boundary — still complete
    def test_coverage_boundary_exact_batch_size(self):
        rows = []
        for i in range(5):
            row = dict(self.sample_active_warning)
            row["id"] = f"00000000-0000-0000-0000-{i:012d}"
            row["canonical_id"] = f"NAVAREA I {i + 1}/26"
            row["status"] = "active"
            rows.append(row)
        client = MockSupabaseClient({"nav_warnings": rows})
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = run_audit(mode="audit_only", client=client, report_dir=tmp_dir, batch_size=5)
        self.assertTrue(res["scan_complete"])
        self.assertEqual(res["status"], "succeeded")
        self.assertEqual(res["coverage"]["scan_status"], "complete")
        self.assertIsNone(res["coverage"]["incomplete_reason"])
        self.assertEqual(res["coverage"]["expected_before"], 5)
        self.assertEqual(res["coverage"]["expected_after"], 5)
        self.assertEqual(res["coverage"]["examined_count"], 5)
        self.assertEqual(res["coverage"]["per_status"], {"active": 5})

    # 25. WP2: examined fewer rows than the count says — incomplete, never silent complete
    def test_coverage_mismatch_marks_incomplete(self):
        rows = []
        for i in range(5):
            row = dict(self.sample_active_warning)
            row["id"] = f"00000000-0000-0000-0000-{i:012d}"
            rows.append(row)
        client = MockSupabaseClient({"nav_warnings": rows})
        client.count_overrides["nav_warnings"] = [10, 10]
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = run_audit(mode="audit_only", client=client, report_dir=tmp_dir)
        self.assertFalse(res["scan_complete"])
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["coverage"]["scan_status"], "incomplete")
        self.assertIn("coverage_mismatch", str(res["coverage"]["incomplete_reason"]))

    # 26. WP2: count query failure — incomplete with a named reason
    def test_count_query_failure_marks_incomplete(self):
        client = MockSupabaseClient({"nav_warnings": [dict(self.sample_active_warning)]})
        client.fail_on_count = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = run_audit(mode="audit_only", client=client, report_dir=tmp_dir)
        self.assertFalse(res["scan_complete"])
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["coverage"]["scan_status"], "incomplete")
        self.assertEqual(res["coverage"]["incomplete_reason"], "expected_count_unavailable")

    # 27. WP2: deletion mid-scan (expected_before > examined) — incomplete
    def test_deletion_mid_scan_marks_incomplete(self):
        rows = []
        for i in range(4):
            row = dict(self.sample_active_warning)
            row["id"] = f"00000000-0000-0000-0000-{i:012d}"
            rows.append(row)
        client = MockSupabaseClient({"nav_warnings": rows})
        client.count_overrides["nav_warnings"] = [5, 4]
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = run_audit(mode="audit_only", client=client, report_dir=tmp_dir)
        self.assertFalse(res["scan_complete"])
        self.assertEqual(res["coverage"]["scan_status"], "incomplete")
        self.assertIn("coverage_mismatch", str(res["coverage"]["incomplete_reason"]))

    # 28. Loud abort on PGRST200 geometry fetch failure (audit 2026-11-07:
    # the swallowed per-batch error silently produced 700+ false
    # TIER_A_ZERO_GEOMETRIES).
    def test_geometry_fetch_pgrst200_raises_loudly(self):
        client = MagicMock()
        query = MagicMock()
        query.execute.side_effect = RuntimeError(
            "{'code': 'PGRST200', 'message': \"Could not find a relationship "
            "between 'nav_warning_geometries' and 'st_asgeojson'\"}"
        )
        client.table.return_value.select.return_value.in_.return_value = query
        with self.assertRaises(GeometryFetchError) as ctx:
            fetch_geometries_for_warnings(client, [self.sample_active_warning["id"]])
        self.assertIn("geom_geojson_computed_column", str(ctx.exception))

    # 29. Any geometry batch failure aborts — never a geometry-blind report.
    def test_geometry_fetch_any_batch_failure_raises(self):
        client = MagicMock()
        query = MagicMock()
        query.execute.side_effect = RuntimeError("connection reset by peer")
        client.table.return_value.select.return_value.in_.return_value = query
        with self.assertRaises(GeometryFetchError):
            fetch_geometries_for_warnings(client, [self.sample_active_warning["id"]])

    # 30. Change B: an SDK 5xx (503 Service Unavailable) falls back to the
    # plain REST call, which succeeds — the record IS assessed and the full
    # SDK error is logged (2026-11-07: 809 bare 'ClientError' lines).
    def test_gemini_sdk_5xx_falls_back_to_rest(self):
        import types
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")

        class _Boom:
            def __init__(self, api_key):
                raise RuntimeError("503 Service Unavailable")

        fake_genai.Client = _Boom
        fake_google.genai = fake_genai

        llm_output = json.dumps([{
            "canonical_id": self.sample_active_warning["canonical_id"],
            "field_name": "data_quality",
            "original_value": "AMBIGUOUS",
            "proposed_value": "EXPLICIT",
            "raw_evidence": "GULF OF MEXICO",
            "explanation": "Coordinates are explicitly stated in the bulletin",
            "confidence": 0.9,
            "requires_review": True
        }])
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": llm_output}]}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}), \
             patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            proposals = assess_warning_with_gemini(
                dict(self.sample_active_warning),
                model_name="gemini-3.8-flash",
                issues=[{"code": "TEST_ISSUE"}]
            )
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["field_name"], "data_quality")
        self.assertEqual(proposals[0]["status"], "pending")
        self.assertEqual(proposals[0]["raw_evidence"], "GULF OF MEXICO")


    # --- Gemini rate control (audit 2026-11-07): filter, cap, throttle, 429 ---

    def _rate_record(self, i):
        """Record with AI-fixable issues (unplotted_reason discrepancy)."""
        rec = dict(self.sample_active_warning)
        rec["id"] = f"00000000-0000-0000-0000-{i:012d}"
        rec["canonical_id"] = f"NAVAREA IV 10{i + 1}/26"
        rec["unplotted_reason"] = "no_coordinates"
        return rec

    def _verify_model_response(self):
        """urlopen mock response that satisfies gemini_verify_model."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "[]"}]}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    # 31. Hard cap: 5 AI-fixable records, cap 2 -> exactly 2 Gemini calls, one
    # 'AI cap reached' limitation line, deterministic issues list NOT truncated.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_ai_record_cap_limits_gemini_calls(self, mock_urlopen):
        mock_urlopen.return_value = self._verify_model_response()
        rows = [self._rate_record(i) for i in range(5)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        proposal = {
            "canonical_id": "NAVAREA IV 101/26",
            "field_name": "unplotted_reason",
            "proposed_value": None,
            "raw_evidence": "GULF OF MEXICO",
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini",
                return_value=[proposal],
            ) as mock_assess:
                report = run_audit(
                    mode="propose_corrections", client=client,
                    report_dir=tmp_dir, max_ai_records=2,
                )
        self.assertEqual(mock_assess.call_count, 2)
        cap_lines = [l for l in report["limitations"] if "AI cap reached" in l]
        self.assertEqual(len(cap_lines), 1)
        self.assertIn("2 records assessed", cap_lines[0])
        # The deterministic audit stays unfiltered: all 5 records, all issues
        self.assertEqual(report["examined_count"], 5)
        self.assertEqual(report["issue_count"], 15)
        self.assertEqual(report["status"], "succeeded")
        # Change C: cap-skipped records are ai-unassessed and needs_review
        # (the cap is a deliberate bound, so the status stays succeeded —
        # but the skipped records are never silently treated as passed).
        self.assertEqual(len(report["ai_unassessed"]), 3)
        self.assertTrue(all(e["reason"] == "ai_cap_reached"
                            for e in report["ai_unassessed"]))
        self.assertTrue(all(e["needs_review"]
                            for e in report["ai_unassessed"]))
        self.assertIsNone(report["coverage"]["incomplete_reason"])

    # 32. Records whose only issues are on non-AI-fixable fields (dates,
    # status, geometry) never burn a Gemini call.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_non_ai_fixable_records_skip_gemini(self, mock_urlopen):
        mock_urlopen.return_value = self._verify_model_response()
        rec = dict(self.sample_active_warning)
        rec["triage_tier"] = "B"
        rec["data_quality"] = "INFERRED"
        rec["valid_from"] = "not-a-timestamp"
        client = MockSupabaseClient({
            "nav_warnings": [rec],
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini"
            ) as mock_assess:
                report = run_audit(
                    mode="propose_corrections", client=client, report_dir=tmp_dir,
                )
        mock_assess.assert_not_called()
        self.assertEqual(report["proposal_count"], 0)
        # The deterministic issue survives unfiltered even though the AI pass
        # skipped the record entirely.
        self.assertTrue(any(
            i["code"] == "INVALID_DATE_FORMAT" for i in report["issues"]
        ))

    # 33. Throttle: 10 RPM -> about a 6-second sleep between two calls.
    def test_throttle_enforces_rpm_gap(self):
        original = audit_supabase_parsing._last_ai_call
        audit_supabase_parsing._last_ai_call = 0.0
        try:
            with patch.object(audit_supabase_parsing, "AI_MAX_RPM", 10), \
                 patch("scripts.audit_supabase_parsing.time") as mock_time:
                mock_time.monotonic.side_effect = [0.0, 0.0, 0.0, 0.0]
                _throttle()
                _throttle()
            self.assertEqual(mock_time.sleep.call_count, 2)
            for call in mock_time.sleep.call_args_list:
                self.assertAlmostEqual(call[0][0], 6.0, places=3)
        finally:
            audit_supabase_parsing._last_ai_call = original

    # 34. A 429 on the third record stops the AI pass: the two proposals
    # already made are kept, the loop stops, status is partial.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_rate_limited_429_stops_ai_pass(self, mock_urlopen):
        mock_urlopen.return_value = self._verify_model_response()
        rows = [self._rate_record(i) for i in range(3)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        proposal = {
            "canonical_id": "NAVAREA IV 101/26",
            "field_name": "unplotted_reason",
            "proposed_value": None,
            "raw_evidence": "GULF OF MEXICO",
        }
        calls = {"n": 0}

        def fake_assess(**kwargs):
            if calls["n"] == 2:
                raise GeminiRateLimited("429 RESOURCE_EXHAUSTED: quota exceeded")
            calls["n"] += 1
            return [dict(proposal)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini",
                side_effect=fake_assess,
            ) as mock_assess:
                report = run_audit(
                    mode="propose_corrections", client=client, report_dir=tmp_dir,
                )
        self.assertEqual(mock_assess.call_count, 3)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(report["proposals"]), 2)
        self.assertEqual(report["proposal_count"], 2)
        self.assertEqual(report["status"], "partial")
        self.assertTrue(any("Stopped on Gemini 429 after 3 records" in l
                            for l in report["limitations"]))
        # Change C: partial + scan_complete=True must now carry a NAMED
        # reason, and the record the AI never assessed stays needs_review.
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["coverage"]["incomplete_reason"], "gemini_quota")
        self.assertEqual(len(report["ai_unassessed"]), 1)
        self.assertEqual(report["ai_unassessed"][0]["canonical_id"],
                         "NAVAREA IV 103/26")
        self.assertEqual(report["ai_unassessed"][0]["reason"], "gemini_quota")
        self.assertTrue(report["ai_unassessed"][0]["needs_review"])

    # 35. An SDK 429 must NOT fall through to the REST fallback (a failing run
    # would otherwise make 2 calls per record against an exhausted quota).
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_sdk_429_does_not_fall_through_to_rest(self):
        import types
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")

        class _Models:
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError(
                    "ClientError: 429 RESOURCE_EXHAUSTED quota exceeded"
                )

        class _QuotaClient:
            def __init__(self, api_key):
                self.models = _Models()

        fake_genai.Client = _QuotaClient
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}), \
             patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertRaises(GeminiRateLimited):
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )
        mock_urlopen.assert_not_called()

    # 36. A REST 429 raises the same GeminiRateLimited instead of being
    # swallowed into a silent per-record failure.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_rest_429_raises_rate_limited(self):
        import io
        from urllib.error import HTTPError
        with patch.dict(sys.modules, {"google": None}), \
             patch("urllib.request.urlopen", side_effect=HTTPError(
                 "https://api", 429, "Too Many Requests", None, io.BytesIO(b"{}"))):
            with self.assertRaises(GeminiRateLimited):
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )

    # 37. AUDIT_AI_MAX_RPM="" (or invalid) must import cleanly and fall back
    # to the default of 4 (under the Free Tier's 5 req/min), never raise
    # ValueError at import time. A fresh interpreter is required: the value
    # is read once, at module import.
    def test_empty_or_invalid_rpm_env_imports_cleanly(self):
        import subprocess
        for env_value, expected in (("", 4), ("abc", 4), ("0", 1)):
            env = dict(os.environ, AUDIT_AI_MAX_RPM=env_value)
            result = subprocess.run(
                [sys.executable, "-c",
                 "from scripts import audit_supabase_parsing as m; "
                 "assert m.AI_MAX_RPM == %d, m.AI_MAX_RPM" % expected],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode, 0,
                f"AUDIT_AI_MAX_RPM={env_value!r}: {result.stderr}",
            )

    # 38. A warning ID like "NAVAREA IV 429/26" inside an SDK error message
    # is NOT a 429 status: it must not raise GeminiRateLimited. Change B: it
    # is also a non-5xx failure, so there is NO REST fallback either — the
    # record is unassessed (GeminiUnavailable) and the REST client is never
    # called against the same quota pool.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_warning_id_429_in_message_is_not_rate_limited(self):
        import types
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")

        class _Models:
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError(
                    "ClientError: could not assess NAVAREA IV 429/26 "
                    "(GULF OF MEXICO) - context length exceeded"
                )

        class _ErrClient:
            def __init__(self, api_key):
                self.models = _Models()

        fake_genai.Client = _ErrClient
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}), \
             patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertRaises(GeminiUnavailable):
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )
        mock_urlopen.assert_not_called()

    # 39. A status-code attribute (code == 429) on the SDK exception is
    # honored even when the message text carries no 429 token at all.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_sdk_status_code_attribute_429_raises_rate_limited(self):
        import types
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")

        class _QuotaError(Exception):
            code = 429

        class _Models:
            @staticmethod
            def generate_content(**kwargs):
                raise _QuotaError("Too Many Requests")

        class _QuotaClient:
            def __init__(self, api_key):
                self.models = _Models()

        fake_genai.Client = _QuotaClient
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}), \
             patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertRaises(GeminiRateLimited):
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )
        mock_urlopen.assert_not_called()


    # 40. --max-ai-records is rejected when negative (argparse exits 2).
    def test_negative_max_ai_records_rejected(self):
        with patch.object(
            sys, "argv",
            ["audit_supabase_parsing.py", "--mode", "audit_only",
             "--max-ai-records", "-1"],
        ):
            with self.assertRaises(SystemExit) as ctx:
                audit_supabase_parsing.main()
        self.assertEqual(ctx.exception.code, 2)

    # 41. --max-ai-records 0 is valid and means NO AI calls: the propose run
    # completes with zero Gemini assessments, a cap limitation line, all
    # deterministic issues kept, and status succeeded.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_max_ai_records_zero_disables_ai_calls(self, mock_urlopen):
        mock_urlopen.return_value = self._verify_model_response()
        rows = [self._rate_record(i) for i in range(3)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini",
            ) as mock_assess:
                report = run_audit(
                    mode="propose_corrections", client=client,
                    report_dir=tmp_dir, max_ai_records=0,
                )
        mock_assess.assert_not_called()
        self.assertEqual(report["proposal_count"], 0)
        cap_lines = [l for l in report["limitations"] if "AI cap reached" in l]
        self.assertEqual(len(cap_lines), 1)
        self.assertIn("0 records assessed", cap_lines[0])
        self.assertEqual(report["examined_count"], 3)
        self.assertEqual(report["issue_count"], 9)
        self.assertEqual(report["status"], "succeeded")

    # 42. Change A: the FIRST 429's retryDelay is honored exactly once — the
    # same record is retried after sleeping the API-given delay, and a
    # successful retry keeps the run green (status succeeded).
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_429_retry_delay_honored_once_then_recovers(self, mock_urlopen):
        mock_urlopen.return_value = self._verify_model_response()
        rows = [self._rate_record(i) for i in range(3)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        proposal = {
            "canonical_id": "NAVAREA IV 101/26",
            "field_name": "unplotted_reason",
            "proposed_value": None,
            "raw_evidence": "GULF OF MEXICO",
        }
        calls = {"n": 0}

        def fake_assess(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise GeminiRateLimited(
                    "429 RESOURCE_EXHAUSTED: quota exceeded", retry_delay=7.0
                )
            return [dict(proposal)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini",
                side_effect=fake_assess,
            ) as mock_assess, patch(
                "scripts.audit_supabase_parsing.time"
            ) as mock_time:
                report = run_audit(
                    mode="propose_corrections", client=client,
                    report_dir=tmp_dir,
                )
        # 3 records + exactly 1 retry of the 429'd record
        self.assertEqual(mock_assess.call_count, 4)
        self.assertEqual(mock_time.sleep.call_count, 1)
        self.assertAlmostEqual(mock_time.sleep.call_args[0][0], 7.0, places=3)
        self.assertEqual(len(report["proposals"]), 3)
        self.assertEqual(report["proposal_count"], 3)
        self.assertEqual(report["status"], "succeeded")
        self.assertIsNone(report["coverage"]["incomplete_reason"])

    # 43. Change A: a 429 whose retry ALSO 429s stops the pass after the
    # single retryDelay-honoring retry: partial status, proposals kept,
    # 'Stopped on Gemini 429' limitation line.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_429_retry_delay_once_then_stop_on_second_429(self, mock_urlopen):
        mock_urlopen.return_value = self._verify_model_response()
        rows = [self._rate_record(i) for i in range(3)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        proposal = {
            "canonical_id": "NAVAREA IV 101/26",
            "field_name": "unplotted_reason",
            "proposed_value": None,
            "raw_evidence": "GULF OF MEXICO",
        }
        calls = {"n": 0}

        def fake_assess(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise GeminiRateLimited(
                    "429 RESOURCE_EXHAUSTED: quota exceeded", retry_delay=5.0
                )
            if calls["n"] == 3:
                raise GeminiRateLimited("429 RESOURCE_EXHAUSTED again")
            return [dict(proposal)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini",
                side_effect=fake_assess,
            ) as mock_assess, patch(
                "scripts.audit_supabase_parsing.time"
            ) as mock_time:
                report = run_audit(
                    mode="propose_corrections", client=client,
                    report_dir=tmp_dir,
                )
        # record 1 ok, record 2 429, record 2 retried -> 429 -> stop
        self.assertEqual(mock_assess.call_count, 3)
        self.assertEqual(mock_time.sleep.call_count, 1)
        self.assertAlmostEqual(mock_time.sleep.call_args[0][0], 5.0, places=3)
        self.assertEqual(len(report["proposals"]), 1)
        self.assertTrue(any("Stopped on Gemini 429 after 2 records" in l
                            for l in report["limitations"]))
        self.assertEqual(report["status"], "partial")

    # 44. Change A: retryDelay inside an SDK 429 message is parsed onto the
    # raised GeminiRateLimited (36s), and absurd values are capped at 120s.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_sdk_429_retry_delay_parsed_and_capped(self):
        import types
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")

        class _Models:
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError(
                    "ClientError: 429 RESOURCE_EXHAUSTED. {'error': "
                    "{'details': [{'@type': 'type.googleapis.com/"
                    "google.rpc.RetryInfo', 'retryDelay': '36s'}]}}"
                )

        class _DelayClient:
            def __init__(self, api_key):
                self.models = _Models()

        fake_genai.Client = _DelayClient
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            with self.assertRaises(GeminiRateLimited) as ctx:
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )
        self.assertAlmostEqual(ctx.exception.retry_delay, 36.0, places=3)

        class _ModelsHuge:
            @staticmethod
            def generate_content(**kwargs):
                raise RuntimeError(
                    "ClientError: 429 RESOURCE_EXHAUSTED. {'error': "
                    "{'details': [{'@type': 'type.googleapis.com/"
                    "google.rpc.RetryInfo', 'retryDelay': '9999s'}]}}"
                )

        class _HugeClient:
            def __init__(self, api_key):
                self.models = _ModelsHuge()

        fake_genai.Client = _HugeClient
        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            with self.assertRaises(GeminiRateLimited) as ctx:
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )
        self.assertAlmostEqual(
            ctx.exception.retry_delay,
            audit_supabase_parsing.RETRY_DELAY_CAP_SECONDS,
            places=3,
        )

    # 45. Change A: retryDelay inside a REST 429 error body is parsed onto
    # the raised GeminiRateLimited as well.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_rest_429_retry_delay_parsed(self):
        import io
        from urllib.error import HTTPError
        body = json.dumps({
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [{
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "42s",
                }],
            }
        }).encode("utf-8")
        with patch.dict(sys.modules, {"google": None}), \
             patch("urllib.request.urlopen", side_effect=HTTPError(
                 "https://api", 429, "Too Many Requests", None, io.BytesIO(body))):
            with self.assertRaises(GeminiRateLimited) as ctx:
                assess_warning_with_gemini(
                    dict(self.sample_active_warning),
                    model_name="gemini-3.8-flash",
                    issues=[{"code": "TEST_ISSUE"}],
                )
        self.assertAlmostEqual(ctx.exception.retry_delay, 42.0, places=3)

    # 46. Change B: an SDK response with EMPTY text is a real (empty)
    # answer — no second, quota-burning REST call for the same record.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    def test_sdk_empty_response_never_calls_rest(self):
        import types
        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")

        class _Resp:
            text = ""

        class _Models:
            @staticmethod
            def generate_content(**kwargs):
                return _Resp()

        class _EmptyClient:
            def __init__(self, api_key):
                self.models = _Models()

        fake_genai.Client = _EmptyClient
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}), \
             patch("urllib.request.urlopen") as mock_urlopen:
            proposals = assess_warning_with_gemini(
                dict(self.sample_active_warning),
                model_name="gemini-3.8-flash",
                issues=[{"code": "TEST_ISSUE"}],
            )
        mock_urlopen.assert_not_called()
        self.assertEqual(proposals, [])

    # 47. Change C: a per-record GeminiUnavailable (e.g. 503 on both
    # transports) does NOT abort the pass — remaining records are assessed,
    # but the run is honest: status partial, scan_complete True with
    # incomplete_reason='gemini_unavailable', the failed record marked
    # needs_review and never passed, and summary.json carries the reason.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_gemini_unavailable_record_marks_partial_and_needs_review(
        self, mock_urlopen
    ):
        mock_urlopen.return_value = self._verify_model_response()
        rows = [self._rate_record(i) for i in range(3)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        proposal = {
            "canonical_id": "NAVAREA IV 101/26",
            "field_name": "unplotted_reason",
            "proposed_value": None,
            "raw_evidence": "GULF OF MEXICO",
        }

        def fake_assess(**kwargs):
            if kwargs.get("record", {}).get("canonical_id") == "NAVAREA IV 102/26":
                raise GeminiUnavailable("503 Service Unavailable")
            return [dict(proposal)]

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "scripts.audit_supabase_parsing.assess_warning_with_gemini",
                side_effect=fake_assess,
            ) as mock_assess:
                report = run_audit(
                    mode="propose_corrections", client=client,
                    report_dir=tmp_dir,
                )
            with open(os.path.join(tmp_dir, "summary.json"),
                      encoding="utf-8") as fh:
                summary = json.load(fh)
        # The pass kept going: all 3 records attempted, 2 proposals kept
        self.assertEqual(mock_assess.call_count, 3)
        self.assertEqual(len(report["proposals"]), 2)
        self.assertEqual(report["proposal_count"], 2)
        # Honest status: partial even though the scan itself completed
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["coverage"]["incomplete_reason"],
                         "gemini_unavailable")
        # The failed record is needs_review, never passed: no proposal exists
        # for it and it is listed in ai_unassessed.
        self.assertEqual([e["canonical_id"] for e in report["ai_unassessed"]],
                         ["NAVAREA IV 102/26"])
        self.assertEqual(report["ai_unassessed"][0]["reason"],
                         "gemini_unavailable")
        self.assertTrue(report["ai_unassessed"][0]["needs_review"])
        self.assertFalse(any(
            p["canonical_id"] == "NAVAREA IV 102/26"
            for p in report["proposals"]
        ))
        # summary.json (what the workflow gate reads) carries the reason
        self.assertEqual(summary["incomplete_reason"], "gemini_unavailable")
        self.assertEqual(summary["status"], "partial")

    # 48. Change D: failures and issue_summary are populated from existing
    # data only — real counts, no invented numbers, no fake success. Both
    # records fail with a hard 503 (no SDK): the failure log, the
    # ai_unassessed list and the per-code issue aggregation all reconcile.
    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"})
    @patch("urllib.request.urlopen")
    def test_failures_and_issue_summary_populated_from_existing_data(
        self, mock_urlopen
    ):
        verify_resp = self._verify_model_response()
        mock_urlopen.side_effect = [
            verify_resp,  # model verification (fail-closed gate)
            RuntimeError("503 Service Unavailable"),  # record 1 REST call
            RuntimeError("503 Service Unavailable"),  # record 2 REST call
        ]
        rows = [self._rate_record(i) for i in range(2)]
        client = MockSupabaseClient({
            "nav_warnings": rows,
            "nav_warning_geometries": [],
            "parsing_audit_runs": [],
            "parsing_correction_proposals": [],
        })
        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.dict(sys.modules, {"google": None}):
            report = run_audit(
                mode="propose_corrections", client=client,
                report_dir=tmp_dir,
            )
        # Honest status for a fully failed AI pass
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["coverage"]["incomplete_reason"],
                         "gemini_unavailable")
        # failures: real reasons from the Gemini failure log + real count
        self.assertEqual(
            report["failures"]["ai"],
            {"RuntimeError: 503 Service Unavailable": 2},
        )
        self.assertEqual(report["failures"]["ai_unassessed_count"], 2)
        self.assertEqual(report["ai_failures"],
                         report["failures"]["ai"])
        self.assertEqual(len(report["ai_unassessed"]), 2)
        self.assertTrue(all(e["needs_review"] for e in report["ai_unassessed"]))
        self.assertEqual(report["proposal_count"], 0)
        # issue_summary: aggregated from the deterministic issues list
        self.assertEqual(report["issue_summary"]["total"],
                         report["issue_count"])
        self.assertEqual(report["issue_summary"]["records_with_issues"], 2)
        expected_by_code = {}
        for iss in report["issues"]:
            expected_by_code[iss["code"]] = (
                expected_by_code.get(iss["code"], 0) + 1
            )
        self.assertEqual(report["issue_summary"]["by_code"], expected_by_code)


if __name__ == "__main__":
    unittest.main()

