import tempfile
import unittest
from pathlib import Path

from scripts.audit_migration_ledger import (
    compare_versions,
    legacy_migration_files,
    repository_versions,
)


class TestRepositoryVersions(unittest.TestCase):

    def test_reads_numeric_prefixes_and_ignores_non_sql_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "20261120150000_fix_guard.sql").write_text("SELECT 1;")
            (root / "20261120170000_harden_acl.sql").write_text("SELECT 1;")
            (root / "20261019_legacy_migration.sql").write_text("SELECT 1;")
            (root / "README.md").write_text("not a migration")
            self.assertEqual(
                repository_versions(root),
                {"20261120150000", "20261120170000"},
            )
            self.assertEqual(
                legacy_migration_files(root),
                ["20261019_legacy_migration.sql"],
            )

    def test_rejects_duplicate_version_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "20261120150000_first.sql").write_text("SELECT 1;")
            (root / "20261120150000_second.sql").write_text("SELECT 1;")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                repository_versions(root)


class TestCompareVersions(unittest.TestCase):

    def test_matching_sets_are_in_sync(self):
        report = compare_versions(
            ["20261120150000", "20261120170000"],
            ["20261120150000", "20261120170000"],
        )
        self.assertEqual(report["status"], "in_sync")
        self.assertEqual(report["missing_in_ledger"], [])
        self.assertEqual(report["ledger_without_repository_file"], [])
        self.assertEqual(report["legacy_8_digit_migrations_requiring_manual_mapping"], [])

    def test_reports_drift_in_both_directions_without_repair(self):
        report = compare_versions(
            ["20261120150000", "20261120170000"],
            ["20261120150000", "20261005113949"],
        )
        self.assertEqual(report["status"], "drift")
        self.assertEqual(report["missing_in_ledger"], ["20261120170000"])
        self.assertEqual(report["ledger_without_repository_file"], ["20261005113949"])
        self.assertEqual(report["legacy_8_digit_migrations_requiring_manual_mapping"], [])


    def test_legacy_migrations_require_manual_mapping(self):
        report = compare_versions(
            ["20261120150000"],
            ["20261120150000"],
            ["20261019_legacy.sql"],
        )
        self.assertEqual(report["status"], "drift")
        self.assertEqual(
            report["legacy_8_digit_migrations_requiring_manual_mapping"],
            ["20261019_legacy.sql"],
        )


if __name__ == "__main__":
    unittest.main()
