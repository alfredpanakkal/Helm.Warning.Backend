"""Static contract checks for public view RLS-invoker hardening."""

import re
import unittest
from pathlib import Path


class TestViewSecurityInvokerMigration(unittest.TestCase):
    def test_both_public_views_are_security_invoker(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_views_security_invoker.sql"
        ).read_text(encoding="utf-8")
        for view in (
            "public.nav_warnings_active_spatial",
            "public.nav_warnings_review_queue",
        ):
            with self.subTest(view=view):
                self.assertIn(
                    "ALTER VIEW " + view + "\n    SET (security_invoker = true)",
                    migration,
                )

    def test_migration_does_not_change_grants_or_policies(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_views_security_invoker.sql"
        ).read_text(encoding="utf-8")
        sql = re.sub(r"--.*?$", "", migration, flags=re.MULTILINE).upper()
        self.assertNotRegex(sql, r"(?m)^\s*(?:REVOKE|GRANT)\b")
        self.assertNotRegex(sql, r"(?m)^\s*(?:CREATE|DROP)\s+POLICY\b")

    def test_migration_requires_base_rls_and_preserves_select_access(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_views_security_invoker.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("nav_warnings RLS must remain enabled", migration)
        self.assertIn("nav_warning_geometries RLS must remain enabled", migration)
        self.assertIn("Public map and review view SELECT privileges must remain available", migration)
        self.assertIn("nav_warnings public SELECT policy must remain available", migration)
        self.assertIn("nav_warning_geometries public SELECT policy must remain available", migration)
        self.assertIn("'anon'::name = ANY(roles)", migration)
        self.assertIn("'authenticated'::name = ANY(roles)", migration)
        self.assertIn("has_table_privilege('anon', 'public.nav_warnings', 'SELECT')", migration)
        self.assertIn("has_table_privilege('authenticated', 'public.nav_warning_geometries', 'SELECT')", migration)


class TestRemainingPublicViewsSecurityInvokerMigration(unittest.TestCase):
    def setUp(self):
        self.migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261120180000_harden_remaining_public_views.sql"
        ).read_text(encoding="utf-8")

    def test_archive_and_unverified_views_are_security_invoker(self):
        for view in (
            "public.nav_warnings_archive",
            "public.nav_warnings_unverified_spatial",
        ):
            with self.subTest(view=view):
                self.assertIn(
                    "ALTER VIEW " + view + "\n    SET (security_invoker = true)",
                    self.migration,
                )

    def test_migration_preserves_base_rls_and_public_select_contract(self):
        for expected in (
            "nav_warnings RLS must remain enabled",
            "nav_warning_geometries RLS must remain enabled",
            "nav_warnings public SELECT policy must remain available",
            "nav_warning_geometries public SELECT policy must remain available",
            "Public archive and unverified view SELECT privileges must remain available",
            "has_table_privilege('anon', 'public.nav_warnings_archive', 'SELECT')",
            "has_table_privilege('authenticated', 'public.nav_warnings_unverified_spatial', 'SELECT')",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.migration)

    def test_migration_does_not_change_grants_or_policies(self):
        sql = re.sub(r"--.*?$", "", self.migration, flags=re.MULTILINE).upper()
        self.assertNotRegex(sql, r"(?m)^\s*(?:REVOKE|GRANT)\b")
        self.assertNotRegex(sql, r"(?m)^\s*(?:CREATE|DROP)\s+POLICY\b")


if __name__ == "__main__":
    unittest.main()
