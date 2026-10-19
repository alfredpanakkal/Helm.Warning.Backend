#!/usr/bin/env python3
"""
baltic_sync.py — Differential Sync Engine for Baltic Warnings
"""

import os
import json
import sys
from typing import Dict, List, Tuple, Set, Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import compute_differential

SOURCE_ID = "sma-baltic-subarea"
VALID_RAW_COLUMNS = {"warning_id", "source_id", "subject_header",
                      "full_raw_text", "received_timestamp", "checksum_sha256"}
VALID_NAV_COLUMNS = {"warning_id", "source_id", "navarea", "title",
                    "issued_text", "coordinates", "latitude", "longitude",
                    "category", "status", "raw_text"}


def sync_to_supabase(json_file="navareas/baltic/parsed_baltic_warnings.json"):
    print("=" * 65)
    print("⚡ Baltic Differential Sync Engine")
    print("=" * 65)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("⚠️ SUPABASE_URL or SUPABASE_KEY missing, skipping sync")
        return True
    try:
        from supabase import create_client
        supabase = create_client(url, key)
    except Exception as e:
        print(f"❌ Supabase client error: {e}")
        return False
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: {json_file} not found")
        return False
    scraped_messages = data.get("raw_messages", [])
    scraped_warnings = data.get("nav_warnings", [])
    print("\n[1/4] Checking database state...")
    try:
        res_warn = supabase.table("nav_warnings").select("warning_id, status, raw_text").eq("source_id", SOURCE_ID).execute()
        existing_warnings = {r["warning_id"]: r for r in (res_warn.data or [])}
    except Exception as e:
        print(f"❌ Query error: {e}")
        return False
    try:
        res_raw = supabase.table("raw_messages").select("warning_id, checksum_sha256").eq("source_id", SOURCE_ID).execute()
        existing_checksums = {(r["warning_id"], r["checksum_sha256"]) for r in (res_raw.data or [])}
    except Exception as e:
        print(f"❌ Query error: {e}")
        return False
    print(f"  ✔ Found {len(existing_warnings)} existing warnings")
    print(f"  ✔ Found {len(existing_checksums)} existing checksums")
    # Even with an empty harvest we must run the differential so that
    # previously active warnings missing from the feed are cancelled.
    diff = compute_differential(scraped_warnings, scraped_messages, existing_warnings, existing_checksums)
    print(f"\n[2/4] Differential: {len(diff['skip'])} skip, {len(diff['new'])} new, {len(diff['update'])} update, {len(diff['cancel'])} cancel")
    has_errors = False
    to_write = diff["new"] + diff["update"]
    if to_write:
        print(f"\n[3/4] Syncing {len(to_write)} records...")
        # Batched writes. A failed raw_messages insert breaks future Skip
        # detection (missing checksum => permanent rewrites), so it is fatal.
        clean_msgs = [{k: v for k, v in msg.items() if k in VALID_RAW_COLUMNS}
                      for warn, msg in to_write if msg]
        if clean_msgs:
            try:
                supabase.table("raw_messages").insert(clean_msgs).execute()
                print(f"  ✅ [raw_messages] inserted {len(clean_msgs)} rows")
            except Exception as e:
                print(f"  ❌ [raw_messages] batch insert failed: {e}")
                has_errors = True
        clean_warns = [{k: v for k, v in warn.items() if k in VALID_NAV_COLUMNS}
                        for warn, msg in to_write]
        try:
            supabase.table("nav_warnings").upsert(clean_warns, on_conflict="warning_id,source_id").execute()
            print(f"  ✨ Upserted {len(clean_warns)} warnings")
        except Exception as e:
            print(f"  ❌ [nav_warnings] batch upsert failed: {e}")
            has_errors = True
    if diff["cancel"]:
        print(f"\n[4/4] Canceling {len(diff['cancel'])} warnings...")
        try:
            supabase.table("nav_warnings").update({"status": "cancelled"}).eq("source_id", SOURCE_ID).in_("warning_id", diff["cancel"]).execute()
            print(f"  🗑️ Cancelled {len(diff['cancel'])} warnings")
        except Exception as e:
            print(f"  ❌ Cancel batch failed: {e}")
            has_errors = True
    print("\n" + "=" * 65)
    print(f"📊 Summary: {len(scraped_warnings)} harvested, {len(diff['skip'])} skip, {len(diff['new'])} new, {len(diff['update'])} update, {len(diff['cancel'])} cancel")
    print("=" * 65)
    if has_errors:
        return False
    print("🎉 Sync completed!")
    return True


if __name__ == "__main__":
    success = sync_to_supabase()
    sys.exit(0 if success else 1)
