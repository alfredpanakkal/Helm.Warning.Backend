#!/usr/bin/env python3
"""
navarea_universal_parser.py — Deterministic Universal Parser for NAVAREA
regions without a dedicated parser (II, III, V, VI, VII, IX, X and the
later MET areas XIII–XXI).

Generalizes scripts/navarea_8_parser.py: the IMO WWNWS bulletin header
('NAVAREA <NUMERAL> [-]nnn/yy') is a global standard across all 21
NAVAREA / MET areas, so segmentation, clause splitting, title extraction
and cross-ref extraction are the proven NAVAREA VIII logic with only the
numeral parameterized. Coordinate parsing and hazard classification are
delegated to the shared parser (no-second-parser rule); geometry-ambiguous
warnings fail closed to Tier C / no_valid_geometry via
shared/models.build_master_payload.

Region resolution (the two-arg main(input, output) contract carries no
region parameter):
  1. The staging subdir of the input path (navareas/manual/navarea_<key>/)
     names the region.
  2. Text headers must agree: warning headers from any other NAVAREA
     region make the paste mixed-region and the parse FAILS CLOSED
     (returns False) — one paste must be exactly one region. Pastes whose
     headers belong to a dedicated-parser region (I/IV/VIII/XI/XII) are
     rejected with a pointer to the right --navarea choice.
  3. With no path hint, exactly one universal-region header must be
     present.

Cross-refs (CANCEL NAVAREA <roman> n/yy) are extracted and stored on the
warning payload for a future supersede pass; this parser applies no
status transitions.
"""
import sys
import os
import re
import json
import hashlib
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared.utils import parse_coordinates, classify_hazard_categories
from shared.navarea_universal_text import (
    UNIVERSAL_REGIONS, NAVAREA_NAMES, regions_in_text, warning_header_re, cancel_ref_re,
)

