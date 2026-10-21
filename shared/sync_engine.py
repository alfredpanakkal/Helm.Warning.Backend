#!/usr/bin/env python3
"""shared/sync_engine.py — Core Differential Ingestion Engine for all NAVAREA Regions.
Handles:
1. Environment pre-flight credential checks (loud failure if missing credentials)
2. Differential change detection keyed on canonical_id
3. Atomic master + child geometry writes via upsert_nav_warning RPC
4. Audit trail persistence into public.raw_messages
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.models import build_master_payload, build_geometry_payloads
from shared.utils import compute_differential

VALID_RAW_COLUMNS = {
    "warning_id", "source_id", "subject_header",
    "full_raw_text", "received_timestamp", "checksum_sha256"
}


def get_supabase_client():
    """Initializes and returns the Supabase client.
    Exits loud if SUPABASE_URL or SUPABASE_KEY are missing unless ALLOW_DRY_RUN=1.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    allow_dry_run = os.environ.get("ALLOW_DRY_RUN", "").lower() in ("1", "true", "yes")

    # Explicit dry-run request always wins, even with valid credentials present,
    # so CI can validate the full pipeline without touching the database.
    if allow_dry_run:
        print("⚠️ ALLOW_DRY_RUN active: running in dry-run mode (no Supabase client).")
        return None

    if not url or not key:
        if allow_dry_run:
            print("⚠️ SUPABASE_URL or SUPABASE_KEY missing in environment (ALLOW_DRY_RUN active).")
            return None
        print("❌ FATAL: SUPABASE_URL or SUPABASE_KEY is missing from the environment.", file=sys.stderr)
        print("   Set both variables or run with ALLOW_DRY_RUN=1 to simulate.", file=sys.stderr)
        sys.exit(2)

    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        if allow_dry_run:
            print("⚠️ supabase Python package not installed (ALLOW_DRY_RUN active).")
            return None
        print("❌ FATAL: 'supabase' package is not installed. Install with `pip install supabase`.", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"❌ FATAL: Failed to initialize Supabase client: {e}", file=sys.stderr)
        sys.exit(2)


def upsert_warning_atomic(supabase_client, master: Dict[str, Any], geometries: List[Dict[str, Any]]) -> bool:
    """Invokes public.upsert_nav_warning RPC to update master and child geometries in one transaction.
    Falls back to direct master upsert if RPC is unavailable.
    """
    if supabase_client is None:
        return True

    payload = {
        "master": master,
        "geometries": geometries
    }

    try:
        supabase_client.rpc("upsert_nav_warning", {"p_payload": payload}).execute()
        return True
    except Exception as rpc_err:
        # Fallback to direct master table upsert if RPC is missing.
        # IMPORTANT: the direct upsert CANNOT persist geometries (the
        # geom_postgis column requires PostGIS/ST_GeomFromGeoJSON, only
        # available inside the RPC). Persisting the master while dropping
        # its geometries corrupts the nav_warnings_active_spatial JOIN
        # (Tier-A masters with zero geometry rows = invisible on the map),
        # so this is treated as an error, not a silent success.
        print(f"    ⚠️ RPC upsert failed ({rpc_err}); attempting direct master upsert...")
        try:
            supabase_client.table("nav_warnings").upsert(master, on_conflict="canonical_id").execute()
        except Exception as direct_err:
            print(f"    ❌ Direct master upsert failed: {direct_err}")
            return False
        if geometries:
            print(
                f"    ❌ GEOMETRIES DROPPED for {master.get('canonical_id')}: "
                f"{len(geometries)} geometry payload(s) NOT persisted "
                f"(nav_warnings_active_spatial will not show this warning). "
                f"Fix the upsert_nav_warning RPC and re-run the sync."
            )
            return False
        return True


