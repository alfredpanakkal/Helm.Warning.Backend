#!/usr/bin/env python3
"""Offline tests for backup_supabase helpers (no network, no DB)."""
import os
import sys
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.backup_supabase import (
    EXCLUDED_TABLES,
    _extract_table_names,
    _normalize_base_url,
)


class TestBackupHelpers(unittest.TestCase):

    def test_normalize_base_url_variants(self):
        self.assertEqual(
            _normalize_base_url("https://xyz.supabase.co"),
            "https://xyz.supabase.co")
        self.assertEqual(
            _normalize_base_url("https://xyz.supabase.co/"),
            "https://xyz.supabase.co")
        self.assertEqual(
            _normalize_base_url("https://xyz.supabase.co/rest/v1"),
            "https://xyz.supabase.co")
        self.assertEqual(_normalize_base_url(""), "")

    def test_extract_table_names_get_paths_only(self):
        openapi = {
            "paths": {
                "/nav_warnings": {"get": {}},
                "/nav_warning_geometries": {"get": {}},
                "/admin_save_nav_warning": {"post": {}},
                "/upsert_nav_warning": {"post": {}},
                "/admin_users": {"get": {}},
                "/deep/nested/path": {"get": {}},
            }
        }
        names = _extract_table_names(openapi)
        self.assertEqual(names, ["nav_warning_geometries", "nav_warnings"])

    def test_extract_table_names_empty_root(self):
        self.assertEqual(_extract_table_names({}), [])
        self.assertEqual(_extract_table_names({"paths": None}), [])

    def test_admin_users_always_excluded(self):
        self.assertIn("admin_users", EXCLUDED_TABLES)
        openapi = {"paths": {"/admin_users": {"get": {}}}}
        self.assertEqual(_extract_table_names(openapi), [])


if __name__ == "__main__":
    unittest.main()