RE_ITEM_LINE = re.compile(r"(?:^|\s)(\d{1,2})\.[\s]+(?=[A-Z])")
RE_AS_ON = re.compile(
    r"WARNINGS?\s+IN\s+FORCE\s+AS\s+ON\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    re.IGNORECASE)
RE_PATH_REGION = re.compile(r"navarea[_-]([a-z0-9]+)", re.IGNORECASE)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _region_config(region_key):
    """Resolves region-dependent constants (regexes, source_id, numeral)."""
    roman = UNIVERSAL_REGIONS[region_key]
    return {
        "key": region_key,
        "roman": roman,
        "source_id": "manual-navarea-" + region_key,
        "navarea_id": roman,
        "header_re": warning_header_re(roman),
        "cancel_re": cancel_ref_re(roman),
    }


def _parse_as_on(text: str):
    m = RE_AS_ON.search(text or "")
    if not m:
        return None
    try:
        day, mon, year = m.group(1).split()
        month = MONTHS.get(mon[:3].lower())
        if not month:
            return None
        return datetime(int(year), month, int(day))
    except (ValueError, IndexError):
        return None


def _clean_line(line: str) -> str:
    """Normalizes '(.)' separators into single spaces for title extraction."""
    return re.sub(r"\(\s*\.\s*\)", " ", line).strip()


def _segment_clauses(body: str):
    """
    Splits a warning body into geometry clauses:
      - numbered items (1. 2. ...) and lettered sub-areas (A. B. ...)
      - otherwise a single clause with the full body.
    Returns a list of {label, text}.
    """
    matches = list(RE_ITEM_LINE.finditer(body))
    if not matches:
        return [{"label": "Area", "text": body}]

    clauses = []
    preamble = body[:matches[0].start()].strip()
    if preamble:
        clauses.append({"label": "Area", "text": preamble})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[m.start():end].strip()
        label = m.group(1).strip() or "Item " + str(i + 1)
        clauses.append({"label": label, "text": chunk})
    return clauses


def _extract_title(body: str, cfg) -> str:
    """Title = leading text before the first numbered item (typically the
    location / operation description)."""
    m = RE_ITEM_LINE.search(body)
    head = body[:m.start()] if m else body
    lines = [_clean_line(l) for l in head.split("\n") if l.strip()]
    title = " ".join(lines).strip()
    # Trim trailing DTG tokens the source may prepend to the next warning.
    title = re.sub(r"\b\d{6}Z?\s*/?\s*[A-Z]{3}\s+\d{2}\s*$", "", title).strip()
    return title[:255] or "NAVAREA " + cfg["roman"] + " Warning"


def _extract_cross_refs(raw_text: str, cfg):
    refs = []
    seen = set()
    for m in cfg["cancel_re"].finditer(raw_text or ""):
        key = (m.group(1), m.group(2))
        if key in seen:
            continue
        seen.add(key)
        refs.append({"number": m.group(1), "year": m.group(2)})
    return refs


def split_into_warnings(text: str, cfg):
    """
    Segments the bulletin into warning blocks on
    'NAVAREA <roman> [-]n/yy' headers.
    Returns a list of {warning_id, number, year, raw_text}.
    """
    blocks = []
    matches = list(cfg["header_re"].finditer(text or ""))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_text = text[start:end].strip()
        number, year = m.group(1), m.group(2)
        blocks.append({
            "warning_id": "NAVAREA " + cfg["roman"] + " " + number + "/" + year,
            "number": number,
            "year": year,
            "raw_text": raw_text,
        })
    return blocks


def parse_warning(block, cfg):
    """Parses one segmented bulletin block into (raw_message, nav_warning)."""
    warning_id = block["warning_id"]
    raw_text = block["raw_text"]
    canonical_id = warning_id

    checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    raw_message = {
        "warning_id": warning_id,
        "source_id": cfg["source_id"],
        "subject_header": warning_id,
        "full_raw_text": raw_text,
        "received_timestamp": datetime.utcnow().isoformat(),
        "checksum_sha256": checksum,
    }

    body = cfg["header_re"].sub("", raw_text, count=1).strip()
    clauses = _segment_clauses(body)

    geoms = []
    for clause in clauses:
        _, lat, lon, spatial = parse_coordinates(clause["text"])
        if spatial:
            geoms.append((clause["label"], spatial, lat, lon))

    if not geoms:
        spatial_fc = None
        lat = lon = None
        geom_labels = []
    elif len(geoms) == 1:
        label, spatial, lat, lon = geoms[0]
        spatial_fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"sub_area": label, "zone_label": label or "Area"},
                "geometry": spatial,
            }],
        }
        geom_labels = [label]
    else:
        features = [{
            "type": "Feature",
            "properties": {"sub_area": g[0], "zone_label": g[0]},
            "geometry": g[1],
        } for g in geoms]
        spatial_fc = {"type": "FeatureCollection", "features": features}
        lat, lon = geoms[0][2], geoms[0][3]
        geom_labels = [g[0] for g in geoms]

    categories = classify_hazard_categories(raw_text)

    nav_warning = {
        "warning_id": warning_id,
        "canonical_id": canonical_id,
        "source_id": cfg["source_id"],
        "navarea": cfg["navarea_id"],
        "title": _extract_title(body, cfg) or warning_id,
        "issued_text": None,
        "coordinates": None,  # master no longer carries flat coords (20261020 schema)
        "latitude": lat,
        "longitude": lon,
        "category": categories[0] if categories else "general",
        "categories": categories,
        "status": "active",
        "raw_text": raw_text,
        "spatial": spatial_fc,
        "sub_areas": [c["label"] for c in clauses],
        "geometry_sub_areas": geom_labels,
        "cross_refs": _extract_cross_refs(raw_text, cfg),
    }
    return raw_message, nav_warning