def run_differential_sync(
    source_id: str,
    navarea_name: str,
    scraped_warnings: List[Dict[str, Any]],
    scraped_messages: List[Dict[str, Any]],
    supabase_client: Optional[Any] = None,
) -> bool:
    """Executes full differential synchronization against Supabase using canonical_id and atomic RPC.
    Returns True if completely successful, False if any error occurred.
    """
    print("=" * 65)
    print(f"⚡ {navarea_name} Differential Sync Engine ({source_id})")
    print("=" * 65)

    if supabase_client is None:
        supabase_client = get_supabase_client()

    if supabase_client is None:
        print(f"ℹ️ Dry-run mode for {navarea_name}: {len(scraped_warnings)} warnings inspected.")
        return True

    if not scraped_warnings:
        print(f"❓ No warnings provided to sync for {navarea_name}.")
        return True

    # 1. Normalize scraped warnings into master payloads & geometries
    normalized_items: List[Tuple[Dict[str, Any], List[Dict[str, Any]], str]] = []
    scraped_for_diff: List[Dict[str, Any]] = []

    for raw_warn in scraped_warnings:
        raw_warn_copy = dict(raw_warn)
        if "source_id" not in raw_warn_copy or not raw_warn_copy["source_id"]:
            raw_warn_copy["source_id"] = source_id
        if "navarea" not in raw_warn_copy or not raw_warn_copy["navarea"]:
            raw_warn_copy["navarea"] = navarea_name

        master = build_master_payload(raw_warn_copy)
        geoms = build_geometry_payloads(raw_warn_copy)
        cid = master["canonical_id"]

        normalized_items.append((master, geoms, raw_warn_copy.get("warning_id", cid)))
        scraped_for_diff.append({
            "canonical_id": cid,
            "warning_id": raw_warn_copy.get("warning_id", cid),
            "status": master["status"],
            "raw_text": master["raw_text"],
            "_master": master,
            "_geoms": geoms,
        })

    print("\n[1/4] Querying remote database state...")
    try:
        res_warn = (
            supabase_client.table("nav_warnings")
            .select("canonical_id, status, raw_text")
            .eq("source_id", source_id)
            .execute()
        )
        existing_warnings = {
            r["canonical_id"]: r
            for r in (res_warn.data or [])
            if isinstance(r, dict) and r.get("canonical_id")
        }
    except Exception as e:
        print(f"❌ DB query failed on 'nav_warnings': {e}")
        return False

    try:
        res_raw = (
            supabase_client.table("raw_messages")
            .select("warning_id, checksum_sha256")
            .eq("source_id", source_id)
            .execute()
        )
        existing_checksums = {
            (r["warning_id"], r["checksum_sha256"])
            for r in (res_raw.data or [])
            if isinstance(r, dict) and "warning_id" in r and "checksum_sha256" in r
        }
    except Exception as e:
        print(f"⚠️ Query on 'raw_messages' returned: {e} (proceeding without checksum cache)")
        existing_checksums = set()

    print(f"  ✔ Found {len(existing_warnings)} existing warnings in database")
    print(f"  ✔ Found {len(existing_checksums)} existing checksums in database")

    # 2. Compute differential keyed on canonical_id
    diff = compute_differential(
        scraped_warnings=scraped_for_diff,
        scraped_messages=scraped_messages,
        existing_warnings=existing_warnings,
        existing_checksums=existing_checksums,
        key_fn=lambda w: w.get("canonical_id")
    )

    print(
        f"\n[2/4] Differential analysis: "
        f"{len(diff['skip'])} skipped, {len(diff['new'])} new, "
        f"{len(diff['update'])} update, {len(diff['cancel'])} cancel"
    )

    has_errors = False

    # 3. Process new and updated records
    to_write = diff["new"] + diff["update"]
    if to_write:
        print(f"\n[3/4] Persisting {len(to_write)} records...")
        for diff_entry in to_write:
            warn_wrapper, msg = diff_entry
            master = warn_wrapper.get("_master")
            geoms = warn_wrapper.get("_geoms", [])
            cid = master["canonical_id"]
            wid = warn_wrapper.get("warning_id", cid)

            # Persist raw_message audit row
            if msg and isinstance(msg, dict):
                clean_msg = {k: v for k, v in msg.items() if k in VALID_RAW_COLUMNS}
                clean_msg.setdefault("source_id", source_id)
                clean_msg.setdefault("warning_id", wid)
                clean_msg.setdefault("full_raw_text", master["raw_text"])
                try:
                    supabase_client.table("raw_messages").insert(clean_msg).execute()
                    print(f"  ✅ [raw_messages] {wid}")
                except Exception as msg_err:
                    # Ignore unique violation if message already recorded
                    if "duplicate key" not in str(msg_err).lower():
                        print(f"  ⚠️ [raw_messages] {wid}: {msg_err}")

            # Atomic master + geometry upsert
            success = upsert_warning_atomic(supabase_client, master, geoms)
            if success:
                print(f"  ✨ [nav_warnings + geoms] {cid} (Triage: {master['triage_tier']}, Geoms: {len(geoms)})")
            else:
                print(f"  ❌ Failed to upsert: {cid}")
                has_errors = True

    # 4. Process cancellations
    if diff["cancel"]:
        print(f"\n[4/4] Canceling {len(diff['cancel'])} warnings...")
        for cid in diff["cancel"]:
            try:
                (
                    supabase_client.table("nav_warnings")
                    .update({"status": "cancelled"})
                    .eq("canonical_id", cid)
                    .execute()
                )
                print(f"  🗑️ Cancelled: {cid}")
            except Exception as e:
                print(f"  ❌ Failed to cancel {cid}: {e}")
                has_errors = True

    print("\n" + "=" * 65)
    print(
        f"📊 {navarea_name} Summary: "
        f"{len(scraped_warnings)} harvested, {len(diff['skip'])} unchanged, "
        f"{len(diff['new'])} inserted, {len(diff['update'])} updated, {len(diff['cancel'])} cancelled"
    )
    print("=" * 65)

    return not has_errors
