"""Static contract checks for internal-table ACL hardening."""

import re
import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20261120170000_harden_internal_table_privileges.sql"
)


class TestInternalTablePrivilegeMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"--.*?$", "", cls.sql, flags=re.MULTILINE).lower()

    def test_internal_tables_are_revoked_from_api_roles(self):
        for table in (
            "public.nav_warning_audits",
            "public.parsing_audit_runs",
            "public.parsing_correction_proposals",
            "public.nav_warning_cancellations",
            "public.nav_warning_schedules",
            "public.raw_artifacts",
            "public.pipeline_logs",
            "public.scraper_runs",
            "public.nav_warning_guard_snapshot",
            "public.nav_warnings_archive_legacy",
        ):
            with self.subTest(table=table):
                self.assertIn(table, self.normalized)

        self.assertIn("revoke all privileges on table", self.normalized)
        self.assertIn("from anon, authenticated", self.normalized)
        self.assertIn("to_regclass(v_table_name)", self.normalized)

    def test_admin_tables_keep_authenticated_access_but_drop_anon(self):
        self.assertIn(
            "public.admin_users,\n    public.manual_ingest_queue,\n    public.pipeline_runs",
            self.normalized,
        )
        self.assertRegex(
            self.normalized,
            r"revoke all privileges on table[\s\S]*?from anon;",
        )
        self.assertIn(
            "authenticated admin select access was not preserved",
            self.normalized,
        )

    def test_non_crud_privileges_are_removed_without_touching_srid_catalogue(self):
        self.assertIn(
            "revoke truncate, references, trigger, maintain on table",
            self.normalized,
        )
        self.assertIn("c.relname <> 'spatial_ref_sys'", self.normalized)
        self.assertIn("supabase_admin", self.sql.lower())

    def test_service_role_access_is_asserted_and_never_revoked(self):
        revoke_statements = re.findall(
            r"\brevoke\b[\s\S]*?;",
            self.normalized,
        )
        self.assertTrue(revoke_statements)
        self.assertTrue(
            all("from service_role" not in statement for statement in revoke_statements)
        )
        self.assertIn(
            "service_role access was not preserved",
            self.normalized,
        )

    def test_public_read_contract_and_rls_policies_are_unchanged(self):
        revoke_statements = re.findall(
            r"revoke all privileges on table[\s\S]*?;",
            self.normalized,
        )
        for table in (
            "public.nav_warnings",
            "public.nav_warning_geometries",
            "public.raw_messages",
            "public.ingestion_generations",
            "public.in_force_snapshots",
            "public.sources_registry",
        ):
            with self.subTest(table=table):
                self.assertFalse(
                    any(re.search(rf"\b{re.escape(table)}\b", statement) for statement in revoke_statements)
                )

        self.assertNotRegex(self.normalized, r"\b(?:create|drop)\s+policy\b")
        self.assertNotRegex(self.normalized, r"\balter\s+table\b")
        self.assertIn("public read contracts", self.sql.lower())


if __name__ == "__main__":
    unittest.main()
