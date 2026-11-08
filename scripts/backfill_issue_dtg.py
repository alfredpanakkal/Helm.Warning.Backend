#!/usr/bin/env python3
"""One-off, re-runnable backfill of valid_from for ACTIVE nav_warnings rows.

Scope (Alfred, 2026-11-08): rows in navarea IV / XII / IX / VIII with
status='active' AND valid_from IS NULL. For each row the SAME rule the
pipeline uses is reapplied - shared helpers only, never a re-implementation:

  1. an explicit validity range in raw_text (universal parser's
     _extract_validity_dates) -> "skipped: range" (never overwritten
     with the issue date; the range's valid_from belongs to a future
     range-extraction change, not this backfill);
  2. issue DTG later than now_utc + 2 days (issue_dtg_is_future,
     injected aware-UTC clock) -> "future" (year errors, not real
     future warnings);
  3. first/last DTG match-and-disagree (issue_dtg_has_conflict) ->
     "conflict";
  4. trailing/leading DTG token (extract_issue_dtg) parsed via
     parse_safe_iso_timestamp -> "filled";
  5. no usable DTG -> "null_by_rule" (stays NULL).

Default mode is DRY-RUN: writes only a report CSV and prints counts.
--apply updates ONLY the valid_from column, one row at a time, guarded
by WHERE id = :id AND valid_from IS NULL AND status = 'active'. Nothing
else (status, valid_to, raw_text, qa_flags, updated_at, ...) is touched.

Secrets come only from SUPABASE_URL / SUPABASE_KEY and are never logged;
log lines carry canonical_id and the computed value only.
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.navarea_universal_parser import _extract_validity_dates
from shared.models import (
    extract_issue_dtg,
    issue_dtg_has_conflict,
    issue_dtg_is_future,
    parse_safe_iso_timestamp,
)

REGIONS = ("IV", "XII", "IX", "VIII")
PAGE_SIZE = 500
DEFAULT_MAX_UPDATES = 500
MAX_EXAMPLES_LOGGED = 5

OUTCOME_FILLED = "filled"
OUTCOME_NULL_BY_RULE = "null_by_rule"
OUTCOME_FUTURE = "future"
OUTCOME_CONFLICT = "conflict"
OUTCOME_RANGE = "skipped: range"
OUTCOMES = (
    OUTCOME_FILLED, OUTCOME_NULL_BY_RULE, OUTCOME_FUTURE,
    OUTCOME_CONFLICT, OUTCOME_RANGE,
)

REPORT_COLUMNS = ("canonical_id", "navarea", "computed_valid_from", "outcome")
BEFORE_COLUMNS = ("canonical_id", "id", "valid_from_before", "valid_from_written")

EXIT_OK = 0
EXIT_CREDS = 2
EXIT_ABORT = 3
EXIT_UPDATE_FAILURES = 4

RE_CANONICAL_YEAR = re.compile(r"/(\d{2,4})\s*$")


def _year_hint(canonical_id):
    """2-digit year hint from the canonical_id suffix ('1155/26' -> '26')."""
    m = RE_CANONICAL_YEAR.search(str(canonical_id or ""))
    return m.group(1) if m else None


def classify_row(row, now_utc):
    """One DB row -> (outcome, computed valid_from or None).

    Same precedence the pipeline applies in build_master_payload /
    parse_warning: an explicit validity range wins over the issue DTG,
    then the future guard, then the conflict check, then the parse.
    Pure: no clock reads, no DB writes; now_utc is injected.
    """
    raw_text = row.get("raw_text") or ""
    range_from, _range_to = _extract_validity_dates(
        raw_text, _year_hint(row.get("canonical_id")))
    if range_from is not None:
        return OUTCOME_RANGE, None
    token = extract_issue_dtg(raw_text)
    if token is not None and issue_dtg_is_future(token, now_utc):
        return OUTCOME_FUTURE, None
    if issue_dtg_has_conflict(raw_text):
        return OUTCOME_CONFLICT, None
    if token is None:
        return OUTCOME_NULL_BY_RULE, None
    value = parse_safe_iso_timestamp(token)
    if value is None:
        return OUTCOME_NULL_BY_RULE, None
    return OUTCOME_FILLED, value


def fetch_backfill_rows(client):
    """Active rows with valid_from IS NULL in the four target regions."""
    rows = []
    offset = 0
    while True:
        resp = (client.table("nav_warnings")
                .select("id, navarea, canonical_id, raw_text")
                .eq("status", "active")
                .is_("valid_from", "null")
                .in_("navarea", list(REGIONS))
                .range(offset, offset + PAGE_SIZE - 1)
                .execute())
        page = list(getattr(resp, "data", None) or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def apply_valid_from(client, row_id, value):
    """One-row guarded UPDATE: valid_from only, only where still NULL."""
    return (client.table("nav_warnings")
            .update({"valid_from": value})
            .eq("id", row_id)
            .eq("status", "active")
            .is_("valid_from", "null")
            .execute())


def _write_report_csv(path, results):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(REPORT_COLUMNS)
        for entry in results:
            row = entry["row"]
            writer.writerow([
                row.get("canonical_id"),
                row.get("navarea"),
                entry["value"] or "",
                entry["outcome"],
            ])


def _write_before_csv(path, fillable):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(BEFORE_COLUMNS)
        for entry in fillable:
            row = entry["row"]
            writer.writerow([
                row.get("canonical_id"),
                row.get("id"),
                row.get("valid_from") or "",
                entry["value"],
            ])


def _log_counts(results, log):
    by_region = {}
    for entry in results:
        navarea = entry["row"].get("navarea") or "?"
        by_region.setdefault(navarea, {})
        per = by_region[navarea]
        per[entry["outcome"]] = per.get(entry["outcome"], 0) + 1
    log("=== Per-region counts ===")
    for navarea in sorted(by_region):
        per = by_region[navarea]
        total = sum(per.values())
        parts = ", ".join(
            "%s %d" % (o, per.get(o, 0)) for o in OUTCOMES)
        log("%s: %d row(s) - %s" % (navarea, total, parts))
    totals = {}
    for entry in results:
        totals[entry["outcome"]] = totals.get(entry["outcome"], 0) + 1
    log("=== Totals ===")
    log("all regions: %d row(s) - %s" % (
        sum(totals.values()),
        ", ".join("%s %d" % (o, totals.get(o, 0)) for o in OUTCOMES)))
    for outcome in OUTCOMES:
        examples = [
            e["row"].get("canonical_id") for e in results
            if e["outcome"] == outcome][:MAX_EXAMPLES_LOGGED]
        if examples:
            log("examples %s: %s" % (outcome, ", ".join(str(x) for x in examples)))


def run_backfill(client, now_utc, apply=False,
                 max_updates=DEFAULT_MAX_UPDATES,
                 report_path="backfill_issue_dtg_report.csv",
                 before_path="backfill_issue_dtg_before_values.csv",
                 log=print):
    """Dry-run (default) or apply. Returns a summary dict.

    On --apply with more fillable rows than --max-updates, aborts BEFORE
    writing anything (no CSVs, no database writes).
    """
    rows = fetch_backfill_rows(client)
    log("Fetched %d active row(s) with valid_from NULL in %s." % (
        len(rows), "/".join(REGIONS)))
    results = []
    for row in rows:
        outcome, value = classify_row(row, now_utc)
        results.append({"row": row, "outcome": outcome, "value": value})
    fillable = [e for e in results if e["outcome"] == OUTCOME_FILLED]

    if apply and len(fillable) > max_updates:
        log("ABORT: would update %d row(s) but --max-updates is %d. "
            "Nothing was written (no CSVs, no database updates)." % (
                len(fillable), max_updates))
        return {
            "aborted": True, "fetched": len(rows),
            "would_update": len(fillable), "applied": 0, "failed": 0,
        }

    _write_report_csv(report_path, results)
    log("Report CSV written: %s" % report_path)
    _log_counts(results, log)

    summary = {
        "aborted": False, "apply": bool(apply), "fetched": len(rows),
        "would_update": len(fillable), "applied": 0, "failed": 0,
    }
    if not apply:
        log("Dry-run: no database writes. Re-run with --apply to write "
            "%d valid_from value(s)." % len(fillable))
        return summary

    # Before-values CSV is written BEFORE any update (rollback record).
    _write_before_csv(before_path, fillable)
    log("Before-values CSV written: %s" % before_path)

    for entry in fillable:
        row, value = entry["row"], entry["value"]
        try:
            apply_valid_from(client, row["id"], value)
            summary["applied"] += 1
            log("[OK] %s: valid_from = %s" % (row.get("canonical_id"), value))
        except Exception as exc:  # noqa: BLE001 - log & continue row by row
            summary["failed"] += 1
            log("[FAIL] %s: update failed (%s)" % (
                row.get("canonical_id"), type(exc).__name__))
    log("Apply complete: %d updated, %d failed." % (
        summary["applied"], summary["failed"]))
    return summary


def _parse_now(text):
    """ISO-8601 aware-UTC clock from a --now argument, or None."""
    if not text:
        return None
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(
        description="Backfill valid_from for active nav_warnings rows "
                    "(same rule as the pipeline). Dry-run by default.")
    parser.add_argument("--apply", action="store_true",
                        help="write valid_from (default: dry-run only)")
    parser.add_argument("--max-updates", type=int, default=DEFAULT_MAX_UPDATES,
                        help="abort before writing anything if the "
                             "would-update count exceeds this (default %d)"
                             % DEFAULT_MAX_UPDATES)
    parser.add_argument("--now", default=None,
                        help="injected clock, ISO-8601 UTC "
                             "(e.g. 2026-11-08T12:00:00Z); default: real clock")
    parser.add_argument("--report-csv", default="backfill_issue_dtg_report.csv",
                        help="dry-run/apply report CSV path")
    parser.add_argument("--before-csv",
                        default="backfill_issue_dtg_before_values.csv",
                        help="before-values CSV path (apply mode)")
    args = parser.parse_args(argv)

    now_utc = _parse_now(args.now)
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    log_clock = now_utc.isoformat()
    print("Backfill clock (now_utc): %s" % log_clock)
    print("Mode: %s" % ("APPLY" if args.apply else "DRY-RUN"))

    if client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        missing = [name for name, val in (
            ("SUPABASE_URL", url), ("SUPABASE_KEY", key)) if not val]
        if missing:
            print("FATAL: missing environment variable(s): %s "
                  "(values are never printed)." % ", ".join(missing))
            return EXIT_CREDS
        from supabase import create_client
        client = create_client(url, key)

    summary = run_backfill(
        client, now_utc, apply=args.apply, max_updates=args.max_updates,
        report_path=args.report_csv, before_path=args.before_csv)
    if summary.get("aborted"):
        return EXIT_ABORT
    if summary.get("failed"):
        return EXIT_UPDATE_FAILURES
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
