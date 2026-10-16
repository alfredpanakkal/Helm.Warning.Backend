#!/usr/bin/env python3
"""
shared/sync.py - Differential synchronization engine for Supabase
Provides smart differential sync that:
- Skips unchanged records
- Inserts new bulletins
- Updates revised bulletins
- Marks cancelled warnings that disappear from source
"""

import os
import sys
import json
from typing import Dict, List, Tuple, Set, Any, Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import filter_dict_keys

class DifferentialSyncEngine:
    """
    Engine for performing differential synchronization with Supabase.
    """

    def __init__(self, source_id: str, valid_raw_columns: set, valid_nav_columns: set):
        self.source_id = source_id
        self.valid_raw_columns = valid_raw_columns
        self.valid_nav_columns = valid_nav_columns
        self.supabase = None

    def initialize_supabase(self) -> bool:
        """Initialize Supabase client from environment variables."""
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            print("\u26a0\ufe0f Notice: SUPABASE_URL or SUPABASE_KEY environment variables are missing.")
            print("Skipping database sync.")
            return False

        try:
            from supabase import create_client, Client
            self.supabase: Client = create_client(url, key)
            return True
        except Exception as e:
            print(f"\u274c Error initializing Supabase client: {e}")
            return False

    def compute_differential(
        self,
        scraped_warnings: List[Dict[str, Any]],
        scraped_messages: List[Dict[str, Any]],
        existing_warnings: Dict[str, Dict[str, Any]],
        existing_checksums: Set[Tuple[str, str]]
    ) -> Dict[str, Any]:
        """Compute differential actions between scraped data and current database state."""
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

    def get_existing_state(self) -> Tuple[Dict[str, Dict[str, Any]], Set[Tuple[str, str]]]:
        """Fetch existing warnings and checksums from Supabase."""
        if not self.supabase:
            return {}, set()

        try:
            res_warn = self.supabase.table("nav_warnings") \
                .select("warning_id, status, raw_text") \
                .eq("source_id", self.source_id) \
                .execute()
            existing_warnings = {r["warning_id"]: r for r in (res_warn.data or [])}
        except Exception as e:
            print(f"\u274c Failed to query existing 'nav_warnings': {e}")
            existing_warnings = {}

        try:
            res_raw = self.supabase.table("raw_messages") \
                .select("warning_id, checksum_sha256") \
                .eq("source_id", self.source_id) \
                .execute()
            existing_checksums = {(r["warning_id"], r["checksum_sha256"]) for r in (res_raw.data or [])}
        except Exception as e:
            print(f"\u274c Failed to query existing 'raw_messages': {e}")
            existing_checksums = set()

        return existing_warnings, existing_checksums

    def sync_to_supabase(self, json_file: str, output_filename: Optional[str] = None) -> bool:
        """Perform differential synchronization with Supabase."""
        print("=" * 65)
        print(f"\u26a1 {self.source_id} Navigational Warnings Differential Sync Engine")
        print("=" * 65)

        if not self.initialize_supabase():
            return True

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"\u274c Error: {json_file} not found.")
            return False

        scraped_messages = data.get("raw_messages", [])
        scraped_warnings = data.get("nav_warnings", [])

        if not scraped_warnings and not scraped_messages:
            print("\u2139\ufe0f No warnings found in harvest payload to synchronize.")
            return True

        print(f"\n[1/4] Inspecting current database state for source '{self.source_id}'...")

        existing_warnings, existing_checksums = self.get_existing_state()

        print(f"  \u2022 Found {len(existing_warnings)} existing bulletins in 'nav_warnings'")
        print(f"  \u2022 Found {len(existing_checksums)} distinct audit records in 'raw_messages'")

        diff = self.compute_differential(
            scraped_warnings,
            scraped_messages,
            existing_warnings,
            existing_checksums
        )

        print(f"\n[2/4] Differential Evaluation:")
        print(f"  \u2022 Unchanged (will skip)    : {len(diff['skip'])}")
        print(f"  \u2022 New to add               : {len(diff['new'])}")
        print(f"  \u2022 Revised to update        : {len(diff['update'])}")
        print(f"  \u2022 Dropped (mark cancelled) : {len(diff['cancel'])}")

        for wid in diff["skip"]:
            print(f"  \u23ed\ufe0f [SKIP] {wid}: Unchanged")

        has_errors = False

        to_write = diff["new"] + diff["update"]
        if to_write:
            print(f"\n[3/4] Synchronizing {len(to_write)} new/updated record(s) to Supabase...")
            for warn, msg in to_write:
                wid = warn["warning_id"]
                action_label = "NEW" if (warn, msg) in diff["new"] else "UPDATE"

                if msg:
                    clean_msg = filter_dict_keys(msg, self.valid_raw_columns)
                    try:
                        self.supabase.table("raw_messages").insert(clean_msg).execute()
                        print(f"  \u2705 [raw_messages] Logged audit trail for {wid}")
                    except Exception as e:
                        print(f"  \u2139\ufe0f [raw_messages] Notice for {wid}: {e}")

                clean_warn = filter_dict_keys(warn, self.valid_nav_columns)
                try:
                    self.supabase.table("nav_warnings").upsert(
                        clean_warn, on_conflict="warning_id,source_id"
                    ).execute()
                    print(f"  \u2728 [{action_label}] Upserted {wid} ({warn.get('category')}) to nav_warnings")
                except Exception as e:
                    print(f"  \u274c [nav_warnings] Error upserting {wid}: {e}")
                    has_errors = True
        else:
            print(f"\n[3/4] No new or updated bulletins to write.")

        if diff["cancel"]:
            print(f"\n[4/4] Processing {len(diff['cancel'])} cancelled bulletin(s)...")
            for wid in diff["cancel"]:
                try:
                    self.supabase.table("nav_warnings") \
                        .update({"status": "cancelled"}) \
                        .eq("source_id", self.source_id) \
                        .eq("warning_id", wid) \
                        .execute()
                    print(f"  \ud83d\uded1 [CANCELLED] {wid}")
                except Exception as e:
                    print(f"  \u274c Error marking {wid} cancelled: {e}")
                    has_errors = True
        else:
            print(f"\n[4/4] Zero bulletins marked cancelled.")

        print("\n" + "=" * 65)
        print("\ud83d\udcca DIFFERENTIAL SYNCHRONIZATION SUMMARY:")
        print(f"   \u2022 Total Harvested  : {len(scraped_warnings)}")
        print(f"   \u2022 Skipped          : {len(diff['skip'])}")
        print(f"   \u2022 New Added        : {len(diff['new'])}")
        print(f"   \u2022 Updated          : {len(diff['update'])}")
        print(f"   \u2022 Cancelled        : {len(diff['cancel'])}")
        print("=" * 65)

        if has_errors:
            print("\u274c Differential synchronization completed with errors!")
            return False
        else:
            print("\ud83c\udf89 Differential synchronization completed with 0 errors!")
            return True

def sync_to_supabase(
    json_file: str,
    source_id: str,
    valid_raw_columns: set,
    valid_nav_columns: set,
    output_filename: Optional[str] = None
) -> bool:
    """Convenience function to perform differential sync."""
    engine = DifferentialSyncEngine(source_id, valid_raw_columns, valid_nav_columns)
    return engine.sync_to_supabase(json_file, output_filename)
