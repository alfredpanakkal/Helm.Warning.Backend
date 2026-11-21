#!/usr/bin/env python3
"""Read-only comparison of repository SQL migrations and the Supabase ledger.

This command never applies migrations or repairs ledger entries. It requires
psql and SUPABASE_DB_URL, and reports both directions of migration drift.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations"
LEDGER_QUERY = (
    "SELECT version FROM supabase_migrations.schema_migrations ORDER BY version"
)


def repository_versions(migrations_dir=MIGRATIONS_DIR):
    versions = []
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        version = path.stem.split("_", 1)[0]
        if not version.isdigit() or len(version) not in (8, 14):
            raise ValueError("Migration filename has an unsupported version prefix: " + path.name)
        if len(version) == 14:
            versions.append(version)
    if len(versions) != len(set(versions)):
        raise ValueError("Duplicate 14-digit migration version prefixes found")
    return set(versions)


def legacy_migration_files(migrations_dir=MIGRATIONS_DIR):
    return sorted(
        path.name for path in Path(migrations_dir).glob("*.sql")
        if len(path.stem.split("_", 1)[0]) == 8
    )


def compare_versions(repo_versions, ledger_versions, legacy_files=()):
    repo = {str(version).strip() for version in repo_versions if str(version).strip()}
    ledger = {str(version).strip() for version in ledger_versions if str(version).strip()}
    legacy = sorted(legacy_files)
    in_sync = repo == ledger and not legacy
    return {
        "status": "in_sync" if in_sync else "drift",
        "repository_timestamped_migrations": len(repo),
        "ledger_migrations": len(ledger),
        "missing_in_ledger": sorted(repo - ledger),
        "ledger_without_repository_file": sorted(ledger - repo),
        "legacy_8_digit_migrations_requiring_manual_mapping": legacy,
    }


def main():
    database_url = os.environ.get("SUPABASE_DB_URL")
    if not database_url:
        print("SUPABASE_DB_URL is required; no database query was run.", file=sys.stderr)
        return 2

    try:
        result = subprocess.run(
            ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
             "-c", LEDGER_QUERY],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PGDATABASE": database_url, "PGCONNECT_TIMEOUT": "15"},
        )
    except OSError:
        print("psql is required but was not found; no database query was run.", file=sys.stderr)
        return 2

    if result.returncode != 0:
        # Do not echo psql stderr: it can contain connection details.
        print("Read-only migration-ledger query failed (psql exit "
              + str(result.returncode) + ").", file=sys.stderr)
        return 2

    try:
        report = compare_versions(
            repository_versions(), result.stdout.splitlines(), legacy_migration_files()
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "in_sync" else 1


if __name__ == "__main__":
    sys.exit(main())
