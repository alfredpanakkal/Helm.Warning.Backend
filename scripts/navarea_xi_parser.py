#!/usr/bin/env python3
"""
navarea_xi_parser.py — Parser for NAVAREA XI (Japan)
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

SOURCE_ID = "kaiho-navarea-xi"
NAVAREA_ID = "XI"


def parse_warning(raw_block, reference_header):
    header_clean = reference_header.strip()
    id_match = re.search(r'NO\.(\d{2})-(\d{4})', header_clean)
    if id_match:
        warning_id = f"NAVAREA XI {id_match.group(2)}/{id_match.group(1)}"
    else:
        warning_id = header_clean.replace("NAVAREA XI ", "").strip()
    lines = [l.strip() for l in raw_block.split('\n') if l.strip()]
    date_pattern = r'Date:(\d{4}/\d{2}/\d{2}\s+\d{2}\s+UTC)'
    issued_text = None
    title = ""
    for line in lines:
        d_match = re.search(date_pattern, line, re.IGNORECASE)
        if d_match and not issued_text:
            issued_text = d_match.group(1)
        elif not title and not d_match and "NO." not in line:
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


def main(input_filename="navareas/navarea_xi/navarea_xi_warnings.txt",
         output_filename="navareas/navarea_xi/parsed_navarea_xi_warnings.json"):
    print("=" * 60)
    print("🧭 NAVAREA XI Parser")
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
