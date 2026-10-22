ga-navarea-iv"
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
