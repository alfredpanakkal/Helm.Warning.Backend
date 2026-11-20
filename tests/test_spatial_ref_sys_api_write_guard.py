"""Static contract checks for the spatial_ref_sys Data API write guard."""

import unittest
from pathlib import Path


class TestSpatialRefSysApiWriteGuardMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261120_spatial_ref_sys_api_write_guard.sql"
        ).read_text(encoding="utf-8")

    def test_hook_is_scoped_to_spatial_ref_sys_write_methods_and_client_roles(self):
        for token in (
            "pgrst.db_pre_request",
            "private.block_spatial_ref_sys_writes",
            "request.method",
            "request.path",
            "request.jwt.claims",
            "('POST', 'PUT', 'PATCH', 'DELETE')",
            "('anon', 'authenticated')",
            "'spatial_ref_sys'",
            "'public.spatial_ref_sys'",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.migration)

    def test_hook_preserves_reads_and_other_roles_by_narrow_matching(self):
        self.assertIn("request_method IN ('POST', 'PUT', 'PATCH', 'DELETE')", self.migration)
        self.assertIn("request_role IN ('anon', 'authenticated')", self.migration)
        self.assertIn("request_path IN ('spatial_ref_sys', 'public.spatial_ref_sys')", self.migration)
        self.assertIn("SECURITY INVOKER", self.migration)

    def test_existing_pre_request_hook_is_not_silently_overwritten(self):
        self.assertIn("Do not silently replace another project's existing pre-request hook", self.migration)
        self.assertIn("already has a different pgrst.db_pre_request hook", self.migration)

    def test_migration_does_not_claim_to_revoke_managed_table_grants_or_enable_rls(self):
        self.assertNotIn("REVOKE ALL PRIVILEGES ON TABLE public.spatial_ref_sys", self.migration)
        self.assertNotIn("ALTER TABLE public.spatial_ref_sys ENABLE ROW LEVEL SECURITY", self.migration)
        self.assertNotIn("DROP EXTENSION", self.migration)
        self.assertIn("does not protect direct database connections", self.migration)


if __name__ == "__main__":
    unittest.main()
