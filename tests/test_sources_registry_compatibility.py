"""Static contract checks for additive sources_registry schema evolution."""

import unittest
from pathlib import Path


class TestSourcesRegistryCompatibilityMigration(unittest.TestCase):
    def test_migration_adds_frontend_and_backend_contracts(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_sources_registry_legacy_compatibility.sql"
        ).read_text(encoding="utf-8")

        frontend_fields = (
            "publisher_id",
            "publisher_name",
            "navareas",
            "scope",
            "discovery_url",
            "entrypoints",
            "allowed_hosts",
            "format",
            "languages",
            "parser_id",
            "publication_semantics",
            "enabled",
            "verification",
            "health",
            "published_generation_id",
            "updated_at",
        )
        backend_fields = (
            "navarea",
            "poll_interval_sec",
            "is_active",
            "last_run_at",
            "last_status",
            "active_warnings_count",
        )
        for field in frontend_fields + backend_fields:
            with self.subTest(field=field):
                self.assertIn("ADD COLUMN IF NOT EXISTS " + field, migration)

    def test_legacy_region_is_retained_but_no_longer_required(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_sources_registry_legacy_compatibility.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("ALTER COLUMN region DROP NOT NULL", migration)
        self.assertNotIn("DROP COLUMN", migration)
        self.assertNotIn("DELETE FROM", migration)
        self.assertNotIn("TRUNCATE", migration)


if __name__ == "__main__":
    unittest.main()
