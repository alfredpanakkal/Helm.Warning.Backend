#!/usr/bin/env python3
"""Recompute canonical severity for every warning; apply only through audited RPC.

Default is read-only. Production writes require both --apply and --confirm-apply.
Human/admin-verified records are reported but never overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from supabase import create_client
from shared.severity import determine_hazard_severity


PAGE_SIZE = 500
WRITE_BATCH_SIZE = 5
PROTECTED_FLAGS = {"edited_by_admin", "verified_by_admin"}


def fetch_all(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_id: str | None = None
    while True:
        query = (
            client.table("nav_warnings")
            .select("id,canonical_id,navarea,raw_text,categories,severity,updated_at,qa_flags,status,triage_tier")
            .order("id")
            .limit(PAGE_SIZE)
        )
        if last_id:
            query = query.gt("id", last_id)
        page = query.execute().data or []
        if not page:
            break
        rows.extend(page)
        last_id = page[-1]["id"]
        if len(page) < PAGE_SIZE:
            break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", default="severity-backfill-report")
    parser.add_argument("--apply", action="store_true", help="Apply severity-only updates through audited RPC.")
    parser.add_argument("--confirm-apply", action="store_true", help="Required second explicit write gate.")
    parser.add_argument("--expected-count", type=int, default=None, help="Abort if fetched row count differs.")
    args = parser.parse_args()

    if args.confirm_apply and not args.apply:
        parser.error("--confirm-apply requires --apply")
    if args.apply and not args.confirm_apply:
        parser.error("Production writes require both --apply and --confirm-apply")

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_KEY/SUPABASE_SERVICE_ROLE_KEY are required.", file=sys.stderr)
        return 2

    client = create_client(url, key)
    rows = fetch_all(client)
    if args.expected_count is not None and len(rows) != args.expected_count:
        raise RuntimeError(f"Expected {args.expected_count} rows; fetched {len(rows)}. Refusing to continue.")

    changes: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    missing_text: list[dict[str, Any]] = []
    distribution_before: dict[str, int] = {}
    distribution_expected: dict[str, int] = {}

    for row in rows:
        old = row.get("severity")
        distribution_before[str(old)] = distribution_before.get(str(old), 0) + 1
        raw = row.get("raw_text")
        if not isinstance(raw, str) or not raw.strip():
            missing_text.append({"id": row["id"], "canonical_id": row.get("canonical_id")})
            continue
        expected = determine_hazard_severity(raw, row.get("categories") or [])
        distribution_expected[expected] = distribution_expected.get(expected, 0) + 1
        flags = set(row.get("qa_flags") or [])
        if flags & PROTECTED_FLAGS:
            if old != expected:
                protected.append({
                    "id": row["id"], "canonical_id": row.get("canonical_id"),
                    "stored": old, "expected": expected, "flags": sorted(flags & PROTECTED_FLAGS)
                })
            continue
        if old != expected:
            changes.append({
                "id": row["id"], "canonical_id": row.get("canonical_id"),
                "navarea": row.get("navarea"), "old": old, "new": expected,
                "updated_at": row.get("updated_at"), "status": row.get("status"),
                "triage_tier": row.get("triage_tier"),
            })

    applied: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if args.apply:
        # Re-read each row immediately before its write. The RPC also enforces
        # updated_at under row lock, preventing stale snapshots from overwriting edits.
        for offset in range(0, len(changes), WRITE_BATCH_SIZE):
            for item in changes[offset:offset + WRITE_BATCH_SIZE]:
                try:
                    current = (
                        client.table("nav_warnings")
                        .select("updated_at,severity,qa_flags")
                        .eq("id", item["id"])
                        .single()
                        .execute()
                        .data
                    )
                    if not current or current.get("severity") != item["old"]:
                        raise RuntimeError("Stored severity changed after snapshot; skipped as stale.")
                    if set(current.get("qa_flags") or []) & PROTECTED_FLAGS:
                        raise RuntimeError("Record became human/admin protected; skipped.")
                    result = client.rpc("admin_set_nav_warning_severity", {
                        "p_warning_id": item["id"],
                        "p_severity": item["new"],
                        "p_expected_updated_at": current["updated_at"],
                        "p_operator": "severity-backfill",
                        "p_reason": "Canonical severity recalculation from raw_text and categories after resolver PR #125",
                    }).execute().data
                    applied.append({"id": item["id"], "result": result})
                except Exception as exc:
                    failures.append({"id": item["id"], "error": str(exc)})
                    # Fail closed: stop the run on first failed write.
                    break
            if failures:
                break

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "fetched_count": len(rows),
        "distribution_before": distribution_before,
        "distribution_expected_nonprotected_with_text": distribution_expected,
        "candidate_count": len(changes),
        "candidates": changes,
        "protected_mismatches": protected,
        "missing_raw_text": missing_text,
        "applied_count": len(applied),
        "applied": applied,
        "failures": failures,
        "write_batch_size": WRITE_BATCH_SIZE,
        "write_scope": "severity column only via admin_set_nav_warning_severity RPC",
    }
    out = Path(args.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "severity_backfill_report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "mode", "fetched_count", "distribution_before",
        "distribution_expected_nonprotected_with_text", "candidate_count",
        "protected_mismatches", "missing_raw_text", "applied_count", "failures"
    )}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
