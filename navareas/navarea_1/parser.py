#!/usr/bin/env python3
"""
NAVAREA I Parser
Parses navigational warnings for NAVAREA I (UK Hydrographic Office).
"""

import re
import json
from datetime import datetime, timezone

from shared.coordinates import parse_coordinates
from shared.classification import classify_hazard
from shared.utils import calculate_sha256
from shared.models import ParsedData
from navareas.navarea_1.config import (
    SOURCE_ID, NAVAREA_ID, OUTPUT_WARNINGS_FILE, OUTPUT_PARSED_FILE
)

def parse_warning(raw_block: str, reference_header: str):
    warning_id = reference_header.split("NAVAREA I ")[-1].strip()

    lines = [line.strip() for line in raw_block.split('\n') if line.strip()]
    title = lines[0] if lines else ""

    coords_text, lat, lon, spatial = parse_coordinates(raw_block)

    date_pattern = r'(\d{6}\sUTC\s[A-Z]{3}\s\d{4})'
    date_match = re.search(date_pattern, title)
    issued_text = date_match.group(1) if date_match else None

    hazard = classify_hazard(raw_block)
    checksum = calculate_sha256(raw_block)

    raw_message = {
        "warning_id": warning_id,
        "source_id": SOURCE_ID,
        "subject_header": reference_header,
        "full_raw_text": raw_block,
        "received_timestamp": datetime.now(timezone.utc).isoformat(),
        "checksum_sha256": checksum
    }

    nav_warning = {
        "warning_id": warning_id,
        "source_id": SOURCE_ID,
        "navarea": NAVAREA_ID,
        "title": title,
        "issued_text": issued_text,
        "coordinates": ", ".join(coords_text) if coords_text else None,
        "latitude": lat,
        "longitude": lon,
        "category": hazard,
        "status": "active",
        "raw_text": raw_block
    }

    return raw_message, nav_warning, spatial

def main(input_filename=OUTPUT_WARNINGS_FILE, output_filename=OUTPUT_PARSED_FILE):
    print("=" * 60)
    print("\ud83e\udded NAVAREA I Navigational Warnings Parser")
    print("=" * 60)

    try:
        with open(input_filename, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: {input_filename} not found.")
        return

    pattern = r'--- (NAVAREA I \d+/\d+) ---\n(.*?)(?=\n--- NAVAREA I|$)'
    matches = re.findall(pattern, content, re.DOTALL)

    parsed_data = ParsedData()

    for header, block in matches:
        raw_msg, nav_warn, spatial = parse_warning(block.strip(), header.strip())
        parsed_data.raw_messages.append(raw_msg)
        parsed_data.nav_warnings.append(nav_warn)
        if spatial:
            parsed_data.spatial_features.append({
                "warning_id": nav_warn["warning_id"],
                "category": nav_warn["category"],
                "geometry": spatial
            })

    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_data.to_dict(), f, indent=2, ensure_ascii=False)

    print(f"\u2705 Successfully parsed {len(matches)} warnings into '{output_filename}'.")
    print(f"   \u2022 {len(parsed_data.raw_messages)} audit records prepared")
    print(f"   \u2022 {len(parsed_data.nav_warnings)} active warnings prepared")
    print(f"   \u2022 {len(parsed_data.spatial_features)} GeoJSON geometries generated")

if __name__ == "__main__":
    main()
