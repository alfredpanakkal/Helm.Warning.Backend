#!/usr/bin/env python3
"""shared/models.py — Triage, provenance, maritime attribute models, and payload builders.
Shared by all parsers and the sync engine.
Aligned with 20261019/20261020 PostgreSQL/Supabase schema.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
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


# --- shared issue-DTG extractor (Alfred, 2026-11-07) -----------------------
#
# One deterministic, fail-closed extractor for warning issue dates carried
# as a bare time group at the START (NGA memo DTG line above the header,
# IV/XII) or the END (NAVTEX-style trailing group, IX; NHO India slash
# form, VIII) of a block. No AI step; nothing is guessed: Z/UTC is
# REQUIRED (timezone must be stated), the year is REQUIRED, and the month
# maps through the explicit dict below (no locale-dependent %b/%B).

ISSUE_DTG_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Whole-line issue time group: DDHHMM + (Z | UTC) + ("/" | whitespace) +
# MONTH (3-letter or full English name) + whitespace + YEAR (2 or 4
# digits). "301639Z OCT 26", "051500 UTC NOV 2026", "021102Z/NOV 26".
RE_ISSUE_DTG_LINE = re.compile(
    r"^(\d{2})(\d{2})(\d{2})(?:Z|\s+UTC)(?:/|\s+)([A-Za-z]{3,9})\.?\s+(\d{2,4})$",
    re.IGNORECASE)

# Second guard behind the whole-line match: a candidate line carrying
# dateline/range/bulletin vocabulary is never an issue date.
RE_ISSUE_DTG_BLOCKWORDS = re.compile(
    r"\b(?:CANCEL|UNTIL|TO|FROM|IN\s+FORCE|AS\s+ON|CORRECT\s+AT|ISSUED)\b",
    re.IGNORECASE)


def _match_issue_dtg_line(line):
    """One candidate line -> verbatim time-group string, or None.

    Strips a BOM and leading dashes/spaces, then requires the ENTIRE
    line to be one time group. Month via the explicit dict (full
    English names accepted). Day/hour/minute range checks plus a
    calendar-existence check (Feb 30 rejected). Never clamps, never
    guesses a timezone or a century ("00-"68 -> 2000s only).
    """
    if not line:
        return None
    candidate = line.replace("\ufeff", "").strip()
    candidate = re.sub(r"^[\s\-\u2010-\u2015]+", "", candidate)
    if not candidate or RE_ISSUE_DTG_BLOCKWORDS.search(candidate):
        return None
    m = RE_ISSUE_DTG_LINE.match(candidate)
    if not m:
        return None
    dd, hh, mi, mon, ytok = m.groups()
    month = ISSUE_DTG_MONTHS.get(mon.lower())
    if month is None:
        return None
    if not (1 <= int(dd) <= 31 and 0 <= int(hh) <= 23 and 0 <= int(mi) <= 59):
        return None
    if len(ytok) not in (2, 4):
        return None
    year = int(ytok)
    if year < 100:
        if year > 68:
            return None  # 69-99: no century guess, fail closed
        year += 2000
    try:
        datetime(year, month, int(dd))
    except ValueError:
        return None
    return m.group(0)


def _parse_issue_dtg_token(s):
    """ISO timestamp from a verbatim issue-DTG token, or None."""
    token = _match_issue_dtg_line(s or "")
    if token is None:
        return None
    dd, hh, mi, mon, ytok = RE_ISSUE_DTG_LINE.match(token).groups()
    month = ISSUE_DTG_MONTHS.get(mon.lower())
    year = int(ytok)
    if year < 100:
        if year > 68:
            return None  # parity with _match_issue_dtg_line (69-99 fail closed)
        year += 2000
    return datetime(year, month, int(dd), int(hh), int(mi)).isoformat()


def extract_issue_dtg(raw_text):
    """Shared, deterministic, fail-closed issue-date extractor.

    Only the FIRST and the LAST non-empty line of the block are
    candidates, and the whole line must be one time group
    ("301639Z OCT 26", "051500 UTC NOV 2026", "021102Z/NOV 26", or a
    dashes-prefixed "------- 271002Z/SEP 26"). Returns the matched
    text verbatim (stripped of BOM/dashes/spaces only) or None. If
    BOTH candidate lines match and disagree, returns None - no
    pick, no guess (callers may surface such blocks via qa_flags).
    """
    lines = [l for l in (raw_text or "").split("\n") if l and l.strip()]
    if not lines:
        return None
    first = _match_issue_dtg_line(lines[0])
    last = _match_issue_dtg_line(lines[-1])
    if first is not None and last is not None and first != last:
        return None
    return first if first is not None else last


def issue_dtg_is_future(token, now_utc, max_days=2):
    """Pure future guard for a verbatim issue-DTG token (no clock reads).

    True only when the parsed issue datetime is LATER than
    now_utc + max_days days. Boundary inclusive: exactly
    now_utc + max_days is accepted. Every datetime is normalized to
    aware UTC before comparing (naive values are assumed UTC), so a
    naive utcnow() value never raises TypeError against an aware
    one. None / unparseable token or now_utc -> False (the wiring
    nulls the token separately; this helper only answers the
    comparison).
    """
    if not token or now_utc is None:
        return False
    iso = _parse_issue_dtg_token(token)
    if iso is None:
        return False
    dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    now = now_utc
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return dt > now + timedelta(days=max_days)


def issue_dtg_has_conflict(raw_text):
    """True when the first AND last non-empty line of the block each
    match a whole-line time group and DISAGREE - the condition under
    which extract_issue_dtg() returns None without picking either.
    Pure: no clock, no mutation; the caller appends the qa flag.
    """
    lines = [l for l in (raw_text or "").split("\n") if l and l.strip()]
    if len(lines) < 2:
        return False
    first = _match_issue_dtg_line(lines[0])
    last = _match_issue_dtg_line(lines[-1])
    return first is not None and last is not None and first != last


def parse_safe_iso_timestamp(date_val: Any) -> Optional[str]:
    """Tolerantly parses timestamp or date string into ISO-8601 string.
    Returns None if date is free-text (e.g., '2026 HOURS 19 OCT') or invalid.
    Also parses NAVAREA DTG issue-date headers ('030020Z JUL 26' -> the
    warning's issue UTC; Z suffix guarantees UTC, never a hemisphere guess).
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

    # Issue-DTG token ("301639Z OCT 26", "021102Z/NOV 26") - explicit
    # month-dict parse, locale-independent (strptime %b/%B avoided).
    iso = _parse_issue_dtg_token(s)
    if iso is not None:
        return iso

    # Try common standardized formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d%H%M UTC %b %y",
        "%d%H%M UTC %b %Y",
        "%d%H%MZ %b %y",
        "%d%H%MZ %b %Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if "%y" in fmt and dt.year < 2000:
                # 2-digit years 69-99 parse as 19xx under %y - that is a
                # century guess. Fail closed like the DTG-token path
                # (69-99 -> None), never resurrect a rejected year.
                continue
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
    Outputs geometry rows with source-stated buffer, corridor, and sweep metadata.
    feature_type MUST use the database CHECK-constraint vocabulary.

    Per-feature "properties.zone_label" (e.g. NAVAREA XII sub-area labels
    A./B./C.) overrides the record-level label so each sub-area persists as
    its own geometry row.
    """
    geometries: List[Dict[str, Any]] = []

    def _append_geometry(geojson_obj: Dict[str, Any], label: str, buffer_val: Any = 0.0, props: Optional[Dict[str, Any]] = None) -> None:
        if not isinstance(geojson_obj, dict):
            return
        geom_type = geojson_obj.get("type")
        if not geom_type:
            return

        props = props if isinstance(props, dict) else {}

        # 1. Resolve and validate buffer_nm FIRST (handling explicit 0.0)
        raw_buffer = props.get("buffer_nm")
        if raw_buffer is None:
            raw_buffer = buffer_val
        try:
            buffer_nm = float(raw_buffer if raw_buffer is not None else 0.0)
        except (TypeError, ValueError):
            buffer_nm = 0.0
        if not math.isfinite(buffer_nm) or buffer_nm < 0:
            buffer_nm = 0.0

        if geom_type == "MultiPoint":
            # Discrete locations (e.g. 'IN VICINITY OF' wellhead lists):
            # persist one POINT geometry row per location instead of a
            # single row holding a MultiPoint (which would tempt
            # renderers to connect or hull the points).
            coords = geojson_obj.get("coordinates") or []
            for idx, c in enumerate(coords):
                try:
                    lon_v, lat_v = float(c[0]), float(c[1])
                except (TypeError, ValueError, IndexError):
                    continue
                geometries.append({
                    "zone_label": label if len(coords) == 1 else f"{label} {idx + 1}",
                    "feature_type": "POINT",
                    "buffer_nm": buffer_nm,
                    "geojson": {"type": "Point", "coordinates": [lon_v, lat_v]},
                })
            return

        # 2. Resolve and validate feature_type against geom_type
        raw_ftype = props.get("feature_type") or record.get("feature_type")
        if raw_ftype:
            raw_ftype = str(raw_ftype).strip().upper()

        if raw_ftype == "SWEEP_ARC":
            feature_type = "SWEEP_ARC" if geom_type == "Polygon" else geojson_type_to_feature_type(geom_type)
        elif raw_ftype == "BOUNDING_BOX":
            feature_type = "BOUNDING_BOX" if geom_type in ("Polygon", "MultiPolygon") else geojson_type_to_feature_type(geom_type)
        elif raw_ftype == "CORRIDOR":
            feature_type = "CORRIDOR" if geom_type in ("LineString", "MultiLineString") else geojson_type_to_feature_type(geom_type)
        elif raw_ftype == "POINT":
            feature_type = "POINT" if geom_type in ("Point", "MultiPoint") else geojson_type_to_feature_type(geom_type)
        elif raw_ftype == "LINE":
            feature_type = "LINE" if geom_type in ("LineString", "MultiLineString") else geojson_type_to_feature_type(geom_type)
        elif raw_ftype == "POLYGON":
            feature_type = "POLYGON" if geom_type in ("Polygon", "MultiPolygon") else geojson_type_to_feature_type(geom_type)
        elif buffer_nm > 0 and geom_type in ("LineString", "MultiLineString"):
            feature_type = "CORRIDOR"
        elif geom_type == "Polygon" and props.get("sweep_radius_nm") is not None:
            feature_type = "SWEEP_ARC"
        elif geom_type == "Polygon" and (props.get("is_bounding_box") or record.get("archetype") == "bounding_box"):
            feature_type = "BOUNDING_BOX"
        else:
            feature_type = geojson_type_to_feature_type(geom_type)

        payload = {
            "zone_label": label,
            "feature_type": feature_type,
            "buffer_nm": buffer_nm,
            "geojson": geojson_obj,
        }
        # Sweep-arc metadata (NAVAREA II 358/26 firing-exercise sectors)
        for key in (
            "corridor_half_width_nm",
            "corridor_clearance_nm",
            "sweep_radius_nm",
            "sweep_start_azimuth",
            "sweep_end_azimuth",
        ):
            if props.get(key) is not None:
                payload[key] = props[key]
        geometries.append(payload)

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
                props,
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
                    props,
                )
            if geometries:
                return geometries
        elif sp_type in ("Point", "Polygon", "LineString", "MultiPoint", "MultiPolygon", "MultiLineString"):
            props = spatial.get("properties") if isinstance(spatial.get("properties"), dict) else {}
            if not props:
                props = {}
                for k in (
                    "feature_type", "buffer_nm", "corridor_half_width_nm",
                    "corridor_clearance_nm", "sweep_radius_nm", "sweep_start_azimuth", "sweep_end_azimuth",
                ):
                    if spatial.get(k) is not None:
                        props[k] = spatial.get(k)
                    elif record.get(k) is not None:
                        props[k] = record.get(k)
            buf = props.get("buffer_nm", record.get("buffer_nm", 0.0))
            _append_geometry(spatial, record.get("title") or "Spatial Feature", buf, props)
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

    # Determine triage tier. Mirror chk_tier_a_invariants in the database:
    # Tier A requires explicit data, rule parsing, no unplotted reason, and a
    # status other than superseded. Geometry is also required for auto-plotting.
    geoms = build_geometry_payloads(record)
    data_quality = record.get("data_quality", "EXPLICIT")
    parsing_method = record.get("parsing_method", "RULE")
    unplotted_reason = record.get("unplotted_reason")
    tier_a_eligible = (
        bool(geoms)
        and data_quality == "EXPLICIT"
        and unplotted_reason is None
        and parsing_method == "RULE"
        and status != "superseded"
    )
    requested_tier = record.get("triage_tier")

    if not geoms:
        triage_tier = "C"
        if not unplotted_reason:
            # Silent-discard fix: a blanket 'no_valid_geometry' hid the
            # actual refusal reason. Map the parser's qa flags onto the
            # schema's unplotted_reason vocabulary; 'no_valid_geometry'
            # only when the parse was truly silent.
            qa_flags = record.get("qa_flags") or []
            if "MISSING_HEM" in qa_flags:
                unplotted_reason = "missing_hemisphere"
            elif "VALIDATION_FAILED" in qa_flags:
                unplotted_reason = "validation_failed"
            else:
                unplotted_reason = "no_valid_geometry"
    elif requested_tier:
        triage_tier = requested_tier
        if triage_tier == "A" and not tier_a_eligible:
            # Keep geometry-bearing but ineligible records visible for review.
            triage_tier = "B"
    else:
        triage_tier = "A" if tier_a_eligible else "B"

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
        "data_quality": data_quality,
        "parsing_method": parsing_method,
        "qa_flags": record.get("qa_flags", []),
        "unplotted_reason": unplotted_reason,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "raw_text": record.get("raw_text") or record.get("warning_text") or "",
        "source_id": record.get("source_id", ""),
    }
