#!/usr/bin/env python3
"""shared/models.py — Triage, provenance, maritime attribute models, and payload builders.
Shared by all parsers and the sync engine.
Aligned with 20261019/20261020 PostgreSQL/Supabase schema.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Optional, Any, Dict, List


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


def parse_safe_iso_timestamp(date_val: Any) -> Optional[str]:
    """Tolerantly parses timestamp or date string into ISO-8601 string.
    Returns None if date is free-text (e.g., '2026 HOURS 19 OCT') or invalid.
    """
    if not date_val:
        return None
    s = str(date_val).strip()
    if not s:
        return None

    # Try ISO format directly
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.isoformat()
    except Exception:
        pass

    # Try common standardized formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d%H%M UTC %b %y",
        "%d%H%M UTC %b %Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.isoformat()
        except Exception:
            continue

    return None


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
        canonical_id = base.get("canonical_id")
        if not canonical_id:
            nav = (base.get("navarea") or "").strip()
            wid = (base.get("warning_id") or "").strip()
            canonical_id = f"{nav} {wid}".strip() if (nav and wid) else (wid or "UNKNOWN")

        if "categories" not in base:
            cat = base.get("category")
            base["categories"] = [cat] if cat else ["general"]
        elif isinstance(base.get("categories"), list) and not base["categories"]:
            base["categories"] = ["general"]

        base.update({
            "canonical_id": canonical_id,
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


def format_canonical_id(navarea: Optional[str], warning_id: Optional[str]) -> str:
    """Format canonical_id according to convention: '{NAVAREA} {warning_id}'."""
    nav = (navarea or "").strip()
    wid = (warning_id or "").strip()
    if nav and wid:
        if wid.startswith(nav):
            return wid
        return f"{nav} {wid}"
    return wid or nav or "UNKNOWN"


def geojson_type_to_feature_type(geojson_type: Optional[str]) -> str:
    """Maps a GeoJSON geometry type to the public.nav_warning_geometries
    feature_type CHECK-constraint vocabulary:
    ('POINT', 'LINE', 'POLYGON', 'CORRIDOR', 'SWEEP_ARC', 'BOUNDING_BOX').
    Note: lowercase values like 'point' violate the CHECK and abort the
    upsert_nav_warning RPC transaction.
    """
    t = (geojson_type or "Point").strip().upper()
    if t in ("LINESTRING", "MULTILINESTRING"):
        return "LINE"
    if t in ("MULTIPOINT",):
        return "POINT"
    if t in ("MULTIPOLYGON",):
        return "POLYGON"
    if t in ("POINT", "POLYGON", "CORRIDOR", "SWEEP_ARC", "BOUNDING_BOX"):
        return t
    # Unknown geometry type: persist as POINT so the record still plots
    return "POINT"


def build_geometry_payloads(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Builds GeoJSON geometry child records suitable for public.nav_warning_geometries.
    Outputs: list of dicts with keys: zone_label, feature_type, buffer_nm, geojson
    feature_type MUST use the DB CHECK-constraint vocabulary (POINT/LINE/POLYGON).

    Per-feature "properties.zone_label" (e.g. NAVAREA XII sub-area labels
    A./B./C.) overrides the record-level label so each sub-area persists as
    its own geometry row.
    """
    geometries: List[Dict[str, Any]] = []

    def _append_geometry(geojson_obj: Dict[str, Any], label: str, buffer_val: Any = 0.0) -> None:
        if not isinstance(geojson_obj, dict):
            return
        geom_type = geojson_obj.get("type")
        if not geom_type:
            return
        try:
            buffer_nm = float(buffer_val or 0.0)
        except (TypeError, ValueError):
            buffer_nm = 0.0
        geometries.append({
            "zone_label": label,
            "feature_type": geojson_type_to_feature_type(geom_type),
            "buffer_nm": buffer_nm,
            "geojson": geojson_obj,
        })

    spatial = record.get("spatial")
    if isinstance(spatial, dict):
        sp_type = spatial.get("type", "")
        if sp_type == "Feature":
            geom = spatial.get("geometry") or {}
            props = spatial.get("properties") if isinstance(spatial.get("properties"), dict) else {}
            _append_geometry(
                geom,
                props.get("zone_label") or record.get("title") or "Spatial Feature",
                props.get("buffer_nm", 0.0),
            )
            return geometries
        if sp_type == "FeatureCollection":
            features = spatial.get("features") or []
            label = record.get("title") or "Spatial Feature"
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                geom = feature.get("geometry") or {}
                props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                _append_geometry(
                    geom,
                    props.get("zone_label") or label,
                    props.get("buffer_nm", 0.0),
                )
            if geometries:
                return geometries
        elif sp_type in ("Point", "Polygon", "LineString", "MultiPoint", "MultiPolygon", "MultiLineString"):
            _append_geometry(spatial, record.get("title") or "Spatial Feature", 0.0)
            return geometries

    # Fallback to lat/lon if available
    lat = record.get("latitude")
    lon = record.get("longitude")
    if lat is not None and lon is not None:
        try:
            flat = float(lat)
            flon = float(lon)
            if -90 <= flat <= 90 and -180 <= flon <= 180:
                geometries.append({
                    "zone_label": "Centroid",
                    "feature_type": "POINT",
                    "buffer_nm": 0.0,
                    "geojson": {
                        "type": "Point",
                        "coordinates": [flon, flat]
                    }
                })
        except (ValueError, TypeError):
            pass

    return geometries


