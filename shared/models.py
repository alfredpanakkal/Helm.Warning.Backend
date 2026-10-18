#!/usr/bin/env python3
"""shared/models.py — Triage, provenance, and maritime attribute models.
Shared by all parsers and the sync engine."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TriageTier(str, Enum):
    A = "A"   # Auto-plot: EXPLICIT, rule-parsed, zero flags, valid geometry
    B = "B"   # Review queue: INFERRED/AMBIGUOUS, repaired, filtered, or AI-proposed
    C = "C"   # Blocked: never rendered on map, persisted with unplotted_reason


class DataQuality(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"


class ParsingMethod(str, Enum):
    RULE = "RULE"
    AI = "AI"


UNPLOTTED_REASONS = {
    "missing_hemisphere", "truncated_clause", "empty_stub", "orphan_fragment",
    "meta_list", "validation_failed", "no_valid_geometry",
}


@dataclass
class CoordinateProvenance:
    raw_token: str
    lat: Optional[float]
    lon: Optional[float]
    quality: DataQuality = DataQuality.EXPLICIT
    repairs: list[str] = field(default_factory=list)   # e.g. ["rule18"]
    flags: list[str] = field(default_factory=list)     # e.g. ["MISSING_HEM"]


@dataclass
class TriageRecord:
    """Mixin contract for any warning record flowing through triage/sync."""
    data_quality: DataQuality = DataQuality.EXPLICIT
    parsing_method: ParsingMethod = ParsingMethod.RULE
    triage_tier: TriageTier = TriageTier.C
    qa_flags: list[str] = field(default_factory=list)
    unplotted_reason: Optional[str] = None
    duplicate_of_id: Optional[str] = None
    coordinates: list[CoordinateProvenance] = field(default_factory=list)
    # Maritime attributes (nullable; absent = not stated in the bulletin)
    shoal_depth_m: Optional[float] = None
    tow_length_m: Optional[float] = None
    tow_speed_kts: Optional[float] = None
    applicable_vessel_filter: Optional[str] = None

    def to_db_row(self, base: dict) -> dict:
        """Merge triage/provenance fields into an existing DB upsert row."""
        base.update({
            "data_quality": self.data_quality.value,
            "parsing_method": self.parsing_method.value,
            "triage_tier": self.triage_tier.value,
            "qa_flags": self.qa_flags,
            "unplotted_reason": self.unplotted_reason,
            "duplicate_of_id": self.duplicate_of_id,
            "shoal_depth_m": self.shoal_depth_m,
            "tow_length_m": self.tow_length_m,
            "tow_speed_kts": self.tow_speed_kts,
            "applicable_vessel_filter": self.applicable_vessel_filter,
            "coordinate_provenance": [
                {
                    "raw_token": c.raw_token, "lat": c.lat, "lon": c.lon,
                    "quality": c.quality.value, "repairs": c.repairs, "flags": c.flags,
                }
                for c in self.coordinates
            ],
        })
        return base
