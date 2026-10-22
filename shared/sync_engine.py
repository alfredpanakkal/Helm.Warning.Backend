#!/usr/bin/env python3
"""shared/sync_engine.py — Core Differential Ingestion Engine for all NAVAREA Regions.
Handles:
1. Environment pre-flight credential checks (loud failure if missing credentials)
2. Differential change detection keyed on canonical_id
3. Atomic master + child geometry writes via upsert_nav_warning RPC
4. Audit trail persistence into public.raw_messages
5. Evidence-based lifecycle transitions (guarded cancel / expiry — a warning
   missing from a scrape is never auto-cancelled without evidence)
6. Run ledger persistence into public.ingestion_generations
"""

import os
import sys
import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.models import build_master_payload, build_geometry_payloads, parse_safe_iso_timestamp
from shared.utils import compute_differential

VALID_RAW_COLUMNS = {
    "warning_id", "source_id", "subject_header",
    "full_raw_text", "received_timestamp", "checksum_sha256"
}

# ---------------------------------------------------------------------------
# Lifecycle-transition evidence thresholds.
#
# A scrape that is suspiciously small relative to the DB's active set is
# treated as an INCOMPLETE SNAPSHOT: scrape-absent warnings are left
# untouched (recorded as 'unobserved' in the run ledger) instead of being
# cancelled. This mirrors the frontend guard (computeDifferentialGuarded,
# minFeedSizeForCancel) and prevents partial-source failures from wiping
# warnings off the live map.
# ---------------------------------------------------------------------------
CANCEL_MIN_FEED_COUNT = int(os.environ.get("SYNC_CANCEL_MIN_FEED_COUNT", "10"))
CANCEL_MIN_FEED_FRACTION = float(os.environ.get("SYNC_CANCEL_MIN_FEED_FRACTION", "0.5"))


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
        # Fallback to direct master upsert if RPC is missing.
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


def _record_generation(
    supabase_client,
    source_id: str,
    navarea_name: str,
    started_at: str,
    status: str,
    counts: Dict[str, Any],
    evidence_ids: List[str],
) -> None:
    """Best-effort run ledger row in public.ingestion_generations.

    Non-fatal by design: the ledger must never block a sync, but its absence
    should be visible. Frontend (Data Bank) reads: generation_id, source_id,
    started_at, completed_at, status, parsed_count, active_count, evidence_hash.
    """
    if supabase_client is None:
        return
    evidence_hash = hashlib.sha256("|".join(sorted(evidence_ids)).encode("utf-8")).hexdigest()
    row = {
        "generation_id": str(uuid.uuid4()),
        "source_id": source_id,
        "navarea": navarea_name,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "parsed_count": int(counts.get("harvested", 0)),
        "active_count": int(counts.get("skip", 0)) + int(counts.get("new", 0)) + int(counts.get("update", 0)),
        "evidence_hash": evidence_hash,
        "details": counts,
    }
    try:
        supabase_client.table("ingestion_generations").insert(row).execute()
    except Exception as e:
        print(f"  ⚠️ Run ledger not recorded (ingestion_generations): {e}")


