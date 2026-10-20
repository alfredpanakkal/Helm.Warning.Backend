#!/usr/bin/env python3
"""
baltic_sync.py — Differential Sync Engine for Baltic Warnings
Conforms to 20261019/20261020 Schema & Atomic RPC Upsert
"""

import os
import json
import sys
from typing import Dict, Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.sync_engine import run_differential_sync, VALID_RAW_COLUMNS

SOURCE_ID = "sma-baltic-subarea"

VALID_NAV_COLUMNS = {
    "warning_id", "canonical_id", "source_id", "navarea", "title",
    "issued_text", "coordinates", "latitude", "longitude",
    "category", "categories", "status", "raw_text", "spatial",
    "data_quality", "triage_tier", "parsing_method", "qa_flags",
    "unplotted_reason", "shoal_depth_m", "tow_length_m", "tow_speed_kts",
    "applicable_vessel_filter"
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
    if not (warn.get("warning_id") or warn.get("canonical_id")):
        return False
    if not warn.get("source_id"):
        return False
    return True


def sync_to_supabase(json_file="navareas/baltic/parsed_baltic_warnings.json") -> bool:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        strict = os.environ.get("STRICT_CREDENTIALS", "").lower() in ("1", "true", "yes")
        if strict:
            print("❌ FATAL: SUPABASE_URL or SUPABASE_KEY missing", file=sys.stderr)
            return False
        print("⚠️ SUPABASE_URL or SUPABASE_KEY missing in environment variables. Database sync skipped (dry-run mode).")
        return True

    if not os.path.isabs(json_file):
        json_file = os.path.join(ROOT_DIR, json_file)

    if not os.path.exists(json_file):
        print(f"❌ Error: Parsed file {json_file} does not exist.", file=sys.stderr)
        return False

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error reading JSON file {json_file}: {e}", file=sys.stderr)
        return False

    scraped_messages = data.get("raw_messages", [])
    scraped_warnings = data.get("nav_warnings", [])

    return run_differential_sync(
        source_id=SOURCE_ID,
        navarea_name="NAVAREA BALTIC",
        scraped_warnings=scraped_warnings,
        scraped_messages=scraped_messages
    )


if __name__ == "__main__":
    success = sync_to_supabase()
    sys.exit(0 if success else 1)
