#!/usr/bin/env python3
"""shared/sync_modes.py — Differential sync safety modes & batch processing.
live_feed:     authoritative feed; missing-from-feed => cancel (guarded by min_feed_size).
static_corpus: merged_files.txt / historical imports; cancellation DISABLED.
               Only Skip / Add / Update are evaluated.
Includes BatchSyncResult and compute_differential_batched."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from shared.exceptions import ValidationError, SyncError
from shared.metrics import metrics
from shared.logging import get_logger

logger = get_logger("sync")


@dataclass(frozen=True)
class SyncDecision:
    op: str                 # "skip" | "add" | "update" | "cancel"
    warning_id: str
    reason: str


@dataclass
class BatchSyncResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    cancelled: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    def total_processed(self) -> int:
        return self.added + self.updated + self.skipped + self.cancelled + self.failed


def compute_differential_guarded(
    feed_ids: Iterable[str],
    active_ids: Iterable[str],
    mode: str = "live_feed",
    min_feed_size_for_cancel: int = 5,
) -> list[SyncDecision]:
    """
    Guarded replacement for compute_differential().
    - static_corpus: never emits "cancel".
    - live_feed: cancels only when the feed is non-trivially populated
      (guards against a broken scraper returning an empty harvest).
    """
    if feed_ids is None or active_ids is None:
        raise ValidationError("feed_ids and active_ids must not be None")

    feed = [str(fid).strip() for fid in feed_ids if fid]
    active = [str(aid).strip() for aid in active_ids if aid]
    decisions: list[SyncDecision] = []
    feed_set = set(feed)

    for wid in active:
        if wid in feed_set:
            decisions.append(SyncDecision("skip", wid, "unchanged in feed"))
            metrics.counter("sync_operations_total", labels={"op": "skip"}).increment()
        elif mode == "static_corpus":
            decisions.append(SyncDecision("skip", wid, "static corpus: cancellation disabled"))
            metrics.counter("sync_operations_total", labels={"op": "skip"}).increment()
        elif len(feed) < min_feed_size_for_cancel:
            decisions.append(SyncDecision("skip", wid, f"feed too small ({len(feed)}), cancel suppressed"))
            metrics.counter("sync_operations_total", labels={"op": "skip"}).increment()
        else:
            decisions.append(SyncDecision("cancel", wid, "missing from live feed"))
            metrics.counter("sync_operations_total", labels={"op": "cancel"}).increment()

    for wid in feed:
        if wid not in set(active):
            decisions.append(SyncDecision("add", wid, "new in feed"))
            metrics.counter("sync_operations_total", labels={"op": "add"}).increment()

    return decisions


def compute_differential_batched(
    feed_warnings: Iterable[Dict[str, Any]],
    active_warnings: Iterable[Dict[str, Any]],
    batch_size: int = 100,
    mode: str = "live_feed",
    min_feed_size_for_cancel: int = 5,
    executor_fn: Optional[Callable[[SyncDecision, Dict[str, Any]], None]] = None,
) -> BatchSyncResult:
    """
    Batched differential sync with safety checks, metrics collection, and progress tracking.
    """
    result = BatchSyncResult()
    feed_list = list(feed_warnings or [])
    active_list = list(active_warnings or [])

    feed_map = {w.get("warning_id"): w for w in feed_list if isinstance(w, dict) and w.get("warning_id")}
    active_map = {w.get("warning_id"): w for w in active_list if isinstance(w, dict) and w.get("warning_id")}

    feed_ids = list(feed_map.keys())
    active_ids = list(active_map.keys())

    # Compute guarded differential
    decisions = compute_differential_guarded(
        feed_ids=feed_ids,
        active_ids=active_ids,
        mode=mode,
        min_feed_size_for_cancel=min_feed_size_for_cancel,
    )

    # Process in chunks of batch_size
    for i in range(0, len(decisions), max(1, batch_size)):
        chunk = decisions[i : i + batch_size]
        for d in chunk:
            try:
                record = feed_map.get(d.warning_id) or active_map.get(d.warning_id, {})
                if executor_fn:
                    executor_fn(d, record)

                if d.op == "add":
                    result.added += 1
                elif d.op == "update":
                    result.updated += 1
                elif d.op == "skip":
                    result.skipped += 1
                elif d.op == "cancel":
                    result.cancelled += 1
            except Exception as e:
                result.failed += 1
                err_msg = f"{d.warning_id} ({d.op}): {str(e)}"
                result.errors.append(err_msg)
                logger.error(f"Batch sync item failed: {err_msg}", extra={"warning_id": d.warning_id, "op": d.op})

    return result
