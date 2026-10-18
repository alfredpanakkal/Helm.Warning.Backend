#!/usr/bin/env python3
"""shared/triage.py — H02 Triage Precedence gate.
Guarantees TriageTier.A is strictly reserved for explicit, rule-parsed
records with verified geometry. Zero-coordinate records can never reach A."""

from __future__ import annotations
from typing import Any

from shared.models import DataQuality, ParsingMethod, TriageTier

C_TIER_BLOCKERS = {
    "MISSING_HEM", "PARTIAL_TRUNCATED_MISSING_COORDS", "AI_VALIDATION_FAILED",
    "ORPHAN_FRAGMENT", "MINUTES_OUT_OF_RANGE", "SECONDS_OUT_OF_RANGE",
    "LAT_OUT_OF_RANGE", "LON_OUT_OF_RANGE", "AXIS_HEMISPHERE_MISMATCH",
    "EMPTY_STUB", "DUAL_ORIGIN_SECTOR_UNRESOLVED",
}

C_TIER_UNPLOTTED = {"missing_hemisphere", "truncated_clause", "empty_stub",
                    "orphan_fragment", "meta_list", "validation_failed"}


def assign_final_triage(rec: Any) -> None:
    """Run after all parsing, repairs, AI escalation, and geometry construction."""
    # 1. Roll record-level quality up from coordinate-level quality (worst wins).
    coords = getattr(rec, "coordinates", []) or []
    for coord in coords:
        quality = getattr(coord, "quality", DataQuality.EXPLICIT)
        if quality == DataQuality.INVALID:
            rec.data_quality = DataQuality.INVALID
        elif quality == DataQuality.AMBIGUOUS and getattr(rec, "data_quality", DataQuality.EXPLICIT) != DataQuality.INVALID:
            rec.data_quality = DataQuality.AMBIGUOUS
        elif quality == DataQuality.INFERRED and getattr(rec, "data_quality", DataQuality.EXPLICIT) == DataQuality.EXPLICIT:
            rec.data_quality = DataQuality.INFERRED

    has_valid_geometry = bool(coords or getattr(rec, "vertices_lonlat", None) or getattr(rec, "latitude", None) is not None)

    # 2. Hard blocks -> Tier C (persist with unplotted_reason, never render).
    qa_flags = getattr(rec, "qa_flags", []) or getattr(rec, "flags", []) or []
    unplotted_reason = getattr(rec, "unplotted_reason", None)

    if (
        getattr(rec, "data_quality", DataQuality.EXPLICIT) == DataQuality.INVALID
        or any(flag in C_TIER_BLOCKERS for flag in qa_flags)
        or unplotted_reason in C_TIER_UNPLOTTED
        or not has_valid_geometry
    ):
        rec.triage_tier = TriageTier.C
        if not getattr(rec, "unplotted_reason", None):
            rec.unplotted_reason = "no_valid_geometry"
        return

    # 3. Inferred / repaired / filtered / AI -> Tier B (human review queue).
    data_quality = getattr(rec, "data_quality", DataQuality.EXPLICIT)
    parsing_method = getattr(rec, "parsing_method", ParsingMethod.RULE)
    applicable_vessel_filter = getattr(rec, "applicable_vessel_filter", None)
    duplicate_of_id = getattr(rec, "duplicate_of_id", None)

    has_repairs = any(getattr(c, "repairs", []) for c in coords)

    if (
        data_quality in (DataQuality.INFERRED, DataQuality.AMBIGUOUS)
        or parsing_method != ParsingMethod.RULE
        or has_repairs
        or applicable_vessel_filter is not None
        or duplicate_of_id is not None
        or len(qa_flags) > 0
    ):
        rec.triage_tier = TriageTier.B
        return

    # 4. Explicit + rule-parsed + clean + geometry -> Tier A.
    rec.triage_tier = TriageTier.A
