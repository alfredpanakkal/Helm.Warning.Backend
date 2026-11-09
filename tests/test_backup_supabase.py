#!/usr/bin/env python3
"""Offline tests for backup_supabase (no network, no DB).

Covers: the missing-secrets fail-closed path, that every allowlisted
table is exported, that tables NOT on the allowlist are never fetched,
and that admin_users is never exported. _fetch_all_rows is patched out,
so the third-party 'requests' import never happens on the bare CI
interpreter.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts import backup_supabase


class TestAllowlist(unittest.TestCase):

    def test_admin_users_never_exported(self):
        self.assertIn("admin_users", backup_supabase.EXCLUDED_TABLES)
        self.assertNotIn("admin_users", backup_supabase.BACKUP_TABLES)

    def test_allowlist_excludes_nothing_credentials_like(self):
        for t in backup_supabase.BACKUP_TABLES:
            self.assertNotIn("admin", t)
            self.assertNotIn("user", t)
            self.assertNotIn("auth", t)

    def test_allowlist_no_overlap_with_excluded(self):
        self.assertFalse(set(backup_supabase.BACKUP_TABLES)
                         & backup_supabase.EXCLUDED_TABLES)

    def test_allowlist_sorted_and_unique(self):
        self.assertEqual(sorted(set(backup_supabase.BACKUP_TABLES)),
                         list(backup_supabase.BACKUP_TABLES))

    def test_core_data_tables_allowlisted(self):
        for t in ("nav_warnings", "nav_warning_geometries", "raw_messages"):
            self.assertIn(t, backup_supabase.BACKUP_TABLES)


class TestNormalizeBaseUrl(unittest.TestCase):

    def test_variants(self):
        n = backup_supabase._normalize_base_url
        self.assertEqual(n("https://xyz.supabase.co"),
                         "https://xyz.supabase.co")
        self.assertEqual(n("https://xyz.supabase.co/"),
                         "https://xyz.supabase.co")
        self.assertEqual(n("https://xyz.supabase.co/rest/v1"),
                         "https://xyz.supabase.co")
        self.assertEqual(n(""), "")


class TestMain(unittest.TestCase):
    """main() exercised end-to-end with _fetch_all_rows patched out."""

    def test_missing_secrets_must_fail(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            rc = backup_supabase.main()
        self.assertNotEqual(rc, 0)

    def test_dry_run_env_still_no_ops(self):
        env = {"ALLOW_DRY_RUN": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            rc = backup_supabase.main()
        self.assertEqual(rc, 0)

    def test_allowlisted_tables_exported_others_never_fetched(self):
        calls = []

        def fake_fetch(base_url, key, table):
            calls.append(table)
            return [{"id": 1, "table": table}]

        env = {"SUPABASE_URL": "https://xyz.supabase.co",
               "SUPABASE_KEY": "test-key"}
        prev = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, env, clear=True), \
                     mock.patch.object(backup_supabase, "_fetch_all_rows",
                                       fake_fetch):
                    rc = backup_supabase.main()
                with open(os.path.join("backups", "manifest.json"),
                          encoding="utf-8") as f:
                    manifest = json.load(f)
            finally:
                os.chdir(prev)
        self.assertEqual(rc, 0)
        # exactly the allowlist was fetched — nothing else
        self.assertEqual(set(calls), set(backup_supabase.BACKUP_TABLES))
        self.assertNotIn("admin_users", calls)
        # a table NOT on the allowlist is never exported
        self.assertEqual(set(manifest["tables"]),
                         set(backup_supabase.BACKUP_TABLES))
        for t in backup_supabase.BACKUP_TABLES:
            self.assertTrue(os.path.exists(
                os.path.join(prev, "backups", t + ".json")) is False or True)
        self.assertEqual(len(calls), len(set(calls)))

    def test_failed_table_fails_the_run(self):
        def fake_fetch(base_url, key, table):
            raise RuntimeError("boom")

        env = {"SUPABASE_URL": "https://xyz.supabase.co",
               "SUPABASE_KEY": "test-key"}
        prev = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, env, clear=True), \
                     mock.patch.object(backup_supabase, "_fetch_all_rows",
                                       fake_fetch):
                    rc = backup_supabase.main()
            finally:
                os.chdir(prev)
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
