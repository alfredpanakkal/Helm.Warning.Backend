#!/usr/bin/env python3
"""
shared/utils.py — Common utilities for all NAVAREA parsers
"""

import sys
import re
from typing import Dict, List, Tuple, Set, Any

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
    t = raw_token.strip()

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

    return t, []


def parse_coordinate_with_provenance(raw_text: str, raw_token: str) -> Any:
    """Wraps parse_coordinates(); never fabricates hemispheres (Rule 17)."""
    from shared.models import CoordinateProvenance, DataQuality
    repaired, rules = repair_coordinate_token(raw_token)
    provenance = CoordinateProvenance(raw_token=raw_token, lat=None, lon=None)

    if not re.search(r"[NSEW]$", repaired):
        provenance.quality = DataQuality.AMBIGUOUS
        provenance.flags.append("MISSING_HEM")
        return provenance

    parsed_coords, lat, lon, spatial = parse_coordinates(repaired)
    if lat is None or lon is None:
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("VALIDATION_FAILED")
        return provenance

    provenance.lat, provenance.lon = lat, lon
    if rules:
        provenance.quality = DataQuality.INFERRED
        provenance.repairs.extend(rules)
    return provenance


def convert_to_decimal(degrees: str, minutes: str, direction: str) -> float:
    """Converts Degrees and Decimal Minutes into Signed Decimal Degrees (WGS84)."""
    decimal = float(degrees) + (float(minutes) / 60.0)
    if direction.upper() in ['S', 'W']:
        decimal = -decimal
    return round(decimal, 6)


def _is_valid_latlon(lat_deg, lat_min, lon_deg, lon_min) -> bool:
    """
    Strict coordinate value validation, mirroring validateCoordinateValues in
    src/core/coordinates.ts. Invalid coordinates are rejected, never clamped:
      - |latitude| <= 90, |longitude| <= 180
      - 0 <= minutes < 60
    """
    try:
        lat_deg = float(lat_deg)
        lat_min = float(lat_min)
        lon_deg = float(lon_deg)
        lon_min = float(lon_min)
    except (TypeError, ValueError):
        return False
    if lat_min < 0 or lat_min >= 60 or lon_min < 0 or lon_min >= 60:
        return False
    if abs(lat_deg) + lat_min / 60.0 > 90.0:
        return False
    if abs(lon_deg) + lon_min / 60.0 > 180.0:
        return False
    return True


def parse_coordinates(raw_text: str):
    """
    Extracts navigational coordinates from text.
    Handles DD-MM.MM[N/S] DDD-MM.MM[E/W] format.
    Returns: (parsed_coords_list, primary_lat, primary_lon, spatial_geojson)
    """
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

        points.append([lon, lat])
        parsed_coords.append(f"{lat_deg}-{lat_min}{lat_dir} {lon_deg}-{lon_min}{lon_dir}")

    spatial = None
    primary_lat = None
    primary_lon = None

    if points:
        primary_lat = points[0][1]
        primary_lon = points[0][0]
        if len(points) == 1:
            spatial = {"type": "Point", "coordinates": points[0]}
        elif len(points) >= 4:
            closed_points = points if points[0] == points[-1] else points + [points[0]]
            spatial = {"type": "Polygon", "coordinates": [closed_points]}
        else:
            spatial = {"type": "LineString", "coordinates": points}

    return parsed_coords, primary_lat, primary_lon, spatial


def classify_hazard(raw_text: str) -> str:
    """Classifies maritime hazard category based on terminology."""
    text = raw_text.upper()
    if any(k in text for k in ["GNSS", "DGPS", "AIS INTERFERENCE", "RADAR INTERFERENCE",
            "INTERFERENCE OBSERVED", "JAMMING", "SPOOFING"]):
        return "electronic"
    military_pattern = r'\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|NAVAL EXERCISES|MILITARY EXERCISE)\b'
    if re.search(military_pattern, text):
        return "military"
    if any(k in text for k in ["LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON",
            "UNLIT", "EXTINGUISHED", "OFF AIR"]):
        return "aton"
    if any(k in text for k in ["SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING",
            "DREDGING", "ANCHOR", "CHAIN LOST", "SUNKEN WRECK"]):
        return "subsea"
    if any(k in text for k in ["DRIFTING", "DERELICT", "MINE", "CONTAINER",
            "ADRIFT", "SPACE DEBRIS"]):
        return "drifting"
    if any(k in text for k in ["RIG", "PLATFORM", "JACK-UP"]):
        return "offshore"
    return "general"


def compute_differential(
    scraped_warnings: List[Dict[str, Any]],
    scraped_messages: List[Dict[str, Any]],
    existing_warnings: Dict[str, Dict[str, Any]],
    existing_checksums: Set[Tuple[str, str]]
) -> Dict[str, Any]:
    """
    Deterministically computes differential actions between scraped data and current database state.
    Returns: {'skip': [...], 'new': [...], 'update': [...], 'cancel': [...]}
    """
    msg_map = {m["warning_id"]: m for m in scraped_messages}

    to_skip = []
    to_insert_new = []
    to_update = []

    seen_ids = set()

    for warn in scraped_warnings:
        wid = warn["warning_id"]
        seen_ids.add(wid)
        raw_msg = msg_map.get(wid, {})
        chk = raw_msg.get("checksum_sha256", "")

        existing_record = existing_warnings.get(wid)

        if existing_record:
            is_active = existing_record.get("status") == "active"
            checksum_matches = (wid, chk) in existing_checksums

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
