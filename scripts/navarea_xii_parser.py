#!/usr/bin/env python3
"""
navarea_xii_parser.py — Parser for NAVAREA XII (NGA Daily Memo)

Deterministic parser on top of shared/navarea_xii_text.py preprocessing:
  1. normalize_memo(): rejoin wrapped coords + DTG-header segmentation
  2. extract_geometry_clauses(): one clause per numbered item or A./B./C.
     sub-area, with trackline classification ("TRACKLINE(S) JOINING" —
     open line, not a closed area)
  3. parse_coordinates() (shared, no-second-parser rule) per clause;
     trackline clauses get their ring opened via ring_to_trackline()
  4. extract_cross_refs(): header-paren refs + body CANCEL refs

Geometry contract: a warning's clauses are emitted as a single GeoJSON
FeatureCollection; each feature carries its clause label so the sync layer
persists one nav_warning_geometries row per clause (zone_label).
"""

import sys
import os
import re
import json
import hashlib
from datetime import datetime, timezone

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.navarea_xii_text import (
    split_into_warnings,
    extract_geometry_clauses,
    extract_cross_refs,
    ring_to_trackline,
)
from shared.utils import parse_coordinates, classify_hazard_categories

SOURCE_ID = "nga-navarea-xii"
NAVAREA_ID = "XII"

RE_ITEM_LINE = re.compile(r"^\s*\d\.\s")
RE_CHART_LINE = re.compile(r"^\s*CHART\s", re.IGNORECASE)


def _extract_title(block) -> str:
    """Title = the geographic/subject lines between header and item 1.

    Falls back to the first body line for single-line warnings
    (e.g. 'CABO MARZO LIGHT ... UNLIT.'). Truncated to 255 chars.
    """
    raw_text = (block.get("raw_text") or "").strip()
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    title_lines = []
    for line in lines:
        if re.match(r"^NAVAREA\s+XII\s+\d+/\d{2}", line, re.IGNORECASE):
            continue
        if re.match(r"^\d{6}Z\s+[A-Z]{3}", line):
            continue
        if line.startswith("MSGID/") or line == "RMKS/":
            continue
        if RE_ITEM_LINE.match(line) or RE_CHART_LINE.match(line):
            break
        title_lines.append(line)
    title = " ".join(title_lines).strip()
    if not title:
        for line in lines:
            if not re.match(r"^NAVAREA\s+XII\s+\d+/\d{2}", line, re.IGNORECASE) \
                    and not re.match(r"^\d{6}Z\s+[A-Z]{3}", line) \
                    and not line.startswith("MSGID/") and line != "RMKS/":
                title = line
                break
    return title[:255]


def _build_spatial(clauses):
    """Assemble geometry from parsed clauses.

    Returns (spatial, primary_lat, primary_lon, clause_labels_with_geometry).
    Single clause with geometry: single-feature FeatureCollection.
    Multiple clauses: one Feature per clause (zone_label in properties).
    Trackline clauses (is_trackline) get Polygon rings opened into
    LineStrings — limits and survey tracks are open lines, never areas.
    """
    geoms = []  # (label, spatial, lat, lon)
    for clause in clauses:
        _, lat, lon, spatial = parse_coordinates(clause["text"])
        if spatial and clause.get("is_trackline"):
            spatial = ring_to_trackline(spatial)
        if spatial:
            geoms.append((clause["label"], spatial, lat, lon))

    if not geoms:
        return None, None, None, []

    if len(geoms) == 1:
        label, spatial, lat, lon = geoms[0]
        fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"sub_area": label, "zone_label": label or "Area"},
                "geometry": spatial,
            }],
        }
        return fc, lat, lon, [label]

    features = []
    for label, spatial, _, _ in geoms:
        features.append({
            "type": "Feature",
            "properties": {"sub_area": label, "zone_label": label},
            "geometry": spatial,
        })
    primary_lat = geoms[0][2]
    primary_lon = geoms[0][3]
    fc = {"type": "FeatureCollection", "features": features}
    return fc, primary_lat, primary_lon, [g[0] for g in geoms]


def parse_warning(block):
    """Parses one segmented memo block into (raw_message, nav_warning)."""
    warning_id = block["warning_id"]
    raw_text = block["raw_text"]
    header_line = "NAVAREA XII %s/%s" % (block["number"], block["year"])
    canonical_id = warning_id  # format: "NAVAREA XII n/yy" (navarea-prefixed already)

    checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    raw_message = {
        "warning_id": warning_id,
        "source_id": SOURCE_ID,
        "subject_header": header_line,
        "full_raw_text": raw_text,
        "received_timestamp": datetime.now(timezone.utc).isoformat(),
        "checksum_sha256": checksum,
    }

    clauses = extract_geometry_clauses(raw_text)
    spatial, lat, lon, geom_labels = _build_spatial(clauses)
    categories = classify_hazard_categories(raw_text)
    cross_refs = extract_cross_refs(block)

    nav_warning = {
        "warning_id": warning_id,
        "canonical_id": canonical_id,
        "source_id": SOURCE_ID,
        "navarea": NAVAREA_ID,
        "title": _extract_title(block) or warning_id,
        "issued_text": block.get("dtg"),
        "coordinates": None,  # master no longer carries flat coords (20261020 schema)
        "latitude": lat,
        "longitude": lon,
        "category": categories[0] if categories else "general",
        "categories": categories,
        "status": "active",
        "raw_text": raw_text,
        "spatial": spatial,
        "sub_areas": [c["label"] for c in clauses],
        "geometry_sub_areas": geom_labels,
        "cross_refs": cross_refs,
    }
    return raw_message, nav_warning


def parse_memo_text(memo_text: str) -> dict:
    """Full deterministic parse of a raw memo text into the pipeline JSON shape."""
    parsed_data = {"raw_messages": [], "nav_warnings": [], "spatial_features": [],
                   "memo": {"in_force_dtg": None}}
    if not memo_text or not memo_text.strip():
        return parsed_data

    from shared.navarea_xii_text import get_in_force_dtg
    parsed_data["memo"]["in_force_dtg"] = get_in_force_dtg(memo_text)

    for block in split_into_warnings(memo_text):
        raw_msg, nav_warn = parse_warning(block)
        parsed_data["raw_messages"].append(raw_msg)
        parsed_data["nav_warnings"].append(nav_warn)
        if nav_warn["spatial"]:
            parsed_data["spatial_features"].append({
                "warning_id": nav_warn["warning_id"],
                "category": nav_warn["category"],
                "geometry": nav_warn["spatial"],
            })
    return parsed_data


def main(input_filename="navareas/navarea_xii/navarea_xii_warnings.txt",
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
            content = ""
    else:
        print(f"ℹ️ Input file {input_filename} not found; initializing empty harvest.")

    parsed_data = parse_memo_text(content)
    n = len(parsed_data["nav_warnings"])

    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    print(f"✅ Parsed {n} warnings into {output_filename}")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
