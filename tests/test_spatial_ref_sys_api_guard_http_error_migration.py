"""Static checks for the corrected PostgREST custom-error envelope."""

import unittest
from pathlib import Path


class TestSpatialRefSysApiGuardHttpErrorMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261120190000_fix_spatial_ref_sys_api_guard_response.sql"
        ).read_text(encoding="utf-8")

    def test_pgrst_error_detail_contains_required_status_and_headers(self):
        self.assertIn("RAISE SQLSTATE 'PGRST' USING", self.migration)
        self.assertIn("'status', 403", self.migration)
        self.assertIn("'headers', '{}'::jsonb", self.migration)

    def test_guard_scope_and_execution_context_are_preserved(self):
        for token in (
            "SECURITY INVOKER",
            "SET search_path = pg_catalog",
            "request_method IN ('POST', 'PUT', 'PATCH', 'DELETE')",
            "request_role IN ('anon', 'authenticated')",
            "request_path IN ('spatial_ref_sys', 'public.spatial_ref_sys')",
            "TO authenticator, anon, authenticated, service_role",
            "NOTIFY pgrst, 'reload config'",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.migration)

    def test_migration_does_not_change_table_acl_rls_or_hook_configuration(self):
        self.assertNotIn("ALTER ROLE authenticator", self.migration)
        self.assertNotIn("ALTER TABLE public.spatial_ref_sys", self.migration)
        self.assertNotIn("REVOKE ALL PRIVILEGES ON TABLE public.spatial_ref_sys", self.migration)
        self.assertNotIn("CREATE POLICY", self.migration)
        self.assertNotIn("DROP POLICY", self.migration)


if __name__ == "__main__":
    unittest.main()
