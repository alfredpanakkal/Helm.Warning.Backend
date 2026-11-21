#!/usr/bin/env python3
"""backup_supabase.py — Data export of the allowlisted Supabase tables.

Exports every row of each table in BACKUP_TABLES (an explicit
allowlist — tables are NEVER discovered dynamically, so a table
added later is not silently pulled into a backup artifact) to
backups/<table>.json plus a manifest.json with row counts and the
fetch timestamp. Service key bypasses RLS; pagination is
fail-closed on any HTTP error — a table that 404s or fails fails
the whole run. Run by .github/workflows/supabase-backup.yml
(monthly cron + manual workflow_dispatch).

admin_users is excluded from this JSON allowlist and its table data
is excluded from the optional public-schema pg_dump. The schema may be
restored, but account rows are not exported. When SUPABASE_DB_URL is
configured, the backup workflow restores the dump into a disposable
PostgreSQL/PostGIS database and verifies core objects. Without that
secret, only the JSON data export is validated; it is not a full restore.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Never exported into backup artifacts (auth/credential material).
EXCLUDED_TABLES = {"admin_users"}

# Explicit allowlist: the ONLY tables exported. Derived from the
# repo migrations (20261019 pipeline, 20261020 raw_messages,
# 20261023 lifecycle + paste queue, 20261026 parsing audit) plus the
# live-DB ledger/registry tables (ingestion_generations, pipeline_runs,
# sources_registry). Data tables only — never admin_users (or any
# credential/email table), and views are never listed (they duplicate
# base-table data).
BACKUP_TABLES = (
    "ingestion_generations",
    "manual_ingest_queue",
    "nav_warning_audits",
    "nav_warning_cancellations",
    "nav_warning_charts",
    "nav_warning_entities",
    "nav_warning_geometries",
    "nav_warning_schedules",
    "nav_warnings",
    "parsing_audit_runs",
    "parsing_correction_proposals",
    "pipeline_runs",
    "raw_messages",
    "sources_registry",
)
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60


def _normalize_base_url(url):
    """Project URL -> base URL without a trailing /rest/v1 or slash."""
    base = (url or "").strip().rstrip("/")
    if base.endswith("/rest/v1"):
        base = base[: -len("/rest/v1")]
    return base


def _fetch_all_rows(base_url, key, table):
    """All rows of one table, paginated; raises on any HTTP error."""
    # Lazy import: the unittest job runs a bare interpreter with no pip
    # packages (2026-10-28 live failure: ModuleNotFoundError 'requests');
    # tests import this module for helper assertions only.
    import requests
    rows = []
    offset = 0
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    while True:
        resp = requests.get(
            base_url + "/rest/v1/" + table,
            params={"select": "*", "limit": PAGE_SIZE, "offset": offset},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _sha256_file(path):
    """Return the SHA-256 digest of a completed backup file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup_directory(backup_dir="backups"):
    """Fail closed unless every allowlisted JSON export matches its manifest."""
    manifest_path = os.path.join(backup_dir, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported or missing backup manifest schema_version")
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(BACKUP_TABLES):
        raise ValueError("Backup manifest table set does not match BACKUP_TABLES")

    for table in BACKUP_TABLES:
        entry = tables[table]
        if not isinstance(entry, dict):
            raise ValueError("Invalid backup manifest entry: " + table)
        expected_file = table + ".json"
        if entry.get("file") != expected_file:
            raise ValueError("Unexpected backup file path for " + table)
        path = os.path.join(backup_dir, expected_file)
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise ValueError("Backup table payload is not a JSON array: " + table)
        if entry.get("row_count") != len(rows):
            raise ValueError("Backup row count mismatch: " + table)
        if entry.get("sha256") != _sha256_file(path):
            raise ValueError("Backup checksum mismatch: " + table)
    return True


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        if os.environ.get("ALLOW_DRY_RUN", "").lower() in ("1", "true", "yes"):
            print("ℹ️ SUPABASE_URL/SUPABASE_KEY missing; backup dry-run no-op.")
            return 0
        print("❌ Fatal: SUPABASE_URL and SUPABASE_KEY are required.",
              file=sys.stderr)
        return 1

    base_url = _normalize_base_url(url)

    if set(BACKUP_TABLES) & EXCLUDED_TABLES:
        print("❌ Fatal: BACKUP_TABLES must never include an excluded "
              "table.", file=sys.stderr)
        return 1

    os.makedirs("backups", exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    manifest = {"schema_version": 1, "fetched_at": fetched_at,
                "base_url": base_url, "tables": {}}

    failed = []
    for table in BACKUP_TABLES:
        try:
            rows = _fetch_all_rows(base_url, key, table)
        except Exception as e:
            print("❌ " + table + ": export failed — " + str(e),
                  file=sys.stderr)
            failed.append(table)
            continue
        path = os.path.join("backups", table + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        manifest["tables"][table] = {
            "row_count": len(rows),
            "file": table + ".json",
            "sha256": _sha256_file(path),
        }
        print("  ✔ " + table + ": " + str(len(rows)) + " rows")

    if failed:
        print("❌ Backup INCOMPLETE — failed tables: "
              + ", ".join(failed), file=sys.stderr)
        return 1

    with open(os.path.join("backups", "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    try:
        verify_backup_directory("backups")
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("❌ Backup verification failed: " + str(e), file=sys.stderr)
        return 1

    total = sum(t["row_count"] for t in manifest["tables"].values())
    print("📦 Backup complete: " + str(len(manifest["tables"]))
          + " tables, " + str(total) + " rows total → backups/ (",
          "admin_users excluded by design)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
