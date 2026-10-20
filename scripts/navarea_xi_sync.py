#!/usr/bin/env python3
"""
navarea_xi_sync.py — Differential Sync Engine for NAVAREA XI Warnings
Conforms to 20261019/20261020 Schema & Atomic RPC Upsert
"""

import os
import json
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.sync_engine import run_differential_sync

SOURCE_ID = "kaiho-navarea-xi"

def sync_to_supabase(json_file="navareas/navarea_xi/parsed_navarea_xi_warnings.json") -> bool:
    if not os.path.isabs(json_file):
        json_file = os.path.join(ROOT_DIR, json_file)

    if not os.path.exists(json_file):
        print(f"❌ Error: {json_file} not found", file=sys.stderr)
        return False

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error reading {json_file}: {e}", file=sys.stderr)
        return False

    scraped_messages = data.get("raw_messages", [])
    scraped_warnings = data.get("nav_warnings", [])

    return run_differential_sync(
        source_id=SOURCE_ID,
        navarea_name="NAVAREA XI",
        scraped_warnings=scraped_warnings,
        scraped_messages=scraped_messages
    )


if __name__ == "__main__":
    success = sync_to_supabase()
    sys.exit(0 if success else 1)