def _as_utc_datetime(value) -> Optional[datetime]:
    """Tolerantly converts DB/API date strings into aware UTC datetimes."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        parsed = parse_safe_iso_timestamp(value)
        if not parsed:
            return None
        try:
            dt = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _apply_status_transition(supabase_client, canonical_id: str, patch: Dict[str, Any]) -> bool:
    try:
        (
            supabase_client.table("nav_warnings")
            .update(patch)
            .eq("canonical_id", canonical_id)
            .execute()
        )
        return True
    except Exception as e:
        print(f"  ❌ Failed to transition {canonical_id}: {e}")
        return False


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
    started_at = datetime.now(timezone.utc).isoformat()
    print("=" * 65)
    print(f"⚡ {navarea_name} Differential Sync Engine ({source_id})")
    print("=" * 65)

    if supabase_client is None:
        supabase_client = get_supabase_client()

    if supabase_client is None:
        print(f"ℹ️ Dry-run mode for {navarea_name}: {len(scraped_warnings)} warnings inspected.")
        return True

    if not scraped_warnings:
        print(f"❓ No warnings provided to sync for {navarea_name}: existing records left untouched.")
        _record_generation(
            supabase_client, source_id, navarea_name, started_at, "empty_feed",
            {"harvested": 0, "skip": 0, "new": 0, "update": 0,
             "cancelled": 0, "expired": 0, "unobserved": 0, "missing": 0},
            [],
        )
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
            .select("canonical_id, status, raw_text, valid_to")
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

    # Warnings active in DB but absent from this scrape (lifecycle input).
    # Computed here rather than in compute_differential so the shared
    # differential contract stays backward-compatible: absence alone
    # never mutates state.
    scraped_ids = {w["canonical_id"] for w in scraped_for_diff}
    missing_ids = [
        wid for wid, rec in existing_warnings.items()
        if rec.get("status") == "active" and wid not in scraped_ids
    ]

    print(
        f"\n[2/4] Differential analysis: "
        f"{len(diff['skip'])} skipped, {len(diff['new'])} new, "
        f"{len(diff['update'])} update, {len(missing_ids)} missing-from-scrape"
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

    # 4. Evidence-based lifecycle transitions for warnings missing from the
    #    scrape. Archiving is a status change, never a deletion:
    #      - 'expired'   : the warning's own valid_to date has passed
    #                      (evidence: validity period in the DB record).
    #      - 'cancelled' : absent from a CREDIBLE complete snapshot
    #                      (evidence: feed size >= SYNC_CANCEL_MIN_FEED_COUNT
    #                      and >= SYNC_CANCEL_MIN_FEED_FRACTION of DB actives).
    #                      Anything else leaves the warning active.
    missing = missing_ids
    expired_ids: List[str] = []
    unobserved_ids: List[str] = []

    now_dt = datetime.now(timezone.utc)
    for wid in missing:
        record = existing_warnings.get(wid, {})
        valid_to_dt = _as_utc_datetime(record.get("valid_to"))
        if valid_to_dt and valid_to_dt <= now_dt:
            expired_ids.append(wid)
        else:
            unobserved_ids.append(wid)

    feed_size = len(scraped_for_diff)
    total_actives = feed_size + len(missing)
    feed_credible = (
        feed_size >= CANCEL_MIN_FEED_COUNT
        and total_actives > 0
        and feed_size >= CANCEL_MIN_FEED_FRACTION * total_actives
    )
    cancelled_ids: List[str] = []
    if feed_credible:
        cancelled_ids = unobserved_ids
        unobserved_ids = []

    print(f"\n[4/4] Lifecycle pass: {len(missing)} missing-from-scrape → "
          f"{len(cancelled_ids)} cancelled, {len(expired_ids)} expired, "
          f"{len(unobserved_ids)} left active (unobserved)")
    if unobserved_ids:
        print(
            f"  ⏸ Cancel guard active: feed not credible as a complete snapshot "
            f"({feed_size} scraped vs {total_actives} DB actives; thresholds: "
            f">={CANCEL_MIN_FEED_COUNT} and >={CANCEL_MIN_FEED_FRACTION:.0%}). "
            f"Existing warnings left untouched."
        )

    now_stamp = datetime.now(timezone.utc).isoformat()
    for wid in expired_ids:
        if _apply_status_transition(supabase_client, wid, {
            "status": "expired",
            "status_basis": "expired_by_validity",
            "status_changed_at": now_stamp,
        }):
            print(f"  🕰️ Expired (valid_to passed): {wid}")
        else:
            has_errors = True

    for wid in cancelled_ids:
        if _apply_status_transition(supabase_client, wid, {
            "status": "cancelled",
            "status_basis": "source_absence_verified_snapshot",
            "status_changed_at": now_stamp,
        }):
            print(f"  🗄️ Archived (cancelled, absent from verified snapshot): {wid}")
        else:
            has_errors = True

    for wid in unobserved_ids:
        print(f"  👁️ Unobserved this run, retained active: {wid}")

    counts = {
        "harvested": len(scraped_warnings),
        "skip": len(diff["skip"]),
        "new": len(diff["new"]),
        "update": len(diff["update"]),
        "cancelled": len(cancelled_ids),
        "expired": len(expired_ids),
        "unobserved": len(unobserved_ids),
        "missing": len(missing),
        "cancel_guard": {
            "min_feed_count": CANCEL_MIN_FEED_COUNT,
            "min_feed_fraction": CANCEL_MIN_FEED_FRACTION,
            "feed_credible": feed_credible,
        },
    }
    _record_generation(
        supabase_client, source_id, navarea_name, started_at,
        "failed" if has_errors else "succeeded",
        counts,
        [w.get("canonical_id", "") for w in scraped_for_diff],
    )

    print("\n" + "=" * 65)
    print(
        f"📊 {navarea_name} Summary: "
        f"{counts['harvested']} harvested, {counts['skip']} unchanged, "
        f"{counts['new']} inserted, {counts['update']} updated, "
        f"{counts['cancelled']} cancelled, {counts['expired']} expired, "
        f"{counts['unobserved']} unobserved (retained active)"
    )
    print("=" * 65)

    return not has_errors
