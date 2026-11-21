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
        if not version.isdigit():
            raise ValueError("Migration filename has no numeric version: " + path.name)
        versions.append(version)
    if len(versions) != len(set(versions)):
        raise ValueError("Duplicate migration version prefixes found")
    return set(versions)


def compare_versions(repo_versions, ledger_versions):
    repo = {str(version).strip() for version in repo_versions if str(version).strip()}
    ledger = {str(version).strip() for version in ledger_versions if str(version).strip()}
    return {
        "status": "in_sync" if repo == ledger else "drift",
        "repository_migrations": len(repo),
        "ledger_migrations": len(ledger),
        "missing_in_ledger": sorted(repo - ledger),
        "ledger_without_repository_file": sorted(ledger - repo),
    }


def main():
    database_url = os.environ.get("SUPABASE_DB_URL")
    if not database_url:
        print("SUPABASE_DB_URL is required; no database query was run.", file=sys.stderr)
        return 2

    try:
        result = subprocess.run(
            ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
             database_url, "-c", LEDGER_QUERY],
            check=False,
            capture_output=True,
            text=True,
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
        report = compare_versions(repository_versions(), result.stdout.splitlines())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "in_sync" else 1


if __name__ == "__main__":
    sys.exit(main())
