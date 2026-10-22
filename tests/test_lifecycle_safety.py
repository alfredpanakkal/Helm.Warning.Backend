#!/usr/bin/env python3
"""tests/test_lifecycle_safety.py — Lifecycle-safety regression tests.

Covers the evidence-based archive policy introduced with the
20261023 lifecycle-safety work: absence from a scrape is NOT
cancellation, archiving is a status change, and every run leaves
an audit ledger row in ingestion_generations.

Uses standard library unittest for zero-dependency test execution.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.sync_engine import run_differential_sync


class _Exec:
    def __init__(self, data):
        self.data = data


def _make_sync_client(warn_rows, raw_rows=()):
    """Mocks the chained supabase builder used by run_differential_sync.

    Records every .update() patch (status transitions) and every
    .insert() payload (run ledger rows) for assertion.
    """
    client = MagicMock()
    client.recorded_updates = []
    client.recorded_inserts = {}

    def table(name):
        t = MagicMock()
        if name == "nav_warnings":
            t.select.return_value.eq.return_value.execute.return_value = _Exec(list(warn_rows))
            orig_update = t.update

            def update_rec(patch, *a, **k):
                client.recorded_updates.append({"table": name, "patch": patch})
                return orig_update(patch, *a, **k)

            t.update.side_effect = update_rec
        elif name == "raw_messages":
            t.select.return_value.eq.return_value.execute.return_value = _Exec(list(raw_rows))
        else:
            t.insert.return_value.execute.return_value = _Exec([])
            orig_insert = t.insert

            def insert_rec(payload, *a, **k):
                client.recorded_inserts.setdefault(name, []).append(payload)
                return orig_insert(payload, *a, **k)

            t.insert.side_effect = insert_rec
        return t

    client.table.side_effect = table
    return client


def _status_updates(client, table_name="nav_warnings"):
    return [u["patch"] for u in client.recorded_updates if u["table"] == table_name]


def _scraped(source_id, navarea, ids, checksum_prefix="chk"):
    """Builds minimal scraped warning/message sets for the given ids."""
    warnings = []
    messages = []
    for i, wid in enumerate(ids):
        cid = f"{navarea} {wid}"
        warnings.append({
            "warning_id": wid,
            "navarea": navarea,
            "source_id": source_id,
            "title": f"TEST {wid}",
            "raw_text": f"NAVAREA {navarea} {wid} TEST WARNING",
            "spatial": {"type": "Point", "coordinates": [10.0, 50.0]},
            "checksum_sha256": f"{checksum_prefix}{i}",
        })
        messages.append({
            "warning_id": wid,
            "canonical_id": cid,
            "checksum_sha256": f"{checksum_prefix}{i}",
        })
    return warnings, messages


def _db_rows(navarea, ids, valid_to=None):
    rows = []
    for wid in ids:
        rows.append({
            "canonical_id": f"{navarea} {wid}",
            "status": "active",
            "raw_text": "OLD",
            "valid_to": valid_to,
        })
    return rows


class TestLifecycleSafety(unittest.TestCase):
    """Archiving = status/visibility change, never deletion."""

    def test_partial_scrape_never_cancels_missing_warnings(self):
        """Guard: a feed covering only a small fraction of the DB's active
        warnings must leave the absent warnings ACTIVE (they are merely
        'unobserved', recorded in the run ledger)."""
        navarea = "NAVAREA IV"
        source_id = "nga-navarea-iv"
        db_ids = [f"{n:03d}/26" for n in range(1, 21)]        # 20 actives in DB
        feed_ids = db_ids[:2]                                   # partial scrape: 2

        warnings, messages = _scraped(source_id, navarea, feed_ids)
        client = _make_sync_client(_db_rows(navarea, db_ids), [])

        ok = run_differential_sync(
            source_id=source_id,
            navarea_name=navarea,
            scraped_warnings=warnings,
            scraped_messages=messages,
            supabase_client=client,
        )
        self.assertTrue(ok)
        # No status transition may be issued: the 18 absent warnings stay active.
        self.assertEqual(_status_updates(client), [])

    def test_credible_snapshot_cancels_with_evidence(self):
        """A credible, large snapshot may archive absent warnings — with an
        explicit status_basis and status_changed_at."""
        navarea = "NAVAREA IV"
        source_id = "nga-navarea-iv"
        db_ids = [f"{n:03d}/26" for n in range(1, 21)]        # 20 actives in DB
        feed_ids = db_ids[:15]                                 # 15/20 = 75% >= 50%

        warnings, messages = _scraped(source_id, navarea, feed_ids)
        client = _make_sync_client(_db_rows(navarea, db_ids), [])

        ok = run_differential_sync(
            source_id=source_id,
            navarea_name=navarea,
            scraped_warnings=warnings,
            scraped_messages=messages,
            supabase_client=client,
        )
        self.assertTrue(ok)

        patches = _status_updates(client)
        self.assertEqual(len(patches), 5)  # 5 absent warnings archived, not deleted
        for patch in patches:
            self.assertEqual(patch["status"], "cancelled")
            self.assertEqual(patch["status_basis"], "source_absence_verified_snapshot")
            self.assertIn("status_changed_at", patch)

    def test_expired_warning_archived_as_expired_not_cancelled(self):
        """A missing warning whose valid_to has passed must transition to
        'expired' (evidence: validity period), even when the feed is small."""
        navarea = "NAVAREA IV"
        source_id = "nga-navarea-iv"
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db_rows = [
            {"canonical_id": f"{navarea} 001/26", "status": "active",
             "raw_text": "OLD", "valid_to": past},
            {"canonical_id": f"{navarea} 002/26", "status": "active",
             "raw_text": "OLD", "valid_to": None},
        ]
        warnings, messages = _scraped(source_id, navarea, ["002/26"])  # 001 absent
        client = _make_sync_client(db_rows, [])

        ok = run_differential_sync(
            source_id=source_id,
            navarea_name=navarea,
            scraped_warnings=warnings,
            scraped_messages=messages,
            supabase_client=client,
        )
        self.assertTrue(ok)

        patches = _status_updates(client)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["status"], "expired")
        self.assertEqual(patches[0]["status_basis"], "expired_by_validity")
        # 002/26 (no valid_to, small feed) stays active: no other transitions.

    def test_run_ledger_recorded(self):
        """Every run must leave an ingestion_generations ledger row, even on
        the happy path, so later disappearances can be investigated."""
        navarea = "NAVAREA IV"
        source_id = "nga-navarea-iv"
        warnings, messages = _scraped(source_id, navarea, ["001/26"])
        client = _make_sync_client([], [])

        ok = run_differential_sync(
            source_id=source_id,
            navarea_name=navarea,
            scraped_warnings=warnings,
            scraped_messages=messages,
            supabase_client=client,
        )
        self.assertTrue(ok)
        ledger_rows = client.recorded_inserts.get("ingestion_generations", [])
        self.assertEqual(len(ledger_rows), 1)
        row = ledger_rows[0]
        self.assertEqual(row["source_id"], source_id)
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["parsed_count"], 1)
        self.assertIn("details", row)
        self.assertIn("cancel_guard", row["details"])


if __name__ == "__main__":
    unittest.main()
