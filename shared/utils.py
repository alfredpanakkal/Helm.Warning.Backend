#!/usr/bin/env python3
"""
shared/utils.py — Common utilities for all NAVAREA parsers
"""

import sys
import re
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Set, Any, Optional

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

def convert_to_decimal(degrees: str, minutes: str, direction: str) -> float:
    """Converts Degrees and Decimal Minutes into Signed Decimal Degrees (WGS84)."""
    decimal = float(degrees) + (float(minutes) / 60.0)
    if direction.upper() in ['S', 'W']:
        decimal = -decimal
    return round(decimal, 6)

def parse_coordinates(raw_text: str):
    """
    Extracts navigational coordinates from text.
    Handles DD-MM.MM[N/S] DDD-MM.MM[E/W] and DD-MM-SS.SS[N/S] DDD-MM-SS.SS[E/W] formats.
    Returns: (parsed_coords_list, primary_lat, primary_lon, spatial_geojson)
    """
    # Pattern for DD-MM.MM[N/S] DDD-MM.MM[E/W]
    pattern1 = r'(\d{2,3})-(\d{2}(?:\.\d+)?)[NS]\s+(\d{2,3})-(\d{2}(?:\.\d+)?)[EW]'
    # Pattern for DD-MM-SS.SS[N/S] DDD-MM-SS.SS[E/W]
    pattern2 = r'(\d{2,3})-(\d{2})-(\d{2}(?:\.\d+)?)[NS]\s+(\d{2,3})-(\d{2})-(\d{2}(?:\.\d+)?)[EW]'

    matches = list(re.finditer(pattern1, raw_text, re.IGNORECASE)) + \
              list(re.finditer(pattern2, raw_text, re.IGNORECASE))

    parsed_coords = []
    points = []

    for match in matches:
        # Try to extract from pattern1 (DD-MM.MM)
        if len(match.groups()) == 4:
            lat_deg, lat_min, lon_deg, lon_min = match.groups()
            lat_dir = raw_text[match.end(2):match.end(2)+1] if match.end(2) < len(raw_text) else ''
            lon_dir = raw_text[match.end(4):match.end(4)+1] if match.end(4) < len(raw_text) else ''
        # Try to extract from pattern2 (DD-MM-SS.SS)
        elif len(match.groups()) == 6:
            lat_deg, lat_min, lat_sec, lon_deg, lon_min, lon_sec = match.groups()
            lat_dir = raw_text[match.end(3):match.end(3)+1] if match.end(3) < len(raw_text) else ''
            lon_dir = raw_text[match.end(6):match.end(6)+1] if match.end(6) < len(raw_text) else ''
            # Convert to decimal
            lat_min_decimal = float(lat_min) + (float(lat_sec or 0) / 60.0)
            lon_min_decimal = float(lon_min) + (float(lon_sec or 0) / 60.0)
            lat_deg, lat_min = str(lat_deg), str(lat_min_decimal)
            lon_deg, lon_min = str(lon_deg), str(lon_min_decimal)
        else:
            continue

        lat_dir = lat_dir.upper() if lat_dir else ''
        lon_dir = lon_dir.upper() if lon_dir else ''

        if not lat_dir or not lon_dir:
            continue

        lat = convert_to_decimal(lat_deg, lat_min, lat_dir)
        lon = convert_to_decimal(lon_deg, lon_min, lon_dir)

        points.append([lon, lat])  # GeoJSON format: [lon, lat]
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
            # Closed polygon for GeoJSON
            closed_points = points if points[0] == points[-1] else points + [points[0]]
            spatial = {"type": "Polygon", "coordinates": [closed_points]}
        else:
            spatial = {"type": "LineString", "coordinates": points}

    return parsed_coords, primary_lat, primary_lon, spatial

def classify_hazard(raw_text: str) -> str:
    """Classifies maritime hazard category based on terminology."""
    text = raw_text.upper()
    # 1. Electronic / GNSS interference
    if any(k in text for k in ["GNSS", "DGPS", "AIS INTERFERENCE", "RADAR INTERFERENCE",
            "INTERFERENCE OBSERVED", "JAMMING", "SPOOFING"]):
        return "electronic"
    # 2. Military / Naval operations
    military_pattern = r'\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|NAVAL EXERCISES|MILITARY EXERCISE)\b'
    if re.search(military_pattern, text):
        return "military"
    # 3. Aids to Navigation (AtoN)
    if any(k in text for k in ["LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON",
            "UNLIT", "EXTINGUISHED", "OFF AIR"]):
        return "aton"
    # 4. Subsea / Obstruction
    if any(k in text for k in ["SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING",
            "DREDGING", "ANCHOR", "CHAIN LOST", "SUNKEN WRECK"]):
        return "subsea"
    # 5. Drifting hazards
    if any(k in text for k in ["DRIFTING", "DERELICT", "MINE", "CONTAINER",
            "ADRIFT", "SPACE DEBRIS"]):
        return "drifting"
    # 6. Offshore operations
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
