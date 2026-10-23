#!/usr/bin/env python3
"""
shared/utils.py — Common utilities for all NAVAREA parsers
Includes hardened input validation, coordinate repairs, centroid computation, and error context.
"""

import sys
import re
import math
from typing import Dict, List, Tuple, Set, Any, Optional

from shared.exceptions import ParseError, ValidationError
from shared.geometry_classifier import classify_geometry_archetype, ring_is_simple
from shared.validation import (
    validate_coordinate_token,
    validate_warning_id,
    validate_raw_text,
    validate_lat_lon,
    validate_public_inputs,
)

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Rule 18 (Peru decimal-hyphen): 11-49-992S -> 11-49.992S
RE_RULE_18 = re.compile(r"^(\d{1,2})-(\d{2})-(\d{3,})([NSEW])$")
# Rule 19 (double-period): 049.01.55E -> 049-01.55E
RE_RULE_19 = re.compile(r"^(\d{2,3})\.(\d{2})\.(\d{2})([NSEW])$")
# Rule 20 (degree padding): 021-26.90N -> 21-26.90N ; 42-08.00E -> 042-08.00E
RE_RULE_20_LAT = re.compile(r"^0(\d{2})-(\d{2}(?:\.\d+)?)([NS])$")
RE_RULE_20_LON = re.compile(r"^(\d{2})-(\d{2}(?:\.\d+)?)([EW])$")
# Rule 93 (European decimal comma): 44-05,12N -> 44-05.12N
RE_RULE_93 = re.compile(r"^(\d{1,3})-(\d{2}),(\d+)([NSEW])$")


