#!/usr/bin/env python3
"""
navarea_xi_sync.py — Differential Sync Engine for NAVAREA XI Warnings
"""

import os
import json
import sys
from typing import Dict, List, Tuple, Set, Any

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import compute_differential

SOURCE_ID = "kaiho-navarea-xi"
VALID_RAW_COLUMNS = {"warning_id", "source_id", "subject_header",
                     "full_raw_text", "received_timestamp", "checksum_sha256"}
VALID_NAV_COLUMNS = {"warning_id", "source_id", "navarea", "title",
                    "issued_text", "coordinates", "latitude", "longitude",
                    "category", "status", "raw_text"}


def sync_to_supabase(json_file="navareas/navarea_xi/parsed_navarea_xi_warnings.json"):
    print("=" * 65)
    print("⚡ NAVAREA XI Differential Sync Engine")
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
    if not scraped_warnings:
        print("❓ No warnings to sync")
        return True
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
    diff = compute_differential(scraped_warnings, scraped_messages, existing_warnings, existing_checksums)
    print(f"\n[2/4] Differential: {len(diff['skip'])} skip, {len(diff['new'])} new, {len(diff['update'])} update, {len(diff['cancel'])} cancel")
    has_errors = False
    to_write = diff["new"] + diff["update"]
    if to_write:
        print(f"\n[3/4] Syncing {len(to_write)} records...")
        for warn, msg in to_write:
            wid = warn["warning_id"]
            if msg:
                clean_msg = {k: v for k, v in msg.items() if k in VALID_RAW_COLUMNS}
                try:
                    supabase.table("raw_messages").insert(clean_msg).execute()
                    print(f"  ✅ [raw_messages] {wid}")
                except Exception as e:
                    print(f"  ❓ [raw_messages] {wid}: {e}")
            clean_warn = {k: v for k, v in warn.items() if k in VALID_NAV_COLUMNS}
            try:
                supabase.table("nav_warnings").upsert(clean_warn, on_conflict="warning_id,source_id").execute()
                print(f"  ✨ {wid}")
            except Exception as e:
                print(f"  ❌ {wid}: {e}")
                has_errors = True
    if diff["cancel"]:
        print(f"\n[4/4] Canceling {len(diff['cancel'])} warnings...")
        for wid in diff["cancel"]:
            try:
                supabase.table("nav_warnings").update({"status": "cancelled"}).eq("source_id", SOURCE_ID).eq("warning_id", wid).execute()
                print(f"  🗑️ {wid}")
            except Exception as e:
                print(f"  ❌ {wid}: {e}")
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
