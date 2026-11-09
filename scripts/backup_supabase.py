#!/usr/bin/env python3
"""backup_supabase.py — Full-data export of every Supabase table.

Insurance backup against data loss: walks the PostgREST OpenAPI
root to discover every readable table/view, then exports ALL rows
(service key bypasses RLS; paginated, fail-closed on any HTTP
error) to backups/<table>.json plus a manifest.json with row
counts and the fetch timestamp. Run by .github/workflows/
supabase-backup.yml (monthly cron + manual workflow_dispatch).

admin_users is EXCLUDED by name so credentials/emails never leave
Supabase in a backup artifact. ALLOW_DRY_RUN=1 (PR CI) makes the
script a credential-check no-op.
"""
import json
import os
import sys
from datetime import datetime, timezone

import requests

# Never exported into backup artifacts (auth/credential material).
EXCLUDED_TABLES = {"admin_users"}
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60


def _normalize_base_url(url):
    """Project URL -> base URL without a trailing /rest/v1 or slash."""
    base = (url or "").strip().rstrip("/")
    if base.endswith("/rest/v1"):
        base = base[: -len("/rest/v1")]
    return base


def _extract_table_names(openapi):
    """Readable table/view names from the PostgREST OpenAPI root.

    Only paths exposing a GET operation are included, so RPC-only
    paths (POST, e.g. admin_save_nav_warning) are never fetched.
    """
    names = set()
    for path, ops in (openapi.get("paths") or {}).items():
        if isinstance(ops, dict) and "get" in ops:
            parts = str(path).strip("/").split("/")
            if len(parts) == 1 and parts[0]:
                names.add(parts[0])
    return sorted(names - EXCLUDED_TABLES)


def _fetch_all_rows(base_url, key, table):
    """All rows of one table, paginated; raises on any HTTP error."""
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
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    try:
        root = requests.get(base_url + "/rest/v1/", headers=headers,
                            timeout=REQUEST_TIMEOUT)
        root.raise_for_status()
        tables = _extract_table_names(root.json())
    except Exception as e:
        print("❌ Fatal: could not discover tables via PostgREST root: "
              + str(e), file=sys.stderr)
        return 1

    if not tables:
        print("❌ Fatal: PostgREST root exposed no readable tables.",
              file=sys.stderr)
        return 1

    os.makedirs("backups", exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    manifest = {"fetched_at": fetched_at, "base_url": base_url,
                "tables": {}}

    failed = []
    for table in tables:
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
        manifest["tables"][table] = {"row_count": len(rows),
                                     "file": path}
        print("  ✔ " + table + ": " + str(len(rows)) + " rows")

    if failed:
        print("❌ Backup INCOMPLETE — failed tables: "
              + ", ".join(failed), file=sys.stderr)
        return 1

    with open(os.path.join("backups", "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    total = sum(t["row_count"] for t in manifest["tables"].values())
    print("📦 Backup complete: " + str(len(manifest["tables"]))
          + " tables, " + str(total) + " rows total → backups/ (",
          "admin_users excluded by design)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
