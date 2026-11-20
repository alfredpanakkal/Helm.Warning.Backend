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
        self.assertIn("ALTER COLUMN navarea DROP NOT NULL", migration)
        self.assertIn("ALTER COLUMN parser_id DROP NOT NULL", migration)
        self.assertNotIn("DROP COLUMN", migration)
        self.assertNotIn("DELETE FROM", migration)
        self.assertNotIn("TRUNCATE", migration)

    def test_migration_asserts_frontend_upsert_conflict_and_nullability(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_sources_registry_legacy_compatibility.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("Frontend SourceRegistryItem columns are incomplete", migration)
        self.assertIn("Frontend-omitted source registry columns must be nullable", migration)
        self.assertIn("con.contype IN ('p', 'u')", migration)
        self.assertIn("pg_get_constraintdef(con.oid) LIKE '%(source_id)%'", migration)

    def test_omitted_not_null_columns_must_have_defaults_or_be_generated(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_sources_registry_legacy_compatibility.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("c.is_nullable = 'NO'", migration)
        self.assertIn("c.column_default IS NULL", migration)
        self.assertIn("c.is_identity = 'NO'", migration)
        self.assertIn("c.is_generated = 'NEVER'", migration)
        self.assertIn(
            "sources_registry has a required column omitted by frontend upsert",
            migration,
        )
        # The legacy-only columns are intentionally absent from the frontend
        # payload allowlist and therefore must be nullable or have defaults.
        self.assertIn("'source_id',", migration)
        self.assertIn("'updated_at'", migration)

    def test_operational_check_constraints_are_added_idempotently(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261113_sources_registry_legacy_compatibility.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("sources_registry_poll_interval_sec_check", migration)
        self.assertIn("CHECK (poll_interval_sec > 0) NOT VALID", migration)
        self.assertIn("sources_registry_active_warnings_count_check", migration)
        self.assertIn("CHECK (active_warnings_count >= 0) NOT VALID", migration)
        self.assertIn("IF NOT EXISTS (", migration)


if __name__ == "__main__":
    unittest.main()