def repair_coordinate_token(raw_token: str) -> tuple[str, list[str]]:
    """Returns (repaired_token, applied_rules). Unchanged token -> (raw_token, [])."""
    if raw_token is None:
        return "", []
    t = str(raw_token).strip()
    if not t:
        return "", []

    applied_rules: list[str] = []

    m = RE_RULE_18.match(t)
    if m:
        deg, mins, secs, hem = m.groups()
        minutes = float(f"{mins}.{secs}") if int(secs) >= 100 or len(secs) > 2 else None
        if minutes is not None:
            if minutes >= 60:
                deg = str(int(deg) + int(minutes // 60))
                minutes = minutes % 60
            deg_int = int(deg)
            deg_str = f"{deg_int:02d}" if deg_int < 100 else f"{deg_int}"
            return f"{deg_str}-{minutes:06.3f}".rstrip('0').rstrip('.') + hem, ["rule18"]

    m = RE_RULE_19.match(t)
    if m:
        deg, mins, secs, hem = m.groups()
        return f"{deg}-{mins}.{secs}{hem}", ["rule19"]

    m = RE_RULE_20_LAT.match(t)
    if m:
        deg, mins, hem = m.groups()
        return f"{int(deg)}-{mins}{hem}", ["rule20"]

    m = RE_RULE_20_LON.match(t)
    if m:
        deg, mins, hem = m.groups()
        return f"{deg.zfill(3)}-{mins}{hem}", ["rule20"]

    m = RE_RULE_93.match(t)
    if m:
        deg, mins, frac, hem = m.groups()
        return f"{deg}-{mins}.{frac}{hem}", ["rule93"]

    return t, applied_rules


def parse_coordinate_with_provenance(raw_text: str, raw_token: str) -> Any:
    """Wraps parse_coordinates(); never fabricates hemispheres (Rule 17)."""
    from shared.models import CoordinateProvenance, DataQuality

    if not raw_token or not isinstance(raw_token, str) or not raw_token.strip():
        provenance = CoordinateProvenance(raw_token=str(raw_token or ""), lat=None, lon=None)
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("EMPTY_TOKEN")
        return provenance

    try:
        token_clean = validate_coordinate_token(raw_token)
    except ValidationError:
        provenance = CoordinateProvenance(raw_token=str(raw_token), lat=None, lon=None)
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("VALIDATION_FAILED")
        return provenance
    repaired, rules = repair_coordinate_token(token_clean)
    provenance = CoordinateProvenance(raw_token=raw_token, lat=None, lon=None)

    if not re.search(r"[NSEW]$", repaired, re.IGNORECASE):
        provenance.quality = DataQuality.AMBIGUOUS
        provenance.flags.append("MISSING_HEM")
        return provenance

    # Check if the token itself is a full pair
    parsed_coords, lat, lon, spatial = parse_coordinates(repaired)

    # If the token was a single axis (e.g. lat only), extract coordinate pair from raw_text
    if (lat is None or lon is None) and raw_text:
        # Check text with repaired token substituted
        search_text = raw_text.replace(raw_token, repaired)
        parsed_coords, lat, lon, spatial = parse_coordinates(search_text)

    if lat is None or lon is None:
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("VALIDATION_FAILED")
        return provenance

    provenance.lat, provenance.lon = lat, lon
    if rules:
        provenance.quality = DataQuality.INFERRED
        provenance.repairs.extend(rules)
    else:
        provenance.quality = DataQuality.EXPLICIT

    return provenance


def convert_to_decimal(
    degrees: Any,
    minutes: Any,
    direction_or_seconds: Any = None,
    direction: Optional[str] = None
) -> float:
    """
    Converts Degrees and Decimal Minutes (or Seconds) into Signed Decimal Degrees (WGS84).
    Supports 3-arg (deg, min, dir) and 4-arg (deg, min, sec, dir).
    Returns math.nan on out-of-bounds or invalid inputs (never clamps).
    """
    try:
        deg_f = float(degrees)
        min_f = float(minutes)
    except (TypeError, ValueError):
        return float('nan')

    # Resolve arguments
    if direction is None:
        # 3-arg signature: convert_to_decimal(deg, min, dir)
        dir_str = str(direction_or_seconds or '').strip().upper()
        sec_f = 0.0
    else:
        # 4-arg signature: convert_to_decimal(deg, min, sec, dir)
        dir_str = str(direction or '').strip().upper()
        try:
            sec_f = float(direction_or_seconds) if direction_or_seconds is not None else 0.0
        except (TypeError, ValueError):
            return float('nan')

    # Boundary checks: degrees must be non-negative, minutes and seconds in [0, 60)
    if deg_f < 0.0 or min_f < 0.0 or min_f >= 60.0 or sec_f < 0.0 or sec_f >= 60.0:
        return float('nan')

    total_degrees = deg_f + (min_f / 60.0) + (sec_f / 3600.0)

    # Direction specific bounds
    if dir_str in ('N', 'S'):
        if total_degrees > 90.0:
            return float('nan')
        if dir_str == 'S':
            total_degrees = -total_degrees
    elif dir_str in ('E', 'W'):
        if total_degrees > 180.0:
            return float('nan')
        if dir_str == 'W':
            total_degrees = -total_degrees
    else:
        # Unknown or missing direction
        return float('nan')

    return round(total_degrees, 6)


def _is_valid_latlon(lat_deg: Any, lat_min: Any, lon_deg: Any, lon_min: Any) -> bool:
    """
    Strict coordinate value validation:
      - |latitude| <= 90, |longitude| <= 180
      - 0 <= minutes < 60
    """
    try:
        lat_d = float(lat_deg)
        lat_m = float(lat_min)
        lon_d = float(lon_deg)
        lon_m = float(lon_min)
    except (TypeError, ValueError):
        return False
    if lat_m < 0 or lat_m >= 60 or lon_m < 0 or lon_m >= 60:
        return False
    if abs(lat_d) + lat_m / 60.0 > 90.0:
        return False
    if abs(lon_d) + lon_m / 60.0 > 180.0:
        return False
    return True


# Standalone axis tokens for 'AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO
# <lon>' bulletins (NAVAREA VIII 1102/26): latitudes and longitudes are
# listed SEPARATELY, so the pair-based pattern extracts nothing.
RE_AXIS_LAT = re.compile(r"(?<![\d.])(\d{1,2})-(\d{2}(?:\.\d+)?)([NS])(?![\d.])")
RE_AXIS_LON = re.compile(r"(?<![\d.])(\d{1,3})-(\d{2}(?:\.\d+)?)([EW])(?![\d.])")


def _bbox_from_axis_tokens(raw_text: str):
    """
    Builds a closed rectangle ring for 'AREA BOUNDED WITHIN' bulletins
    whose latitudes and longitudes are listed as separate axis ranges
    (e.g. 14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E).
    Returns (spatial, centroid_lat, centroid_lon) or (None, None, None).
    Gated on the bbox phrase so unrelated lat/lon mentions never
    fabricate an area (fail-closed outside the known format).
    """
    from shared.geometry_classifier import RE_BBOX

    if not raw_text or not RE_BBOX.search(raw_text.upper()):
        return None, None, None

    lats = set()
    for m in RE_AXIS_LAT.finditer(raw_text):
        deg, mins, hem = m.groups()
        if _is_valid_latlon(deg, mins, "0", "0"):
            val = convert_to_decimal(deg, mins, hem)
            if not math.isnan(val):
                lats.add(val)
    lons = set()
    for m in RE_AXIS_LON.finditer(raw_text):
        deg, mins, hem = m.groups()
        if _is_valid_latlon("0", "0", deg, mins):
            val = convert_to_decimal(deg, mins, hem)
            if not math.isnan(val):
                lons.add(val)

    if len(lats) != 2 or len(lons) != 2:
        return None, None, None  # not a clean two-corner range: fail closed

    lat_s, lat_n = sorted(lats)
    lon_w, lon_e = sorted(lons)
    ring = [
        [lon_w, lat_s], [lon_e, lat_s], [lon_e, lat_n], [lon_w, lat_n], [lon_w, lat_s],
    ]
    spatial = {"type": "Polygon", "coordinates": [ring]}
    return spatial, round((lat_s + lat_n) / 2, 6), round((lon_w + lon_e) / 2, 6)


def parse_coordinates(raw_text: str):
    """
    Extracts navigational coordinates from text.
    Handles DD-MM.MM[N/S] DDD-MM.MM[E/W] format.
    Returns: (parsed_coords_list, primary_lat, primary_lon, spatial_geojson)
    For polygons and line segments, primary_lat and primary_lon represent the centroid.
    """
    if not raw_text or not isinstance(raw_text, str):
        return [], None, None, None

    pattern = r'(\d{2,3})-(\d{2}(?:\.\d+)?)[NS]\s+(\d{2,3})-(\d{2}(?:\.\d+)?)[EW]'
    matches = list(re.finditer(pattern, raw_text, re.IGNORECASE))

    parsed_coords = []
    points = []

    for match in matches:
        lat_deg, lat_min, lon_deg, lon_min = match.groups()

        # Extract direction characters from the raw text
        text_after_lat = raw_text[match.end(2):]
        lat_dir_char = text_after_lat[0] if text_after_lat and len(text_after_lat) > 0 else ''

        text_after_lon = raw_text[match.end(4):]
        lon_dir_char = text_after_lon[0] if text_after_lon and len(text_after_lon) > 0 else ''

        lat_dir = lat_dir_char.upper() if lat_dir_char in 'NS' else ''
        lon_dir = lon_dir_char.upper() if lon_dir_char in 'EW' else ''

        if not lat_dir or not lon_dir:
            continue

        # Strict range validation: skip invalid pairs instead of clamping
        if not _is_valid_latlon(lat_deg, lat_min, lon_deg, lon_min):
            continue

        lat = convert_to_decimal(lat_deg, lat_min, lat_dir)
        lon = convert_to_decimal(lon_deg, lon_min, lon_dir)

        if math.isnan(lat) or math.isnan(lon):
            continue

        points.append([lon, lat])
        parsed_coords.append(f"{lat_deg}-{lat_min}{lat_dir} {lon_deg}-{lon_min}{lon_dir}")

    spatial = None
    primary_lat = None
    primary_lon = None

    if points:
        if len(points) == 1:
            primary_lat = points[0][1]
            primary_lon = points[0][0]
            spatial = {"type": "Point", "coordinates": points[0]}
        else:
            # Centroid calculation for multi-point, polygon, and linestring
            primary_lat = round(sum(p[1] for p in points) / len(points), 6)
            primary_lon = round(sum(p[0] for p in points) / len(points), 6)
            archetype = classify_geometry_archetype(raw_text, points)
            if archetype == "multipoint":
                # Discrete scattered locations (e.g. 'IN VICINITY OF'
                # wellhead/platform lists, buoy lists): individual markers,
                # never a connected shape. Prevents the tangled-polygon bug.
                spatial = {"type": "MultiPoint", "coordinates": points}
            elif archetype == "bounding_box":
                # 'AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO <lon>'
                # (NAVAREA VIII 1102/26): two opposite corners define the
                # rectangle — expand into a proper closed ring rather than
                # misplotting a 2-point corridor LineString.
                lon_a, lat_a = points[0]
                lon_b, lat_b = points[1]
                spatial = {"type": "Polygon", "coordinates": [[
                    [lon_a, lat_a], [lon_b, lat_a], [lon_b, lat_b],
                    [lon_a, lat_b], [lon_a, lat_a],
                ]]}
            elif archetype == "linestring" or len(points) in (2, 3):
                # Sequential track/route/trackline: open path, never
                # auto-closed.
                spatial = {"type": "LineString", "coordinates": points}
            else:
                # Legacy default for bounded areas / unknown multi-vertex
                # arrays: closed polygon ring — but only if the ring is a
                # valid, non-self-intersecting boundary (>= 3 unique
                # vertices). A crooked/bowtie ring means the listed order
                # is not a genuine perimeter: fall back to an open path
                # instead of fabricating a filled, tangled hazard zone.
                ring = points if points[0] == points[-1] else points + [points[0]]
                unique_vertices = {tuple(p) for p in ring}
                if len(unique_vertices) >= 4 and ring_is_simple(ring):
                    spatial = {"type": "Polygon", "coordinates": [ring]}
                else:
                    spatial = {"type": "LineString", "coordinates": points}

    if not points:
        # 'AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO <lon>' lists its
        # axes separately (no pairs): fall back to axis tokens so these
        # bounded-area warnings plot as rectangles instead of nothing.
        bbox_spatial, bbox_lat, bbox_lon = _bbox_from_axis_tokens(raw_text)
        if bbox_spatial:
            return [], bbox_lat, bbox_lon, bbox_spatial

    return parsed_coords, primary_lat, primary_lon, spatial


def classify_hazard_categories(raw_text: str) -> list[str]:
    """Classifies all matching maritime hazard categories based on terminology."""
    if not raw_text or not isinstance(raw_text, str):
        return ["general"]

    text = raw_text.upper()
    categories: list[str] = []

    if any(k in text for k in ["GNSS", "DGPS", "AIS INTERFERENCE", "RADAR INTERFERENCE",
            "INTERFERENCE OBSERVED", "JAMMING", "SPOOFING"]):
        categories.append("electronic")

    military_pattern = r'\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|NAVAL EXERCISES|MILITARY EXERCISE)\b'
    if re.search(military_pattern, text):
        categories.append("military")

    if any(k in text for k in ["LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON",
            "UNLIT", "EXTINGUISHED", "OFF AIR"]):
        categories.append("aton")

    if any(k in text for k in ["SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING",
            "DREDGING", "ANCHOR", "CHAIN LOST", "SUNKEN WRECK"]):
        categories.append("subsea")

    if any(k in text for k in ["DRIFTING", "DERELICT", "MINE", "CONTAINER",
            "ADRIFT", "SPACE DEBRIS"]):
        categories.append("drifting")

    if any(k in text for k in ["RIG", "PLATFORM", "JACK-UP"]):
        categories.append("offshore")

    return categories if categories else ["general"]


def classify_hazard(raw_text: str) -> str:
    """Classifies primary maritime hazard category (first matched category)."""
    cats = classify_hazard_categories(raw_text)
    return cats[0] if cats else "general"


def compute_differential(
    scraped_warnings: List[Dict[str, Any]],
    scraped_messages: List[Dict[str, Any]],
    existing_warnings: Dict[str, Dict[str, Any]],
    existing_checksums: Set[Tuple[str, str]],
    key_fn: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Deterministically computes differential actions between scraped data and current database state.
    Supports canonical_id and custom key function.
    Returns: {'skip': [...], 'new': [...], 'update': [...], 'cancel': [...]}
    """
    scraped_warnings = scraped_warnings if scraped_warnings is not None else []
    scraped_messages = scraped_messages if scraped_messages is not None else []
    existing_warnings = existing_warnings if existing_warnings is not None else {}
    existing_checksums = existing_checksums if existing_checksums is not None else set()

    msg_map: Dict[str, Dict[str, Any]] = {}
    for m in scraped_messages:
        if isinstance(m, dict):
            if m.get("warning_id"):
                msg_map[str(m["warning_id"])] = m
            if m.get("canonical_id"):
                msg_map[str(m["canonical_id"])] = m

    to_skip = []
    to_insert_new = []
    to_update = []

    seen_ids = set()

    for warn in scraped_warnings:
        if not isinstance(warn, dict):
            continue
        if key_fn is not None:
            wid = key_fn(warn)
        else:
            wid = warn.get("canonical_id") or warn.get("warning_id")
        if not wid:
            continue
        seen_ids.add(wid)

        raw_msg = msg_map.get(wid) or msg_map.get(warn.get("warning_id", "")) or {}
        chk = raw_msg.get("checksum_sha256", "")

        existing_record = existing_warnings.get(wid)

        if existing_record:
            is_active = existing_record.get("status") == "active"
            checksum_matches = (
                (wid, chk) in existing_checksums or
                (warn.get("warning_id", ""), chk) in existing_checksums
            )

            if is_active and checksum_matches:
                to_skip.append(wid)
            else:
                to_update.append((warn, raw_msg))
        else:
            to_insert_new.append((warn, raw_msg))

    to_cancel = [
        wid for wid, record in existing_warnings.items()
        if record.get("status") == "active" and wid not in seen_ids
    ]

    return {
        "skip": to_skip,
        "new": to_insert_new,
        "update": to_update,
        "cancel": to_cancel
    }

