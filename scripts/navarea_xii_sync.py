#!/usr/bin/env python3
"""
navarea_xii_sync.py — Differential Sync Engine for NAVAREA XII Warnings
Conforms to 20261019/20261020 Schema & Atomic RPC Upsert.

After the standard differential sync, applies the NAVAREA XII cross-reference
contract decided in the preprocessing review:
  - body "CANCEL NAVAREA XII n/yy" and header-paren refs mark the referenced
    warnings SUPERSEDED (a referenced warning still listed in-force in the
    memo keeps status active until it disappears from the memo).
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

from shared.sync_engine import run_differential_sync, get_supabase_client

SOURCE_ID = "nga-navarea-xii"
NAVAREA_ID = "XII"


def _supersede_cross_refs(supabase_client, nav_warnings) -> bool:
    """Marks warnings referenced by CANCEL/header-paren cross-refs SUPERSEDED."""
    refs = {}
    for warn in nav_warnings:
        for ref in warn.get("cross_refs") or []:
            cid = "NAVAREA XII %s/%s" % (ref["number"], ref["year"])
            refs[cid] = ref
    if not refs or supabase_client is None:
        return True

    print(f"\n🔗 Cross-references: {len(refs)} referenced warning(s) to mark SUPERSEDED...")
    has_errors = False
    for cid in sorted(refs):
        try:
            res = (
                supabase_client.table("nav_warnings")
                .select("canonical_id, status")
                .eq("canonical_id", cid)
                .eq("source_id", SOURCE_ID)
                .execute()
            )
            rows = res.data or []
            if not rows:
                print(f"  ℹ️ {cid} not present in DB (already removed or never ingested)")
                continue
            if rows[0].get("status") != "active":
                print(f"  ↩️ {cid} already {rows[0].get('status')}")
                continue
            (
                supabase_client.table("nav_warnings")
                .update({"status": "superseded"})
                .eq("canonical_id", cid)
                .eq("source_id", SOURCE_ID)
                .execute()
            )
            print(f"  🔗 SUPERSEDED: {cid}")
        except Exception as e:
            print(f"  ❌ Failed to supersede {cid}: {e}")
            has_errors = True
    return not has_errors


def sync_to_supabase(json_file="navareas/navarea_xii/parsed_navarea_xii_warnings.json") -> bool:
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

    sync_ok = run_differential_sync(
        source_id=SOURCE_ID,
        navarea_name="NAVAREA XII",
        scraped_warnings=scraped_warnings,
        scraped_messages=scraped_messages,
    )

    # Cross-reference supersede pass (skipped in dry-run: no client available)
    client = get_supabase_client()
    supersede_ok = _supersede_cross_refs(client, scraped_warnings)

    return sync_ok and supersede_ok


if __name__ == "__main__":
    success = sync_to_supabase()
    sys.exit(0 if success else 1)