def parse_bulletin_text(bulletin_text: str, region_key: str) -> dict:
    """Full deterministic parse of the bulletin into pipeline JSON shape.

    memo carries region/source_id so navarea_generic_sync can key the
    differential sync without hardcoding a region.
    """
    cfg = _region_config(region_key)
    parsed_data = {"raw_messages": [], "nav_warnings": [], "spatial_features": [],
                   "memo": {"region": region_key, "navarea": cfg["navarea_id"],
                            "source_id": cfg["source_id"],
                            "in_force_as_on": None}}
    if not bulletin_text or not bulletin_text.strip():
        return parsed_data

    as_on = _parse_as_on(bulletin_text)
    parsed_data["memo"]["in_force_as_on"] = as_on.isoformat() if as_on else None

    for block in split_into_warnings(bulletin_text, cfg):
        raw_msg, nav_warn = parse_warning(block, cfg)
        parsed_data["raw_messages"].append(raw_msg)
        parsed_data["nav_warnings"].append(nav_warn)
        if nav_warn["spatial"]:
            parsed_data["spatial_features"].append({
                "warning_id": nav_warn["warning_id"],
                "category": nav_warn["category"],
                "geometry": nav_warn["spatial"],
            })
    return parsed_data


def resolve_region(input_filename, text):
    """Determines the region for this parse. Returns (region_key, error).

    Precedence: the input path's staging subdir (navarea_<key>) wins; text
    headers are used for validation (mixed-region pastes are rejected) and
    as the fallback when no path hint exists.
    """
    romans = regions_in_text(text)

    path_key = None
    if input_filename:
        parent = os.path.basename(os.path.dirname(os.path.abspath(input_filename)))
        m = RE_PATH_REGION.search(parent)
        if m:
            key = m.group(1).lower()
            if key in UNIVERSAL_REGIONS:
                path_key = key

    if path_key:
        target_roman = UNIVERSAL_REGIONS[path_key]
        foreign = {r for r in romans if r != target_roman}
        if foreign:
            return None, (
                "mixed-region paste: input path targets NAVAREA "
                + target_roman + " but the text contains warning headers for "
                + ", ".join(sorted(foreign))
                + ". Split the paste per region (one region per ingest).")
        return path_key, None

    # No path hint: resolve from the text alone.
    if not romans:
        return None, ("could not determine the NAVAREA region: no "
                      "'NAVAREA <numeral> n/yy' warning header found in the text.")
    universal_romans = {r for r in romans if r in UNIVERSAL_REGIONS.values()}
    if len(romans) > 1:
        return None, ("mixed-region paste: warning headers for "
                      + ", ".join(sorted(romans))
                      + " found. One ingest must cover exactly one region.")
    roman = next(iter(romans))
    if roman not in UNIVERSAL_REGIONS.values():
        return None, ("NAVAREA " + roman + " has a dedicated parser — ingest it "
                      "with the matching --navarea choice instead of a "
                      "universal-region ingest.")
    key = next(k for k, v in UNIVERSAL_REGIONS.items() if v == roman)
    return key, None


def main(input_filename="navareas/manual/navarea_ii/pasted_raw.txt",
         output_filename="navareas/manual/navarea_ii/parsed.json") -> bool:
    print("=" * 60)
    print("NAVAREA Universal Parser (rule-first — all non-dedicated areas)")
    print("=" * 60)
    content = ""
    if os.path.exists(input_filename):
        try:
            with open(input_filename, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print("Warning: Could not read " + input_filename + " (" + str(e) + ").")
            content = ""
    else:
        print("Input file " + input_filename + " not found; initializing empty harvest.")

    region_key, error = resolve_region(input_filename, content)
    if region_key is None:
        print("ERROR: " + str(error))
        parsed_data = {"raw_messages": [], "nav_warnings": [],
                       "spatial_features": [], "memo": {}}
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(parsed_data, f, indent=2, ensure_ascii=False)
        return False

    cfg = _region_config(region_key)
    region_name = NAVAREA_NAMES.get(region_key, "")
    print("Region: NAVAREA " + cfg["roman"]
          + " (" + region_name + ") — source_id=" + cfg["source_id"])

    parsed_data = parse_bulletin_text(content, region_key)
    n = len(parsed_data["nav_warnings"])
    n_geom = len([w for w in parsed_data["nav_warnings"] if w["spatial"]])
    print("Parsed " + str(n) + " warning(s); " + str(n_geom)
          + " with resolvable geometry (" + str(n - n_geom)
          + " fail closed to Tier C / no_valid_geometry).")

    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    print("Parsed output written to " + output_filename)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
