#!/usr/bin/env python3
"""
scripts/audit_failure_clustering.py — Phase 3 WP1: deterministic failure clustering.

Groups Phase 2 audit issues into stable, ranked clusters so a later AI
root-cause stage sees ~20 clusters instead of thousands of rows.

Design (Phase 3 plan, accepted 2026-10-28):
  - Pure and offline: no network, no DB, no AI calls. Deterministic: the same
    input always yields the same cluster_ids (this enables checkpointing).
  - Cluster key = issue code + NAVAREA + masked text signature.
  - Text signature: raw_text uppercased, digits masked (41°20.5'N ->
    ##°##.#'N), whitespace collapsed, capped length. Hemisphere letters
    and keywords (BOUNDED BY, JOINING, RADIUS) stay unmasked because they
    often hold the cause.
  - cluster_id = sha1 of the key, truncated — stable across runs.
  - Excluded before clustering: protected_conflict and geometry_unknown
    (and any infra-failure code); those are not parser defects.
  - Ranking: analyzable severity (critical, major) first, then active
    count, then cluster size.
  - Interim severity mapping (ERROR/WARNING) until Phase 2 WP4 defines the
    per-code critical/major/minor mapping; WP4 replaces the table.
  - Analysis scope (Alfred's decision 2026-10-28): critical + major only.
    Minor clusters are still clustered and reported, but analyzable=False.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

# Issue codes that are never parser defects — excluded before clustering.
EXCLUDED_ISSUE_CODES = {
    "PROTECTED_CONFLICT",   # admin-owned rows (Phase 2 WP7)
    "GEOMETRY_UNKNOWN",     # geometry fetch failed (Phase 2 WP3) — infra
}

# Severity vocabulary and ranking (Phase 2 WP4 vocabulary).
SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2}

# Interim mapping from current audit severities (ERROR/WARNING) to the
# WP4 vocabulary. Phase 2 WP4 replaces this with a per-code mapping.
INTERIM_SEVERITY_MAP = {"ERROR": "major", "WARNING": "minor"}

# Analysis scope (Alfred, 2026-10-28): only these go to the AI stage.
ANALYSIS_SEVERITIES = ("critical", "major")

SIGNATURE_MAX_CHARS = 600
EXAMPLE_LIMIT = 3
EXAMPLE_SNIPPET_CHARS = 400
EXAMPLES_PER_STATUS = 3  # bound the example pool per status

_DIGIT_RE = re.compile(r"\d")
_WHITESPACE_RE = re.compile(r"\s+")


def text_signature(raw_text: Optional[str], max_chars: int = SIGNATURE_MAX_CHARS) -> str:
    """Masked, whitespace-collapsed, uppercased signature of the raw text.

    Digits become '#' so the same pattern clusters across warnings with
    different coordinates; hemisphere letters and keywords stay intact.
    """
    text = (raw_text or "").upper()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _DIGIT_RE.sub("#", text)
    return text[:max_chars]


def cluster_id_for(code: str, navarea: str, signature: str) -> str:
    """Stable cluster id: same key -> same id on every run."""
    raw = "|".join((str(code or ""), str(navarea or ""), signature))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _example_snippet(raw_text: Optional[str]) -> str:
    """Whitespace-collapsed raw snippet, trimmed for prompt use."""
    text = _WHITESPACE_RE.sub(" ", (raw_text or "")).strip()
    return text[:EXAMPLE_SNIPPET_CHARS]


def cluster_issues(
    issues: List[Dict[str, Any]],
    records_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Cluster audit issues deterministically. Pure; mutates nothing.

    issues: Phase 2 issue dicts (code, severity, warning_id, navarea, ...).
    records_by_id: warning_id -> nav_warnings record (for raw_text/status).

    Returns a ranked list of cluster dicts:
      cluster_id, code, navarea, signature, severity, analyzable, count,
      active_count, per_status, affected_warning_ids, examples
    """
    records_by_id = records_by_id or {}
    clusters: Dict[str, Dict[str, Any]] = {}

    for iss in issues:
        code = str(iss.get("code") or "").strip().upper()
        if code in EXCLUDED_ISSUE_CODES:
            continue

        wid = iss.get("warning_id")
        rec = records_by_id.get(wid) or {}
        navarea = iss.get("navarea") or rec.get("navarea") or ""
        raw_text = rec.get("raw_text")
        signature = text_signature(raw_text)
        cid = cluster_id_for(code, navarea, signature)

        sev_raw = str(iss.get("severity") or "").strip().upper()
        severity = INTERIM_SEVERITY_MAP.get(sev_raw, "minor")
        status = str(rec.get("status") or "unknown")

        c = clusters.setdefault(cid, {
            "cluster_id": cid,
            "code": code,
            "navarea": navarea,
            "signature": signature,
            "severity": severity,
            "count": 0,
            "warning_ids": [],
            "per_status": {},
            "_example_pool": {},  # status -> list of example dicts
        })
        c["count"] += 1
        if wid and wid not in c["warning_ids"]:
            c["warning_ids"].append(wid)
        c["per_status"][status] = c["per_status"].get(status, 0) + 1

        pool = c["_example_pool"].setdefault(status, [])
        if len(pool) < EXAMPLES_PER_STATUS:
            pool.append({
                "warning_id": wid,
                "canonical_id": iss.get("canonical_id") or rec.get("canonical_id"),
                "status": status,
                "raw_snippet": _example_snippet(raw_text),
            })

    ranked: List[Dict[str, Any]] = []
    for c in clusters.values():
        # Diverse examples: round-robin across statuses so examples differ
        # in status where possible, capped at EXAMPLE_LIMIT.
        statuses = sorted(c["_example_pool"].keys())
        examples: List[Dict[str, Any]] = []
        picked = 0
        while picked < EXAMPLE_LIMIT:
            added = False
            for status in statuses:
                pool = c["_example_pool"][status]
                if pool:
                    examples.append(pool.pop(0))
                    picked += 1
                    added = True
                    if picked >= EXAMPLE_LIMIT:
                        break
            if not added:
                break

        active_count = c["per_status"].get("active", 0)
        ranked.append({
            "cluster_id": c["cluster_id"],
            "code": c["code"],
            "navarea": c["navarea"],
            "signature": c["signature"],
            "severity": c["severity"],
            "analyzable": c["severity"] in ANALYSIS_SEVERITIES,
            "count": c["count"],
            "active_count": active_count,
            "per_status": dict(c["per_status"]),
            "affected_warning_ids": sorted(c["warning_ids"]),
            "examples": examples,
        })

    # Rank: analyzable first, then severity, then active count, then size,
    # then cluster_id as a final deterministic tiebreak.
    ranked.sort(key=lambda cl: (
        0 if cl["analyzable"] else 1,
        SEVERITY_RANK.get(cl["severity"], len(SEVERITY_RANK)),
        -cl["active_count"],
        -cl["count"],
        cl["cluster_id"],
    ))
    return ranked


if __name__ == "__main__":
    # Offline smoke: cluster a trivial list and print the result shape.
    demo_issues = [{
        "code": "DISCREPANCY_UNPLOTTED_WITH_COORDINATES",
        "severity": "WARNING",
        "warning_id": "w-1",
        "canonical_id": "NAVAREA IV 001/26",
        "navarea": "NA IV",
    }]
    demo_records = {"w-1": {"raw_text": "1. BOUNDED BY 41-20.5N 011-14.5W", "status": "active"}}
    print(json.dumps(cluster_issues(demo_issues, demo_records), indent=2))
