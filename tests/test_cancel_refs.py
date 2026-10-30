#!/usr/bin/env python3
"""tests/test_cancel_refs.py — CANCEL cross-reference resolution tests.

Audit finding F2 (2026-10-30): the parsers extract cross-refs onto the
warning payload, but the sync layer never resolved them — 0/594 live
rows ever transitioned on a published cancellation. These tests pin the
new shared-engine pass: audit-first default (zero writes), explicit
apply gate, self/feed guards, loud unresolved logging, and the
end-to-end property that a CANCEL cross-reference cancels a target even
when scrape-absence cannot (partial feed below the cancel-guard
threshold).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.sync_engine import (
    _cancel_ref_target_ids,
    resolve_cancel_cross_refs,
    run_differential_sync,
)


class _Exec:
    def __init__(self, data):
        self.data = data


CARRIER = {
    "warning_id": "NAVAREA XI 0479/26",
    "canonical_id": "NAVAREA XI 0479/26",
    "cross_refs": [{"number": "0430", "year": "26"}],
}


def _ref_client(ref_rows):
    """Mock client for the cross-ref lookup: nav_warnings
    .select().in_() returns ref_rows; update() patches are recorded."""
    client = MagicMock()
    client.recorded_updates = []

    def table(name):
        t = MagicMock()
        if name == "nav_warnings":
            select_builder = MagicMock()
            select_builder.in_.return_value.execute.return_value = _Exec(
                list(ref_rows))
            t.select.return_value = select_builder
            update_builder = MagicMock()
            update_builder.eq.return_value.execute.return_value = _Exec([])

            def update_rec(patch, *a, **k):
                client.recorded_updates.append(patch)
                return update_builder

            t.update.side_effect = update_rec
        return t

    client.table.side_effect = table
    return client


class TestCancelRefTargetIds(unittest.TestCase):
    """Pure mapping: refs -> target canonical ids, with guards."""

    def test_mapping_and_dedup(self):
        w = dict(CARRIER)
        targets = _cancel_ref_target_ids([w, dict(w)], "NAVAREA XI", set())
        # F8: a ref registers every padding variant of its number; the
        # padded feed form plus the unpadded alias both map to the carrier.
        self.assertEqual(targets,
                         {"NAVAREA XI 0430/26": "NAVAREA XI 0479/26",
                          "NAVAREA XI 430/26": "NAVAREA XI 0479/26"})

    def test_self_reference_excluded(self):
        w = {
            "warning_id": "NAVAREA V 0622/26",
            "canonical_id": "NAVAREA V 0622/26",
            "cross_refs": [{"number": "0622", "year": "26"}],
        }
        self.assertEqual(_cancel_ref_target_ids([w], "NAVAREA V", set()), {})

    def test_in_feed_target_excluded(self):
        # the feed still lists the referenced warning in force: the feed
        # is fresher evidence than the cross-reference
        targets = _cancel_ref_target_ids(
            [CARRIER], "NAVAREA XI", {"NAVAREA XI 0430/26"})
        # The in-feed (padded) form is excluded; the unpadded alias stays
        # registered as a harmless extra lookup (it resolves only if such a
        # row exists; live DB has no padded/unpadded pair on any source).
        self.assertNotIn("NAVAREA XI 0430/26", targets)

    def test_malformed_refs_ignored(self):
        w = {"canonical_id": "NAVAREA XI 0100/26",
             "cross_refs": [{"number": "1"}, {"year": "26"}, "bad", None]}
        self.assertEqual(_cancel_ref_target_ids([w], "NAVAREA XI", set()), {})


class TestResolveCancelCrossRefs(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("SYNC_APPLY_CANCEL_REFS", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["SYNC_APPLY_CANCEL_REFS"] = self._saved

    def test_audit_only_default_writes_nothing(self):
        client = _ref_client(
            [{"canonical_id": "NAVAREA XI 0430/26", "status": "active"}])
        counts = resolve_cancel_cross_refs(client, [CARRIER], "NAVAREA XI")
        # F8: referenced counts candidate targets (each padding variant is
        # its own lookup); the un-found unpadded alias is a loud unresolved
        # entry, never a write.
        self.assertEqual(counts["referenced"], 2)
        self.assertEqual(counts["resolved"], 1)
        self.assertEqual(counts["applied"], 0)
        self.assertEqual(counts["unresolved"], 1)
        self.assertEqual(client.recorded_updates, [])

    def test_apply_mode_transitions_active_target(self):
        os.environ["SYNC_APPLY_CANCEL_REFS"] = "1"
        client = _ref_client(
            [{"canonical_id": "NAVAREA XI 0430/26", "status": "active"}])
        counts = resolve_cancel_cross_refs(client, [CARRIER], "NAVAREA XI")
        self.assertEqual(counts["applied"], 1)
        self.assertEqual(len(client.recorded_updates), 1)
        patch = client.recorded_updates[0]
        self.assertEqual(patch["status"], "cancelled")
        self.assertEqual(patch["status_basis"], "cancelled_by_cross_reference")
        self.assertIn("status_changed_at", patch)

    def test_unresolved_ref_logged_no_write(self):
        client = _ref_client([])
        counts = resolve_cancel_cross_refs(client, [CARRIER], "NAVAREA XI")
        self.assertEqual(counts["unresolved"], 1)
        self.assertEqual(counts["resolved"], 0)
        self.assertEqual(client.recorded_updates, [])

    def test_non_active_target_is_no_op(self):
        client = _ref_client(
            [{"canonical_id": "NAVAREA XI 0430/26", "status": "cancelled"}])
        counts = resolve_cancel_cross_refs(client, [CARRIER], "NAVAREA XI")
        self.assertEqual(counts["resolved"], 0)
        self.assertEqual(counts["applied"], 0)
        self.assertEqual(client.recorded_updates, [])

    def test_no_cross_refs_makes_no_db_call(self):
        client = _ref_client([])
        plain = {"warning_id": "NAVAREA XI 0100/26",
                 "canonical_id": "NAVAREA XI 0100/26", "cross_refs": []}
        counts = resolve_cancel_cross_refs(client, [plain], "NAVAREA XI")
        self.assertEqual(counts["referenced"], 0)
        client.table.assert_not_called()


class TestE2ECrossRefCancelsWhereAbsenceCannot(unittest.TestCase):
    """A CANCEL cross-reference is positive withdrawal evidence: it must
    cancel the target even when the feed is far below the absence-based
    cancel-guard threshold (1 scraped vs 1 DB active is NOT credible as
    a complete snapshot)."""

    def test_e2e_apply_mode_cancels_target(self):
        os.environ["SYNC_APPLY_CANCEL_REFS"] = "1"
        try:
            client = MagicMock()
            client.recorded_updates = []
            client.recorded_inserts = {}

            def table(name):
                t = MagicMock()
                if name == "nav_warnings":
                    select_builder = MagicMock()
                    select_builder.eq.return_value.execute.return_value = _Exec([
                        {"id": "uuid-t", "canonical_id": "NAVAREA XI 0430/26",
                         "status": "active", "raw_text": "OLD",
                         "valid_to": None, "triage_tier": "A"},
                    ])
                    select_builder.in_.return_value.execute.return_value = _Exec([
                        {"canonical_id": "NAVAREA XI 0430/26",
                         "status": "active"},
                    ])
                    t.select.return_value = select_builder
                    update_builder = MagicMock()
                    update_builder.eq.return_value.execute.return_value = _Exec([])

                    def update_rec(patch, *a, **k):
                        client.recorded_updates.append(patch)
                        return update_builder

                    t.update.side_effect = update_rec
                else:
                    insert_builder = MagicMock()
                    insert_builder.execute.return_value = _Exec([])

                    def insert_rec(payload, *a, **k):
                        client.recorded_inserts.setdefault(name, []).append(
                            payload)
                        return insert_builder

                    t.insert.side_effect = insert_rec
                return t

            client.table.side_effect = table
            client.rpc.return_value.execute.return_value = _Exec([])

            scraped = [{
                "warning_id": "NAVAREA XI 0479/26",
                "canonical_id": "NAVAREA XI 0479/26",
                "navarea": "XI",
                "source_id": "manual-navarea-xi",
                "title": "CANCEL NOTICE",
                "raw_text": "NAVAREA XI 0479/26 CANCEL NAVAREA XI 0430/26.",
                "spatial": {"type": "Point", "coordinates": [135.0, 35.0]},
                "cross_refs": [{"number": "0430", "year": "26"}],
            }]
            messages = [{
                "warning_id": "NAVAREA XI 0479/26",
                "canonical_id": "NAVAREA XI 0479/26",
                "checksum_sha256": "chk1",
            }]

            ok = run_differential_sync(
                source_id="manual-navarea-xi",
                navarea_name="NAVAREA XI",
                scraped_warnings=scraped,
                scraped_messages=messages,
                supabase_client=client,
            )
            self.assertTrue(ok)

            # exactly one transition: the cross-ref cancel (0430 was
            # 'unobserved' by the absence pass — feed not credible)
            self.assertEqual(len(client.recorded_updates), 1)
            patch = client.recorded_updates[0]
            self.assertEqual(patch["status"], "cancelled")
            self.assertEqual(patch["status_basis"],
                             "cancelled_by_cross_reference")

            # ledger records the cross-ref counts
            ledger = client.recorded_inserts.get("ingestion_generations", [])
            self.assertEqual(len(ledger), 1)
            details = ledger[0]["details"]
            # F8: 2 candidate targets (padded form + unpadded alias)
            self.assertEqual(details["cancel_refs"]["referenced"], 2)
            self.assertEqual(details["cancel_refs"]["applied"], 1)
            self.assertEqual(details["unobserved"], 1)
        finally:
            os.environ.pop("SYNC_APPLY_CANCEL_REFS", None)


class TestRefNumberPaddingVariants(unittest.TestCase):
    """F8 (2026-10-30, live-DB confirmed): cross-ref numbers are padded by
    some parser configs (the NGA XII memo config pads refs to 3 digits)
    while the target's stored canonical_id is the memo header VERBATIM
    ("NAVAREA XII 88/26" is a live row). A single-form target can never
    resolve, so every padding variant of the ref number is registered
    and whichever form is stored gets found. Verified live: no source
    carries both a padded and an unpadded form, so variants are aliases
    of the same warning, never distinct targets.
    """

    def test_zfilled_ref_resolves_verbatim_stored_id(self):
        # memo config pads the CANCEL ref "88" -> "088"; the stored
        # canonical_id is the verbatim header "NAVAREA XII 88/26"
        carrier = {
            "canonical_id": "NAVAREA XII 99/26",
            "cross_refs": [{"number": "088", "year": "26"}],
        }
        targets = _cancel_ref_target_ids([carrier], "NAVAREA XII", set())
        self.assertIn("NAVAREA XII 88/26", targets)
        self.assertIn("NAVAREA XII 088/26", targets)

    def test_unpadded_ref_resolves_padded_stored_id(self):
        carrier = {
            "canonical_id": "NAVAREA V 0700/26",
            "cross_refs": [{"number": "700", "year": "26"}],
        }
        targets = _cancel_ref_target_ids([carrier], "NAVAREA V", set())
        self.assertIn("NAVAREA V 700/26", targets)
        self.assertIn("NAVAREA V 0700/26", targets)

    def test_variants_dedupe_to_distinct_forms(self):
        targets = _cancel_ref_target_ids([dict(CARRIER)], "NAVAREA XI", set())
        self.assertEqual(
            set(targets),
            {"NAVAREA XI 0430/26", "NAVAREA XI 430/26"})
        self.assertEqual(
            set(targets.values()), {"NAVAREA XI 0479/26"})

    def test_in_feed_guard_covers_verbatim_alias(self):
        # the feed lists the target in force under its stored (verbatim)
        # form: the digits variant is excluded, so the guard still sees
        # the alias that would actually resolve in the DB.
        carrier = {
            "canonical_id": "NAVAREA XII 99/26",
            "cross_refs": [{"number": "088", "year": "26"}],
        }
        targets = _cancel_ref_target_ids(
            [carrier], "NAVAREA XII", {"NAVAREA XII 88/26"})
        self.assertNotIn("NAVAREA XII 88/26", targets)

    def test_apply_mode_resolves_verbatim_stored_row(self):
        # end-to-end through the resolver: only the verbatim row exists
        # in the DB; the padded variant stays a loud unresolved alias.
        os.environ["SYNC_APPLY_CANCEL_REFS"] = "1"
        try:
            client = _ref_client(
                [{"canonical_id": "NAVAREA XII 88/26", "status": "active"}])
            carrier = {
                "canonical_id": "NAVAREA XII 99/26",
                "cross_refs": [{"number": "088", "year": "26"}],
            }
            counts = resolve_cancel_cross_refs(
                client, [carrier], "NAVAREA XII")
            self.assertEqual(counts["resolved"], 1)
            self.assertEqual(counts["applied"], 1)
            self.assertEqual(counts["unresolved"], 1)
            patch = client.recorded_updates[0]
            self.assertEqual(patch["status"], "cancelled")
            self.assertEqual(patch["status_basis"],
                             "cancelled_by_cross_reference")
        finally:
            os.environ.pop("SYNC_APPLY_CANCEL_REFS", None)

if __name__ == "__main__":
    unittest.main()
