"""Contract checks for the spatial_ref_sys guard synchronization migration."""

import unittest
from pathlib import Path


class TestSpatialRefSysApiGuardSyncMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261120150000_sync_spatial_ref_sys_api_guard.sql"
        ).read_text(encoding="utf-8")

    def test_replaces_function_with_hardened_role_resolution(self):
        for token in (
            "CREATE OR REPLACE FUNCTION private.block_spatial_ref_sys_writes()",
            "request.jwt.claims",
            "current_setting('role', true)",
            "current_user",
            "request_method IN ('POST', 'PUT', 'PATCH', 'DELETE')",
            "request_role IN ('anon', 'authenticated')",
            "request_path IN ('spatial_ref_sys', 'public.spatial_ref_sys')",
            "SECURITY INVOKER",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.migration)

    def test_preserves_existing_hook_and_does_not_change_table_acl_or_rls(self):
        self.assertNotIn("ALTER ROLE authenticator", self.migration)
        self.assertNotIn("REVOKE ALL PRIVILEGES ON TABLE public.spatial_ref_sys", self.migration)
        self.assertNotIn("ALTER TABLE public.spatial_ref_sys ENABLE ROW LEVEL SECURITY", self.migration)
        self.assertIn("NOTIFY pgrst, 'reload config'", self.migration)

    def test_limits_function_execution_and_uses_safe_search_path(self):
        self.assertIn("SET search_path = pg_catalog", self.migration)
        self.assertIn("REVOKE ALL ON FUNCTION private.block_spatial_ref_sys_writes() FROM PUBLIC", self.migration)
        self.assertIn("TO authenticator, anon, authenticated, service_role", self.migration)


if __name__ == "__main__":
    unittest.main()
