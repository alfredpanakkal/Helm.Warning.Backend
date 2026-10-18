#!/usr/bin/env python3
"""
navarea_1_parser.py — Parser for UKHO NAVAREA I Bulletins
"""

import sys
import os
import re
import json
import hashlib
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import convert_to_decimal, parse_coordinates, classify_hazard

SOURCE_ID = "ukho-navarea-1"
NAVAREA_ID = "I"


def parse_warning(raw_block, reference_header):
    header_clean = reference_header.strip()
    warning_id = header_clean.replace("NAVAREA I ", "").strip()
    lines = [line.strip() for line in raw_block.split('\n') if line.strip()]
    date_pattern = r'(\d{6}\s+UTC\s+[A-Z]{3}\s+\d{4})'
    issued_text = None
    title = lines[0] if lines else ""
    for line in lines:
        d_match = re.search(date_pattern, line)
        if d_match and not issued_text:
            issued_text = d_match.group(1)
            if line == lines[0]:
                title = ""
        if not title and line != issued_text:
            title = line
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
        "title": title or header_clean,
        "issued_text": issued_text,
        "coordinates": ", ".join(coords_text) if coords_text else None,
        "latitude": lat,
        "longitude": lon,
        "category": hazard,
        "status": "active",
        "raw_text": raw_block
    }
    return raw_message, nav_warning, spatial


def main(input_filename="navareas/navarea_1/navarea_1_warnings.txt",
         output_filename="navareas/navarea_1/parsed_navarea_1_warnings.json"):
    print("=" * 60)
    print("🧭 NAVAREA I Parser")
    print("=" * 60)
    try:
        with open(input_filename, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ Error: {input_filename} not found")
        sys.exit(1)
    pattern = r'--- (NAVAREA I \d+/\d+) ---\n(.*?)(?=\n--- NAVAREA I|\n--- |$)'
    matches = re.findall(pattern, content, re.DOTALL)
    if not matches:
        pattern = r'--- (.*?) ---\n(.*?)(?=\n--- |$)'
        matches = re.findall(pattern, content, re.DOTALL)
        if not matches:
            print("❌ No warning blocks found")
            sys.exit(1)
    parsed_data = {"raw_messages": [], "nav_warnings": [], "spatial_features": []}
    for header, block in matches:
        if not header.strip().startswith("NAVAREA I"):
            header = f"NAVAREA I {header.strip()}"
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
