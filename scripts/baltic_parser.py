#!/usr/bin/env python3
"""
baltic_parser.py — Deterministic Navigational Warning Parser for Baltic & Swedish Bulletins
Normalizes coordinate geometries into WGS84 decimal, infers issued years, classifies maritime hazard semantics,
and prepares structured JSON payloads for Supabase synchronization.
"""

import sys
import re
import json
import hashlib
import os
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

SOURCE_ID = "sma-baltic-subarea"
NAVAREA_ID = "Baltic"

def convert_to_decimal(degrees: str, minutes: str, direction: str) -> float:
    decimal = float(degrees) + (float(minutes) / 60.0)
    if direction.upper() in ['S', 'W']:
        decimal = -decimal
    return round(decimal, 6)

def parse_coordinates(raw_text: str):
    pattern = r'(\d{2,3})-(\d{2}(?:\.\d+)?)[N|S]\s+(\d{2,3})-(\d{2}(?:\.\d+)?)[E|W]'
    matches = list(re.finditer(pattern, raw_text))

    parsed_coords = []
    points = []

    for match in matches:
        full_match = match.group(0)
        sub = re.match(r'(\d{2,3})-(\d{2}(?:\.\d+)?)([NS])\s+(\d{2,3})-(\d{2}(?:\.\d+)?)([EW])', full_match, re.IGNORECASE)
        if sub:
            lat_deg, lat_min, lat_dir = sub.group(1), sub.group(2), sub.group(3).upper()
            lon_deg, lon_min, lon_dir = sub.group(4), sub.group(5), sub.group(6).upper()

            lat = convert_to_decimal(lat_deg, lat_min, lat_dir)
            lon = convert_to_decimal(lon_deg, lon_min, lon_dir)

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
        elif len(points) >= 4:
            primary_lat = round(sum(p[1] for p in points) / len(points), 6)
            primary_lon = round(sum(p[0] for p in points) / len(points), 6)
            closed_points = points if points[0] == points[-1] else points + [points[0]]
            spatial = {"type": "Polygon", "coordinates": [closed_points]}
        else:
            primary_lat = points[0][1]
            primary_lon = points[0][0]
            spatial = {"type": "LineString", "coordinates": points}

    return parsed_coords, primary_lat, primary_lon, spatial

def classify_hazard(raw_text: str) -> str:
    text = raw_text.upper()
    if any(k in text for k in ["GNSS", "DGPS", "AIS INTERFERENCE", "RADAR INTERFERENCE", "INTERFERENCE OBSERVED", "JAMMING", "SPOOFING"]):
        return "electronic"
    military_pattern = r'\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|NAVAL EXERCISES|MILITARY EXERCISE)\b'
    if re.search(military_pattern, text):
        return "military"
    if any(k in text for k in ["LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON", "UNLIT", "EXTINGUISHED"]):
        return "aton"
    if any(k in text for k in ["SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING", "DREDGING", "ANCHOR", "CHAIN LOST"]):
        return "subsea"
    if any(k in text for k in ["DRIFTING", "DERELICT", "MINE", "CONTAINER"]):
        return "drifting"
    if any(k in text for k in ["RIG", "PLATFORM", "JACK-UP"]):
        return "offshore"
    return "general"

def parse_warning(raw_block: str, reference_header: str):
    header_clean = reference_header.strip()
    area_match = re.search(r'\[(.*?)\]', header_clean)
    sub_areas_text = area_match.group(1) if area_match else ""
    header_no_area = re.sub(r'\s*\[.*?\]', '', header_clean).strip()

    if "BALTIC SEA NAV WARN" in header_no_area:
        num = header_no_area.split("BALTIC SEA NAV WARN")[-1].strip()
        warning_id = f"BALTIC {num}"
    elif "SWEDISH NAV WARN" in header_no_area:
        num = header_no_area.split("SWEDISH NAV WARN")[-1].strip()
        warning_id = f"SWEDISH {num}"
    else:
        warning_id = header_no_area

    lines = [line.strip() for line in raw_block.split('\n') if line.strip()]
    date_pattern = r'(\d{6}\s+UTC\s+[A-Z]{3})'
    issued_text = None
    title = ""

    for line in lines:
        d_match = re.search(date_pattern, line)
        if d_match and not issued_text:
            issued_text = d_match.group(1)
        elif not title and not d_match:
            title = line

    yr_match = re.search(r'/(\d{2})$', warning_id)
    if yr_match and issued_text and not re.search(r'\b20\d{2}\b', issued_text):
        full_year = f"20{yr_match.group(1)}"
        issued_text = f"{issued_text} {full_year}"

    coords_text, lat, lon, spatial = parse_coordinates(raw_block)
    hazard = classify_hazard(raw_block)
    checksum = hashlib.sha256(raw_block.encode('utf-8')).hexdigest()

    raw_message = {
        "warning_id": warning_id,
        "source_id": SOURCE_ID,
        "subject_header": header_clean,
        "full_raw_text": raw_block,
        "received_timestamp": datetime.now(timezone.utc).isoformat(),
        "checksum_sha256": checksum
    }

    nav_warning = {
        "warning_id": warning_id,
        "source_id": SOURCE_ID,
        "navarea": NAVAREA_ID,
        "title": title or header_no_area,
        "issued_text": issued_text,
        "coordinates": ", ".join(coords_text) if coords_text else None,
        "latitude": lat,
        "longitude": lon,
        "category": hazard,
        "status": "active",
        "raw_text": raw_block
    }

    return raw_message, nav_warning, spatial

def parse_baltic_warnings(input_filename="navarea_baltic_warnings.txt", output_filename="parsed_baltic_warnings.json"):
    if not os.path.exists(input_filename):
        print(f"❌ Input file '{input_filename}' not found.")
        return []

    with open(input_filename, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = content.split("--- ")
    parsed_warnings = []

    for block in blocks:
        if not block.strip():
            continue
        parts = block.split(" ---", 1)
        if len(parts) < 2:
            continue
        header_text = parts[0]
        body_text = parts[1].strip()

        raw_msg, nav_warn, spatial = parse_warning(body_text, header_text)
        nav_warn["spatial"] = spatial
        parsed_warnings.append({
            "raw_message": raw_msg,
            "nav_warning": nav_warn
        })

    os.makedirs(os.path.dirname(output_filename) if os.path.dirname(output_filename) else ".", exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_warnings, f, indent=2)

    print(f"✅ Successfully parsed {len(parsed_warnings)} Baltic warnings into '{output_filename}'.")
    return parsed_warnings

if __name__ == "__main__":
    parse_baltic_warnings()
