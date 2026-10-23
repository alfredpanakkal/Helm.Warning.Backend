#!/usr/bin/env python3
"""
navarea_universal_parser.py — Deterministic Universal Parser for NAVAREA
regions without a dedicated parser (II, III, V, VI, VII, IX, X and the
later MET areas XIII–XXI).

This file keeps the repo's deterministic parsing as the final authority.
A Gemini-first path is layered in front of it (shared/gemini_navarea_parser),
but the rule parser remains the fallback whenever the model is
unavailable, times out, or returns invalid data. If the Gemini layer is
absent entirely, this parser degrades to pure rule-first parsing instead
of crashing on import (PR-A hotfix for the #29 breakage).

Header quirks (live coordinator corpus, Oct 2026) are carried by
shared/navarea_universal_text.py: per-region extra header patterns
(V bare '0648/26', VI 'NAVAREA - 0355-2026', VII 'n OF yyyy',
XV 'NAVAREA XV 0142' with a bulletin year hint, XIX 'Number:n/yy'),
2- and 4-digit years (normalized to 2-digit warning ids), the XIV
'WARNING' word, and cancel-prefixed headers that must NEVER split a
block (a 'CANCEL NAVAREA II 100/26' cross-ref is part of the enclosing
warning, not a new one).

Spanish bulletins (XV Chile / XVI Peru) get titles machine-translated
via shared/translation.py — fail-closed: without a key or on any error
the original Spanish title is kept and the ingest still succeeds.

NAVAREA I companion exception: NAVAREA I (UK / North Atlantic) warnings
are routinely bundled by universal-region publishers (e.g. Norwegian
NAVAREA XIX bulletins also carry North Sea NAVAREA I items). Its headers
never make a paste mixed-region, and its blocks are truncated out during
segmentation so the regional snapshot stays pure. A paste that is ONLY
NAVAREA I still routes to the dedicated NAVAREA 1 parser.
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

try:
    from shared.gemini_navarea_parser import parse_bulletin_with_fallback
except ImportError:  # PR-A hotfix: Gemini layer not deployed — stay usable.
    parse_bulletin_with_fallback = None

from shared.utils import parse_coordinates, classify_hazard_categories
from shared.navarea_universal_text import (
    UNIVERSAL_REGIONS, NAVAREA_NAMES, regions_in_text,
    region_header_patterns, region_cancel_patterns, normalize_year, warning_header_re,
    RE_YEAR_HINT, TITLE_TRANSLATION_REGIONS,
)
from shared.translation import looks_spanish, translate_title

RE_ITEM_LINE = re.compile(r"(?:^|s)(d{1,2}).[s]+(?=[A-Z])")
RE_AS_ON = re.compile(
    r"WARNINGS?s+INs+FORCEs+ASs+ONs+(d{1,2}s+[A-Za-z]{3,9}s+d{4})",
    re.IGNORECASE)
RE_PATH_REGION = re.compile(r"navarea[_-]([a-z0-9]+)", re.IGNORECASE)
# Broadcast tail: Australia terminates each message with 'NNNN' (and the
# Russian XX with '.=' before it). These end-of-message markers must not
# leak into the last warning's raw text / title.
RE_BROADCAST_TAIL = re.compile(r"(?:
[=s]*N{3,6}[=s]*)+s*$")

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# NAVAREA I (UK / North Atlantic) is a tolerated COMPANION region: its
# warning headers never make a paste mixed-region, and its blocks are
# excluded from segmentation. Pure-NAVAREA-I pastes are still rejected by
# resolve_region (dedicated parser region).
COMPANION_ROMANS = {"I"}


def _region_config(region_key):
    """Resolves region-dependent constants (regexes, source_id, numeral)."""
    roman = UNIVERSAL_REGIONS[region_key]
    return {
        "key": region_key,
        "roman": roman,
        "source_id": "manual-navarea-" + region_key,
        "navarea_id": roman,
        "header_res": region_header_patterns(region_key, roman),
        "cancel_res": region_cancel_patterns(region_key, roman),
        "companion_re": warning_header_re("I"),  # default NAVAREA I header
        "translate_titles": region_key in TITLE_TRANSLATION_REGIONS,
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


def _parse_year_hint(text: str):
    """Bulletin-level year for regions whose headers omit it (NAVAREA XV):
    'YEAR 2026:' or 'DATE: OCT/16/2026'. None when no hint exists."""
    m = RE_YEAR_HINT.search(text or "")
    if not m:
        return None
    year = m.group(2) or m.group(3)  # 'YEAR 2026' alt / 'DATE: ...2026' alt
    return normalize_year(year)


def _clean_line(line: str) -> str:
    """Normalizes '(.)' separators into single spaces for title extraction."""
    return re.sub(r"(s*.s*)", " ", line).strip()


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
    lines = [_clean_line(l) for l in head.split("
") if l.strip()]
    title = " ".join(lines).strip()
    title = re.sub(r"d{6}Z?s*/?s*[A-Z]{3}s+d{2}s*$", "", title).strip()
    return title[:255] or "NAVAREA " + cfg["roman"] + " Warning"


def _extract_cross_refs(raw_text: str, cfg):
    refs = []
    seen = set()
    for rex in cfg["cancel_res"]:
        for m in rex.finditer(raw_text or ""):
            key = (m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            refs.append({"number": m.group(1), "year": normalize_year(m.group(2))})
    return refs


def _header_matches(text, cfg):
    """All warning-header matches for the target region, CANCEL-prefixed
    cross-references excluded: a 'CANCEL NAVAREA II 100/26' reference
    inside a warning body belongs to that warning — it must never split
    the block (previously it created a phantom warning). Overlapping
    matches from different patterns (default + region extra) collapse to
    the first."""
    found = []
    for rex in cfg["header_res"]:
        for m in rex.finditer(text or ""):
            prefix = text[max(0, m.start() - 8):m.start()].upper()
            if "CANCEL" in prefix:
                continue
            found.append(m)
    found.sort(key=lambda m: (m.start(), m.end()))
    out = []
    last_end = -1
    for m in found:
        if m.start() < last_end:
            continue  # nested inside an earlier (higher-priority) match
        out.append(m)
        last_end = m.end()
    return out


def _block_starts(text, cfg):
    """Start positions that END a warning block: the next header of the
    target region, or a tolerated companion (NAVAREA I) header — CANCEL
    cross-references excluded — so companion blocks are never absorbed
    into the tail of the last regional warning."""
    starts = [m.start() for m in _header_matches(text, cfg)]
    for m in cfg["companion_re"].finditer(text or ""):
        prefix = text[max(0, m.start() - 8):m.start()].upper()
        if "CANCEL" in prefix:
            continue
        starts.append(m.start())
    return sorted(set(starts))


def split_into_warnings(text: str, cfg):
    """
    Segments the bulletin into warning blocks on the region's header
    patterns (default + per-region extras). Returns a list of
    {warning_id, number, year, header_text, raw_text}.
    """
    blocks = []
    matches = _header_matches(text, cfg)
    starts = _block_starts(text, cfg)
    for m in matches:
        start = m.start()
        end = len(text)
        for s in starts:
            if s > start:
                end = s
                break
        raw_text = text[start:end].strip()
        raw_text = RE_BROADCAST_TAIL.sub("
", raw_text).strip()
        number, year = m.group(1), m.group(2)
        blocks.append({
            "number": number,
            "year": year,  # may be None (NAVAREA XV) — resolved by caller
            "header_text": m.group(0),
            "raw_text": raw_text,
        })
    return blocks


def parse_warning(block, cfg):
    """Parses one segmented bulletin block into (raw_message, nav_warning)."""
    number = block["number"]
    year = normalize_year(block["year"]) or block.get("year_hint")
    roman = cfg["roman"]
    warning_id = ("NAVAREA " + roman + " " + str(number)
                 + (("/" + str(year)) if year else ""))
    canonical_id = warning_id
    raw_text = block["raw_text"]

    checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    raw_message = {
        "warning_id": warning_id,
        "source_id": cfg["source_id"],
        "subject_header": warning_id,
        "full_raw_text": raw_text,
        "received_timestamp": datetime.utcnow().isoformat(),
        "checksum_sha256": checksum,
    }

    body = raw_text.replace(block["header_text"], "", 1).strip()
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

    title = _extract_title(body, cfg) or warning_id

    # Spanish bulletins (XV/XVI): fail-closed title translation. The raw
    # text stays the original Spanish; on ANY translation problem the
    # original title is kept and the ingest still succeeds.
    if cfg.get("translate_titles") and looks_spanish(title):
        translated = translate_title(title)
        if translated:
            title = translated[:255]

    nav_warning = {
        "warning_id": warning_id,
        "canonical_id": canonical_id,
        "source_id": cfg["source_id"],
        "navarea": cfg["navarea_id"],
        "title": title,
        "issued_text": None,
        "coordinates": None,
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
    """Full deterministic parse of the bulletin into pipeline JSON shape."""
    cfg = _region_config(region_key)
    parsed_data = {"raw_messages": [], "nav_warnings": [], "spatial_features": [],
                   "memo": {"region": region_key, "navarea": cfg["navarea_id"],
                            "source_id": cfg["source_id"],
                            "in_force_as_on": None}}
    if not bulletin_text or not bulletin_text.strip():
        return parsed_data

    as_on = _parse_as_on(bulletin_text)
    parsed_data["memo"]["in_force_as_on"] = as_on.isoformat() if as_on else None

    year_hint = _parse_year_hint(bulletin_text)
    for block in split_into_warnings(bulletin_text, cfg):
        block["year_hint"] = year_hint
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

    NAVAREA I is tolerated as a companion region: its headers never make a
    paste mixed-region. One NON-companion region per paste is still
    required; pure-NAVAREA-I pastes route to the dedicated parser.
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
        foreign = {r for r in romans if r != target_roman} - COMPANION_ROMANS
        if foreign:
            return None, (
                "mixed-region paste: input path targets NAVAREA "
                + target_roman + " but the text contains warning headers for "
                + ", ".join(sorted(foreign))
                + ". Split the paste per region (one region per ingest).")
        if romans & COMPANION_ROMANS:
            print("Note: tolerated companion NAVAREA I warning block(s) "
                  "excluded from this " + target_roman + " snapshot.")
        return path_key, None

    if not romans:
        return None, ("could not determine the NAVAREA region: no "
                      "'NAVAREA <numeral> n/yy' warning header found in the text.")
    candidates = romans - COMPANION_ROMANS or (romans & COMPANION_ROMANS)
    if len(candidates) > 1:
        return None, ("mixed-region paste: warning headers for "
                      + ", ".join(sorted(candidates))
                      + " found. One ingest must cover exactly one region.")
    roman = next(iter(candidates))
    if roman not in UNIVERSAL_REGIONS.values():
        return None, ("NAVAREA " + roman + " has a dedicated parser — ingest it "
                      "with the matching --navarea choice instead of a "
                      "universal-region ingest.")
    key = next(k for k, v in UNIVERSAL_REGIONS.items() if v == roman)
    return key, None


def main(input_filename="navareas/manual/navarea_ii/pasted_raw.txt",
         output_filename="navareas/manual/navarea_ii/parsed.json") -> bool:
    print("=" * 60)
    print("NAVAREA Universal Parser (rule-first — Gemini layer optional)")
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

    if parse_bulletin_with_fallback is not None:
        parsed_data = parse_bulletin_with_fallback(content, region_key, parse_bulletin_text)
    else:
        print("Gemini layer not installed — using deterministic rule parser only.")
        parsed_data = parse_bulletin_text(content, region_key)
    n = len(parsed_data["nav_warnings"])
    n_geom = len([w for w in parsed_data["nav_warnings"] if w.get("spatial")])
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
