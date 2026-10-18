#!/usr/bin/env python3
"""
supabase_sync.py — Smart Differential Synchronization Engine for Baltic Warnings
Performs differential synchronization with Supabase.
"""

import os
import json
import sys
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Set, Any

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

SOURCE_ID = "sma-baltic-subarea"

VALID_RAW_MESSAGE_COLUMNS = {
    "warning_id", "source_id", "subject_header",
    "full_raw_text", "received_timestamp", "checksum_sha256"
}

VALID_NAV_WARNING_COLUMNS = {
    "warning_id", "source_id", "navarea", "title",
    "issued_text", "coordinates", "latitude", "longitude",
    "category", "status", "raw_text"
}

def compute_differential(
    scraped_warnings: List[Dict[str, Any]],
    scraped_messages: List[Dict[str, Any]],
    existing_warnings: Dict[str, Dict[str, Any]],
    existing_checksums: Set[Tuple[str, str]]
) -> Dict[str, Any]:
    msg_map = {m["warning_id"]: m for m in scraped_messages}

    to_skip = []
    to_insert_new = []
    to_update = []

    seen_ids = set()

    for warn in scraped_warnings:
        wid = warn["warning_id"]
        seen_ids.add(wid)
        raw_msg = msg_map.get(wid, {})
        chk = raw_msg.get("checksum_sha256", "")

        existing_record = existing_warnings.get(wid)

        if existing_record:
            is_active = existing_record.get("status") == "active"
            checksum_matches = (wid, chk) in existing_checksums

            if is_active and checksum_matches:
                to_skip.append(wid)
            else:
                to_update.append((warn, raw_msg))
        else:
            to_insert_new.append((warn, raw_msg))

    to_cancel = [
        wid for wid, record in existing_warnings.items()
        if record.get("status") == "active" and wid not in seen_ids
    ]

    return {
        "skip": to_skip,
        "new": to_insert_new,
        "update": to_update,
        "cancel": to_cancel
    }

def sync_to_supabase(json_file="parsed_warnings.json"):
    print("=" * 65)
    print("⚡ Baltic Navigational Warnings Differential Sync Engine")
    print("=" * 65)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("⚠️ Notice: SUPABASE_URL or SUPABASE_KEY environment variables are missing.")
        print("Skipping database sync. (Configure secrets on GitHub / locally to enable)")
        return

    try:
        from supabase import create_client, Client
        supabase: Client = create_client(url, key)
    except Exception as e:
        print(f"❌ Error initializing Supabase client: {e}")
        sys.exit(1)

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: {json_file} not found.")
        sys.exit(1)

    scraped_messages = data.get("raw_messages", [])
    scraped_warnings = data.get("nav_warnings", [])

    if not scraped_warnings and not scraped_messages:
        print("❓ No warnings found in harvest payload to synchronize.")
        return

    print(f"\n[1/4] Inspecting current database state for source '{SOURCE_ID}'...")

    try:
        res_warn = supabase.table("nav_warnings") \
            .select("warning_id, status, raw_text") \
            .eq("source_id", SOURCE_ID) \
            .execute()
        existing_warnings = {r["warning_id"]: r for r in (res_warn.data or [])}
    except Exception as e:
        print(f"❌ Failed to query existing 'nav_warnings': {e}")
        sys.exit(1)

    try:
        res_raw = supabase.table("raw_messages") \
            .select("warning_id, checksum_sha256") \
            .eq("source_id", SOURCE_ID) \
            .execute()
        existing_checksums = {(r["warning_id"], r["checksum_sha256"]) for r in (res_raw.data or [])}
    except Exception as e:
        print(f"❌ Failed to query existing 'raw_messages': {e}")
        sys.exit(1)

    print(f"  ✔ Found {len(existing_warnings)} existing bulletins in 'nav_warnings'")
    print(f"  ✔ Found {len(existing_checksums)} distinct audit records in 'raw_messages'")

    diff = compute_differential(
        scraped_warnings,
        scraped_messages,
        existing_warnings,
        existing_checksums
    )

    print(f"\n[2/4] Differential Evaluation:")
    print(f"  ✔ Unchanged (will skip)    : {len(diff['skip'])}")
    print(f"  ✔ New to add               : {len(diff['new'])}")
    print(f"  ✔ Revised to update        : {len(diff['update'])}")
    print(f"  ✔ Dropped (mark cancelled) : {len(diff['cancel'])}")

    for wid in diff["skip"]:
        print(f"  ⏭️ [SKIP] {wid}: Unchanged (already current in Supabase)")

    has_errors = False

    to_write = diff["new"] + diff["update"]
    if to_write:
        print(f"\n[3/4] Synchronizing {len(to_write)} new/updated record(s) to Supabase...")
        for warn, msg in to_write:
            wid = warn["warning_id"]
            action_label = "NEW" if (warn, msg) in diff["new"] else "UPDATE"

            if msg:
                clean_msg = {k: v for k, v in msg.items() if k in VALID_RAW_MESSAGE_COLUMNS}
                try:
                    supabase.table("raw_messages").insert(clean_msg).execute()
                    print(f"  ✅ [raw_messages] Logged audit trail for {wid}")
                except Exception as e:
                    print(f"  ❓ [raw_messages] Notice for {wid}: {e}")

            clean_warn = {k: v for k, v in warn.items() if k in VALID_NAV_WARNING_COLUMNS}
            try:
                supabase.table("nav_warnings").upsert(clean_warn, on_conflict="warning_id,source_id").execute()
                print(f"  ✨ [{action_label}] Upserted {wid} ({warn.get('category')}) to nav_warnings")
            except Exception as e:
                print(f"  ❌ [nav_warnings] Error upserting {wid}: {e}")
                has_errors = True
    else:
        print(f"\n[3/4] No new or updated bulletins to write. Database writes skipped.")

    if diff["cancel"]:
        print(f"\n[4/4] Processing {len(diff['cancel'])} cancelled bulletin(s)...")
        for wid in diff["cancel"]:
            try:
                supabase.table("nav_warnings") \
                    .update({"status": "cancelled"}) \
                    .eq("source_id", SOURCE_ID) \
                    .eq("warning_id", wid) \
                    .execute()
                print(f"  🗑️ [CANCELLED] {wid}: No longer on VHF broadcast, marked cancelled.")
            except Exception as e:
                print(f"  ❌ Error marking {wid} cancelled: {e}")
                has_errors = True
    else:
        print(f"\n[4/4] Zero bulletins marked cancelled.")

    print("\n" + "=" * 65)
    print("📊 DIFFERENTIAL SYNCHRONIZATION SUMMARY:")
    print(f"   ✔ Total Harvested  : {len(scraped_warnings)}")
    print(f"   ✔ Skipped          : {len(diff['skip'])}")
    print(f"   ✔ New Added        : {len(diff['new'])}")
    print(f"   ✔ Updated          : {len(diff['update'])}")
    print(f"   ✔ Cancelled        : {len(diff['cancel'])}")
    print("=" * 65)

    if has_errors:
        sys.exit(1)
    else:
        print("🎉 Differential synchronization completed with 0 errors!")

if __name__ == "__main__":
    sync_to_supabase()
