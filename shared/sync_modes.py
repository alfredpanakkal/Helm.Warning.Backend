#!/usr/bin/env python3
"""shared/sync_modes.py — Differential sync safety modes.
live_feed:     authoritative feed; missing-from-feed => cancel (existing behavior).
static_corpus: merged_files.txt / historical imports; cancellation DISABLED.
               Only Skip / Add / Update are evaluated."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SyncDecision:
    op: str                 # "skip" | "add" | "update" | "cancel"
    warning_id: str
    reason: str


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
    feed = list(feed_ids)
    active = list(active_ids)
    decisions: list[SyncDecision] = []
    feed_set = set(feed)

    for wid in active:
        if wid in feed_set:
            decisions.append(SyncDecision("skip", wid, "unchanged in feed"))
        elif mode == "static_corpus":
            decisions.append(SyncDecision("skip", wid, "static corpus: cancellation disabled"))
        elif len(feed) < min_feed_size_for_cancel:
            decisions.append(SyncDecision("skip", wid, f"feed too small ({len(feed)}), cancel suppressed"))
        else:
            decisions.append(SyncDecision("cancel", wid, "missing from live feed"))

    for wid in feed:
        if wid not in set(active):
            decisions.append(SyncDecision("add", wid, "new in feed"))
    return decisions
