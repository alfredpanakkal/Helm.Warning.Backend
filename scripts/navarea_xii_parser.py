#!/usr/bin/env python3
"""
navarea_xii_parser.py — Parser for NAVAREA XII (NGA Daily Memo)

Pipeline: rejoin wrapped coordinates → DTG-header segmentation → per-sub-area
split → geometry via shared.utils.parse_coordinates (no-second-parser rule).
Every sub-area (A./B./C.) becomes its own nav_warning record so the sync layer
can upsert on (navarea, number, year, sub_area). Cross-refs extracted from
header parens and body CANCEL lines mark referenced warnings SUPERSEDED.
"""

import sys
import os
import re
import json
import hashlib

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.navarea_xii_text import (
    split_into_warnings,
    split_sub_areas,
    extract_cross_refs,
    RE_DTG_LINE,
    RE_SUBAREA_MARKER,
    RE_ITEM_LINE,
    NAVAREA_ID,
)
from shared.utils import parse_coordinates, classify_hazard_categories

SOURCE_ID = "nga-navarea-xii"


def _extract_title(block) -> str:
    """Area/title lines: everything between the DTG/header lines and the first
    sub-area marker or numbered item, e.g. 'NORTH PACIFIC. CALIFORNIA.'"""
    lines = [l.strip() for l in block["raw_text"].split("\n") if l.strip()]
    title_parts = []
    for i, line in enumerate(lines):
        if RE_DTG_LINE.match(line):
            continue
        if re.match(r"^NAVAREA\s+XII\s+\d+/\d+", line, re.IGNORECASE):
            continue
        if RE_SUBAREA_MARKER.match(line) or RE_ITEM_LINE.match(line):
            break
        title_parts.append(line)
    return ", ".join(title_parts)


def parse_warning(block):
    """Returns (raw_message, nav_warning_records, spatial_features).

    nav_warning_records: one record per sub-area (single record with
    sub_area=None when the warning has no A./B./C. markers).
    """
    cross_refs = extract_cross_refs(block)
    categories = classify_hazard_categories(block["raw_text"])
    hazard = categories[0] if categories else "general"
    title = _extract_title(block) or block["warning_id"]
    checksum = hashlib.sha256(block["raw_text"].encode("utf-8")).hexdigest()

    raw_message = {
        "warning_id": block["warning_id"],
        "source_id": SOURCE_ID,
        "subject_header": block["warning_id"],
        "full_raw_text": block["raw_text"],
        "received_timestamp": None,  # set by caller (keeps parser deterministic)
        "checksum_sha256": checksum,
    }

    nav_warnings = []
    spatial_features = []
    for sub in split_sub_areas(block["raw_text"]):
        coords_text, lat, lon, spatial = parse_coordinates(sub["text"])
        record = {
            "warning_id": block["warning_id"],
            "canonical_id": block["warning_id"],
            "source_id": SOURCE_ID,
            "navarea": NAVAREA_ID,
            "number": block["number"],
            "year": block["year"],
            "sub_area": sub["label"],
            "title": title,
            "issued_text": block["dtg"],
            "coordinates": ", ".join(coords_text) if coords_text else None,
            "latitude": lat,
            "longitude": lon,
            "category": hazard,
            "categories": categories,
            "status": "active",
            "raw_text": block["raw_text"],
            "spatial": spatial,
            "cross_refs": cross_refs,
            "checksum_sha256": checksum,
        }
        nav_warnings.append(record)
        if spatial:
            spatial_features.append({
                "warning_id": record["warning_id"],
                "sub_area": record["sub_area"],
                "category": hazard,
                "geometry": spatial,
            })
    return raw_message, nav_warnings, spatial_features


def parse_memo(content: str) -> dict:
    """Full pipeline: normalize + segment + parse the raw memo text."""
    parsed = {"raw_messages": [], "nav_warnings": [], "spatial_features": []}
    if not content:
        return parsed
    for block in split_into_warnings(content):
        raw_msg, nav_warns, spatials = parse_warning(block)
        parsed["raw_messages"].append(raw_msg)
        parsed["nav_warnings"].extend(nav_warns)
        parsed["spatial_features"].extend(spatials)
    return parsed


def main(input_filename="navareas/navarea_xii/navarea_xii_memo.txt",
         output_filename="navareas/navarea_xii/parsed_navarea_xii_warnings.json") -> bool:
    print("=" * 60)
    print("🧭 NAVAREA XII Parser")
    print("=" * 60)
    content = ""
    if os.path.exists(input_filename):
        try:
            with open(input_filename, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️ Warning: Could not read {input_filename} ({e}).")
    else:
        print(f"ℹ️ Input file {input_filename} not found; initializing empty harvest.")

    parsed = parse_memo(content)
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)
    n_warnings = len({(w["warning_id"], w["sub_area"]) for w in parsed["nav_warnings"]})
    print(f"✅ Parsed {len(parsed['raw_messages'])} warnings "
          f"({n_warnings} sub-area records) into {output_filename}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