def build_master_payload(record: Dict[str, Any]) -> Dict[str, Any]:
    """Builds schema-compliant master record for public.nav_warnings.
    Strips legacy flat columns (latitude, longitude, spatial, issued_text)
    and populates canonical_id, categories array, triage tier, and safe ISO dates.
    """
    navarea = (record.get("navarea") or "").strip()
    wid = str(record.get("warning_id") or "").strip()
    canonical_id = record.get("canonical_id") or format_canonical_id(navarea, wid)

    # Categories array
    categories: List[str] = []
    if "categories" in record and isinstance(record["categories"], list):
        categories = [str(c).strip().lower() for c in record["categories"] if c]
    elif "category" in record and record["category"]:
        categories = [str(record["category"]).strip().lower()]
    if not categories:
        categories = ["general"]
    # De-duplicate while preserving order
    seen_cats = set()
    cleaned_cats = []
    for c in categories:
        if c not in seen_cats:
            seen_cats.add(c)
            cleaned_cats.append(c)

    title = record.get("title") or f"{canonical_id}"
    area_text = record.get("area_text") or record.get("general_area") or record.get("subarea") or record.get("issued_text")
    status = record.get("status") or "active"

    # Determine triage tier
    geoms = build_geometry_payloads(record)
    default_tier = "A" if geoms else "C"
    triage_tier = record.get("triage_tier") or default_tier
    unplotted_reason = record.get("unplotted_reason")
    if not geoms:
        triage_tier = "C"
        unplotted_reason = unplotted_reason or "no_valid_geometry"

    valid_from = parse_safe_iso_timestamp(record.get("valid_from") or record.get("publication_time") or record.get("issued_text"))
    valid_to = parse_safe_iso_timestamp(record.get("valid_to") or record.get("cancellation_date"))

    return {
        "canonical_id": canonical_id,
        "navarea": navarea or "NAVAREA",
        "title": title[:255],
        "area_text": area_text,
        "categories": cleaned_cats,
        "status": status,
        "triage_tier": triage_tier,
        "data_quality": record.get("data_quality", "EXPLICIT"),
        "parsing_method": record.get("parsing_method", "RULE"),
        "qa_flags": record.get("qa_flags", []),
        "unplotted_reason": unplotted_reason,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "raw_text": record.get("raw_text") or record.get("warning_text") or "",
        "source_id": record.get("source_id", ""),
    }
