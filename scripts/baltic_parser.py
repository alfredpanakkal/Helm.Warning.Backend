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

# Ensure repo root is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.utils import (
    convert_to_decimal, parse_block_geometries, classify_hazard,
    classify_hazard_categories,
)

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
    canonical_id = warning_id
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
    # Clause-aware parse: lettered sub-areas ('A. 12-34.5N ...') become
    # SEPARATE geometries instead of one merged shape; line-wrapped
    # coordinate tokens are rejoined; qa flags / data quality are
    # aggregated across clauses.
    geoms, coords_text, qa_flags, data_quality = parse_block_geometries(raw_block)
    if not geoms:
        spatial = None
        lat = lon = None
    elif len(geoms) == 1:
        _label, spatial, lat, lon = geoms[0]
    else:
        features = [{
            "type": "Feature",
            "properties": {"sub_area": g[0], "zone_label": g[0] or "Area"},
            "geometry": g[1],
        } for g in geoms]
        spatial = {"type": "FeatureCollection", "features": features}
        lat, lon = geoms[0][2], geoms[0][3]
    categories = classify_hazard_categories(raw_block)
    hazard = categories[0] if categories else "general"
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
        "canonical_id": canonical_id,
        "source_id": SOURCE_ID,
        "navarea": NAVAREA_ID,
        "title": title or header_no_area,
        "issued_text": issued_text,
        "coordinates": ", ".join(coords_text) if coords_text else None,
        "latitude": lat,
        "longitude": lon,
        "category": hazard,
        "categories": categories,
        "status": "active",
        "raw_text": raw_block,
        "spatial": spatial,
        "qa_flags": qa_flags,
        "data_quality": data_quality or "EXPLICIT",
    }
    return raw_message, nav_warning, spatial


def main(input_filename="navareas/baltic/navarea_baltic_warnings.txt",
         output_filename="navareas/baltic/parsed_baltic_warnings.json") -> bool:
    print("=" * 60)
    print("🧭 Baltic Parser")
    print("=" * 60)

    content = ""
    if os.path.exists(input_filename):
        try:
            with open(input_filename, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️ Warning: Could not read {input_filename} ({e}).")
            content = ""
    else:
        print(f"ℹ️ Input file {input_filename} does not exist yet; initializing empty harvest.")

    pattern = r'--- (.*?) ---\n(.*?)(?=\n--- |$)'
    matches = re.findall(pattern, content, re.DOTALL) if content else []
    parsed_data = {"raw_messages": [], "nav_warnings": [], "spatial_features": []}

    if not matches:
        # Empty harvest is a valid state; emit an empty dataset so the sync
        # stage can still cancel previously active warnings for this source.
        print("ℹ️ No warning blocks found (empty harvest is valid)")
    else:
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
    success = main()
    sys.exit(0 if success else 1)

