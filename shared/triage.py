#!/usr/bin/env python3
"""shared/triage.py — H02 Triage Precedence gate & Audit Trail.
Guarantees TriageTier.A is strictly reserved for explicit, rule-parsed
records with verified geometry. Zero-coordinate records can never reach A."""

from __future__ import annotations
from typing import Any
import logging
import math

from shared.models import (
    DataQuality, ParsingMethod, TriageTier,
    qa_flags_require_review, unplotted_reason_from_qa_flags,
    normalize_unplotted_reason,
)
from shared.logging import get_logger

logger = get_logger("triage")


def _valid_lat_lon(lat: Any, lon: Any) -> bool:
    try:
        lat_value, lon_value = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(lat_value) and math.isfinite(lon_value)
        and -90 <= lat_value <= 90 and -180 <= lon_value <= 180
    )


def assign_final_triage(rec: Any) -> None:
    """Run after all parsing, repairs, AI escalation, and geometry construction."""
    original_tier = getattr(rec, "triage_tier", None)
    original_quality = getattr(rec, "data_quality", None)

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

    has_valid_geometry = any(
        _valid_lat_lon(getattr(coord, "lat", None), getattr(coord, "lon", None))
        for coord in coords
    )
    if not has_valid_geometry:
        vertices = getattr(rec, "vertices_lonlat", None) or []
        has_valid_geometry = any(
            isinstance(vertex, (list, tuple)) and len(vertex) >= 2
            and _valid_lat_lon(vertex[1], vertex[0])
            for vertex in vertices
        )
    if not has_valid_geometry:
        has_valid_geometry = _valid_lat_lon(
            getattr(rec, "latitude", None), getattr(rec, "longitude", None)
        )

    # 2. Hard blocks -> Tier C (persist with unplotted_reason, never render).
    qa_flags = getattr(rec, "qa_flags", []) or getattr(rec, "flags", []) or []
    unplotted_reason = normalize_unplotted_reason(
        getattr(rec, "unplotted_reason", None), qa_flags
    )
    if unplotted_reason is not None:
        rec.unplotted_reason = unplotted_reason

    if not has_valid_geometry:
        rec.triage_tier = TriageTier.C
        if not getattr(rec, "unplotted_reason", None):
            rec.unplotted_reason = (
                unplotted_reason_from_qa_flags(qa_flags) or "no_valid_geometry"
            )
    else:
        # Any geometry-bearing partial failure, repair, AI parse, or lifecycle
        # exception remains visible for review; it cannot enter Tier A.
        data_quality = getattr(rec, "data_quality", DataQuality.EXPLICIT)
        parsing_method = getattr(rec, "parsing_method", ParsingMethod.RULE)
        applicable_vessel_filter = getattr(rec, "applicable_vessel_filter", None)
        duplicate_of_id = getattr(rec, "duplicate_of_id", None)
        has_repairs = any(getattr(c, "repairs", []) for c in coords)
        status = getattr(rec, "status", "active")

        if (
            data_quality != DataQuality.EXPLICIT
            or parsing_method != ParsingMethod.RULE
            or has_repairs
            or applicable_vessel_filter is not None
            or duplicate_of_id is not None
            or qa_flags_require_review(qa_flags)
            or status == "superseded"
            or unplotted_reason is not None
        ):
            rec.triage_tier = TriageTier.B
        else:
            # Explicit + rule-parsed + clean + valid geometry -> Tier A.
            rec.triage_tier = TriageTier.A

    # Structured Audit Logging of decision
    new_tier = rec.triage_tier
    new_quality = rec.data_quality
    logger.info(
        "Triage decision assigned",
        extra={
            "warning_id": getattr(rec, "warning_id", "unknown"),
            "original_tier": str(original_tier),
            "new_tier": new_tier.value if hasattr(new_tier, "value") else str(new_tier),
            "original_quality": str(original_quality),
            "new_quality": new_quality.value if hasattr(new_quality, "value") else str(new_quality),
            "coordinate_count": len(coords),
            "qa_flags": qa_flags,
            "unplotted_reason": getattr(rec, "unplotted_reason", None),
        }
    )
