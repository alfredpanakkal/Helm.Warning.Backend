#!/usr/bin/env python3
"""
navarea_generic_sync.py — Differential Sync for the universal-parser
regions (NAVAREA II / III / V / VI / VII / IX / X / XIII–XXI).

One wrapper serves all universal regions: the universal parser stamps
'region', 'navarea' and 'source_id' into the parsed JSON's memo block,
and this sync passes them to the shared engine, which is fully
region-agnostic (keyed on source_id). Template: scripts/baltic_sync.py.

Cross-ref CANCEL supersede transitions are NOT applied here (Phase 1
stores cross-refs on the warning payload only).
"""
import os
import json
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared.sync_engine import run_differential_sync


def sync_to_supabase(json_file="navareas/manual/navarea_ii/parsed.json",
                     full_snapshot: bool = True) -> bool:
    """Sync parsed universal-region warnings to Supabase, or no-op dry run
    when credentials are missing.

    full_snapshot=False (a harvest that skipped already-stored rows)
    disables the evidence-based cancel pass in the sync engine: the
    feed is partial BY DESIGN, so absence is not withdrawal evidence."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("ℹ️ SUPABASE_URL or SUPABASE_KEY missing; skipping universal "
              "sync in dry-run mode.")
        return True

    if not os.path.isabs(json_file):
        json_file = os.path.join(ROOT_DIR, json_file)

    if not os.path.exists(json_file):
        print("❌ Error: Parsed file " + json_file + " does not exist.", file=sys.stderr)
        return False

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("❌ Error reading JSON file " + json_file + ": " + str(e), file=sys.stderr)
        return False

    memo = data.get("memo") or {}
    source_id = memo.get("source_id")
    navarea = memo.get("navarea")
    if not source_id or not navarea:
        print("❌ Error: parsed JSON memo lacks source_id/navarea — cannot "
              "determine the region for sync. Re-run the universal parser "
              "to regenerate it.", file=sys.stderr)
        return False

    scraped_messages = data.get("raw_messages", [])
    scraped_warnings = data.get("nav_warnings", [])

    return run_differential_sync(
        source_id=source_id,
        # AUSCOAST pseudo-regions carry a display-ready navarea label
        # ('AUSCOAST B'); NAVAREA regions keep the 'NAVAREA ' prefix.
        navarea_name=(navarea if navarea.startswith("AUSCOAST")
                      else "NAVAREA " + navarea),
        scraped_warnings=scraped_warnings,
        scraped_messages=scraped_messages,
        full_snapshot=full_snapshot,
    )


if __name__ == "__main__":
    success = sync_to_supabase()
    sys.exit(0 if success else 1)
