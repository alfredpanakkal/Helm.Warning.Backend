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

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import convert_to_decimal, parse_coordinates, classify_hazard

SOURCE_ID = "sma-baltic-subarea"
NAVAREA_ID = "Baltic"


def parse_warning(raw_block, reference_header):
    header_clean = reference_header.strip()
    area_match = re.search(r'\[(.*?)\]', header_clean)
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
        issued_text = f"{issued_text} 20{yr_match.group(1)}"
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


def main(input_filename="navareas/baltic/navarea_baltic_warnings.txt",
         output_filename="navareas/baltic/parsed_baltic_warnings.json"):
    print("=" * 60)
    print("🧭 Baltic Parser")
    print("=" * 60)
    try:
        with open(input_filename, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ Error: {input_filename} not found")
        sys.exit(1)
    pattern = r'--- (.*?) ---\n(.*?)(?=\n--- |$)'
    matches = re.findall(pattern, content, re.DOTALL)
    if not matches:
        print("❌ No warning blocks found")
        sys.exit(1)
    parsed_data = {"raw_messages": [], "nav_warnings": [], "spatial_features": []}
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
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    print(f"✅ Parsed {len(matches)} warnings into {output_filename}")
    return True


if __name__ == "__main__":
    main()
