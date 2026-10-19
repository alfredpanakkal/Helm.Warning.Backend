#!/usr/bin/env python3
"""
baltic_sync.py — Differential Sync Engine for Baltic Warnings
Hardened differential sync against Supabase with strict schema filtering and detailed diagnostics.
"""

import os
import json
import sys
from typing import Dict, List, Tuple, Set, Any

# Ensure repo root is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import compute_differential

SOURCE_ID = "sma-baltic-subarea"
VALID_RAW_COLUMNS = {
    "warning_id", "source_id", "subject_header",
    "full_raw_text", "received_timestamp", "checksum_sha256"
}
VALID_NAV_COLUMNS = {
    "warning_id", "source_id", "navarea", "title",
    "issued_text", "coordinates", "latitude", "longitude",
    "category", "status", "raw_text"
}


def validate_raw_message(msg: Dict[str, Any]) -> bool:
    """Validate that required fields exist and are non-empty for raw_messages."""
    if not isinstance(msg, dict):
        return False
    if not msg.get("warning_id") or not str(msg["warning_id"]).strip():
        return False
    if not msg.get("source_id") or not str(msg["source_id"]).strip():
        return False
    if not msg.get("checksum_sha256") or not str(msg["checksum_sha256"]).strip():
        return False
    return True


def validate_nav_warning(warn: Dict[str, Any]) -> bool:
    """Validate that required fields exist and are non-empty for nav_warnings."""
    if not isinstance(warn, dict):
        return False
    if not warn.get("warning_id") or not str(warn["warning_id"]).strip():
        return False
    if not warn.get("source_id") or not str(warn["source_id"]).strip():
        return False
    return True


def sync_to_supabase(json_file="navareas/baltic/parsed_baltic_warnings.json") -> bool:
    print("=" * 65)
    print("⚡ Baltic Differential Sync Engine")
    print("=" * 65)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("⚠️ SUPABASE_URL or SUPABASE_KEY missing in environment variables. Database sync skipped (dry-run mode).")
        return True

    try:
        from supabase import create_client
        supabase = create_client(url, key)
    except Exception as e:
        print(f"❌ Failed to initialize Supabase client: {e}")
        return False

    if not os.path.exists(json_file):
        print(f"❌ Error: Parsed file {json_file} does not exist.")
        return False

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error reading JSON file {json_file}: {e}")
        return False

    scraped_messages = data.get("raw_messages", [])
    scraped_warnings = data.get("nav_warnings", [])

    print("\n[1/4] Checking remote database state...")
    try:
        res_warn = supabase.table("nav_warnings").select("warning_id, status, raw_text").eq("source_id", SOURCE_ID).execute()
        existing_warnings = {r["warning_id"]: r for r in (res_warn.data or []) if isinstance(r, dict) and "warning_id" in r}
    except Exception as e:
        print(f"❌ DB query failed on 'nav_warnings': {e}")
        return False

    try:
        res_raw = supabase.table("raw_messages").select("warning_id, checksum_sha256").eq("source_id", SOURCE_ID).execute()
        existing_checksums = {(r["warning_id"], r["checksum_sha256"]) for r in (res_raw.data or []) if isinstance(r, dict) and "warning_id" in r and "checksum_sha256" in r}
    except Exception as e:
        print(f"❌ DB query failed on 'raw_messages': {e}")
        return False

    print(f"  ✔ Found {len(existing_warnings)} existing warnings in database")
    print(f"  ✔ Found {len(existing_checksums)} existing checksums in database")

    # Differential calculation: handles both populated feeds and empty feeds
    diff = compute_differential(scraped_warnings, scraped_messages, existing_warnings, existing_checksums)
    print(f"\n[2/4] Differential Analysis: {len(diff['skip'])} skip, {len(diff['new'])} new, {len(diff['update'])} update, {len(diff['cancel'])} cancel")

    has_errors = False
    to_write = diff["new"] + diff["update"]

    if to_write:
        print(f"\n[3/4] Syncing {len(to_write)} records...")

        # 1. Prepare and validate raw_messages
        clean_msgs = []
        for warn, msg in to_write:
            if not msg:
                continue
            if not validate_raw_message(msg):
                print(f"  ⚠️ Warning: Skipping malformed raw_message: {msg.get('warning_id')}")
                continue
            clean_msgs.append({k: v for k, v in msg.items() if k in VALID_RAW_COLUMNS})

        if clean_msgs:
            try:
                supabase.table("raw_messages").insert(clean_msgs).execute()
                print(f"  ✅ [raw_messages] Inserted {len(clean_msgs)} audit records")
            except Exception as e:
                print(f"  ❌ [raw_messages] Batch insert failed: {e}")
                has_errors = True

        # 2. Prepare and validate nav_warnings
        clean_warns = []
        for warn, msg in to_write:
            if not validate_nav_warning(warn):
                print(f"  ⚠️ Warning: Skipping malformed nav_warning: {warn.get('warning_id')}")
                continue
            clean_warns.append({k: v for k, v in warn.items() if k in VALID_NAV_COLUMNS})

        if clean_warns:
            try:
                supabase.table("nav_warnings").upsert(clean_warns, on_conflict="warning_id,source_id").execute()
                print(f"  ✨ [nav_warnings] Upserted {len(clean_warns)} warnings")
            except Exception as e:
                print(f"  ❌ [nav_warnings] Batch upsert failed: {e}")
                has_errors = True
    else:
        print("\n[3/4] No new or updated records to sync.")

    if diff["cancel"]:
        print(f"\n[4/4] Canceling {len(diff['cancel'])} obsolete warnings...")
        try:
            supabase.table("nav_warnings").update({"status": "cancelled"}).eq("source_id", SOURCE_ID).in_("warning_id", diff["cancel"]).execute()
            print(f"  🗑️ Cancelled {len(diff['cancel'])} obsolete warnings")
        except Exception as e:
            print(f"  ❌ [nav_warnings] Cancel batch failed: {e}")
            has_errors = True
    else:
        print("\n[4/4] No active warnings to cancel.")

    print("\n" + "=" * 65)
    print(f"📊 Summary: {len(scraped_warnings)} harvested, {len(diff['skip'])} skipped, {len(diff['new'])} new, {len(diff['update'])} updated, {len(diff['cancel'])} cancelled")
    print("=" * 65)

    if has_errors:
        print("❌ Sync finished with one or more batch errors.")
        return False

    print("🎉 Baltic differential sync completed successfully!")
    return True


if __name__ == "__main__":
    success = sync_to_supabase()
    sys.exit(0 if success else 1)

