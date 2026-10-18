#!/usr/bin/env python3
"""
baltic_parser.py — Deterministic Parser for Baltic & Swedish Bulletins
"""

import sys
import re
import json
import hashlib
import os
from datetime import datetime, timezone

# Ensure root directory is on sys.path for shared imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.utils import convert_to_decimal, parse_coordinates, classify_hazard

SOURCE_ID = "sma-baltic-subarea"
NAVAREA_ID = "Baltic"

def parse_warning(raw_block: str, reference_header: str):
    """Parse a single Baltic warning block into structured data."""
    header_clean = reference_header.strip()

    # Extract warning ID and areas
    area_match = re.search(r'\[(.*?)\]', header_clean)
    sub_areas_text = area_match.group(1) if area_match else ""
    header_no_area = re.sub(r'\s*\[.*?\]', '', header_clean).strip()

    # Form standardized warning_id
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

    # Infer year from warning_id
    yr_match = re.search(r'/(\d{2})$', warning_id)
    if yr_match and issued_text and not re.search(r'\b20\d{2}\b', issued_text):
        full_year = f"20{yr_match.group(1)}"
        issued_text = f"{issued_text} {full_year}"

    # Parse coordinates
    coords_text, lat, lon, spatial = parse_coordinates(raw_block)

    # Classify hazard
    hazard = classify_hazard(raw_block)

    # Checksum
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

def main(input_path="navareas/baltic/navarea_baltic_warnings.txt",
         output_path="navareas/baltic/parsed_baltic_warnings.json"):
    """Parse Baltic warnings file and output structured JSON."""
    print("=" * 60)
    print("🧭 Baltic Navigational Warnings Parser")
    print("=" * 60)

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ Error: {input_path} not found.")
        sys.exit(1)

    # Match blocks delimited by --- HEADER [areas] ---
    pattern = r'--- (.*?) ---\n(.*?)(?=\n--- |$)'
    matches = re.findall(pattern, content, re.DOTALL)

    if not matches:
        print("❌ No warning blocks found in the input file.")
        sys.exit(1)

    parsed_data = {
        "raw_messages": [],
        "nav_warnings": [],
        "spatial_features": []
    }

    for header, block in matches:
        raw_msg, nav_warn, spatial = parse_warning(block.strip(), header.strip())
        parsed_data["raw_messages"].append(raw_msg)
        parsed_data["nav_warnings"].append(nav_warn)
        if spatial:
            parsed_data["spatial_features"].append({
                "warning_id": nav_warn["warning_id"],
                "category": nav_warn["category"],
                "geometry": spatial
            })

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Successfully parsed {len(matches)} warnings into '{output_path}'.")
    print(f"   ✔ {len(parsed_data['raw_messages'])} audit records")
    print(f"   ✔ {len(parsed_data['nav_warnings'])} active warnings")
    print(f"   ✔ {len(parsed_data['spatial_features'])} GeoJSON geometries")

if __name__ == "__main__":
    main()
