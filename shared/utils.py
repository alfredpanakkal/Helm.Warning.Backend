#!/usr/bin/env python3
"""
shared/utils.py — Common utilities for all NAVAREA parsers
Includes hardened input validation, coordinate repairs, centroid computation, and error context.
"""

import sys
import re
import math
from typing import Dict, List, Tuple, Set, Any, Optional

from shared.exceptions import ParseError, ValidationError
from shared.geometry_classifier import (
    classify_geometry_archetype, classify_geometry_archetype_detailed,
    ring_is_simple,
)
from shared.validation import (
    validate_coordinate_token,
    validate_warning_id,
    validate_raw_text,
    validate_lat_lon,
    validate_public_inputs,
)

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Rule 18 (Peru decimal-hyphen): 11-49-992S -> 11-49.992S
RE_RULE_18 = re.compile(r"^(\d{1,2})-(\d{2})-(\d{3,})([NSEW])$")
# Rule 19 (double-period): 049.01.55E -> 049-01.55E
RE_RULE_19 = re.compile(r"^(\d{2,3})\.(\d{2})\.(\d{2})([NSEW])$")
# Rule 20 (degree padding): 021-26.90N -> 21-26.90N ; 42-08.00E -> 042-08.00E
RE_RULE_20_LAT = re.compile(r"^0(\d{2})-(\d{2}(?:\.\d+)?)([NS])$")
RE_RULE_20_LON = re.compile(r"^(\d{2})-(\d{2}(?:\.\d+)?)([EW])$")
# Rule 93 (European decimal comma): 44-05,12N -> 44-05.12N
RE_RULE_93 = re.compile(r"^(\d{1,3})-(\d{2}),(\d+)([NSEW])$")


# --- line-wrap rejoining (canonical shared implementation) ------------------
#
# Coordinate tokens split across line wraps ("16-" at the end of one
# line, "40.27N" starting the next — the NAVAREA VIII 1087/26 shape)
# previously produced 4-of-6 positions and a truncated polygon. This
# canonical copy lives in shared/utils so parse_coordinates()
# can rejoin EVERY input before extraction (NgaMemoPreprocessor keeps its
# identical method for the IV/XII memo path; dedup is a deliberate
# follow-up, not part of this correctness fix).

_REJOIN_TOKEN = re.compile(r"^(\d{1,3})-(\d{1,2}(?:\.\d{1,4})?)([NSEW])$")

# Line wrap INSIDE a coordinate token: optional CR then LF. Kept as a
# named constant so every raw-string pattern below stays a single
# physical line (a raw string can never span a real newline).
_WRAP = r"\r?\n"

# Each spec is (compiled_pattern, merge_fn) — a merge only applies when
# the merged fragment forms a valid coordinate token.
_REJOIN_WRAP_SPECS = (
    # "34-27." + wrap + "00N" (XII 148/26); "58-10." + wrap + "50N" (IV 1170/25)
    (re.compile(r"(\d{1,3}-\d{1,2}(?:\.\d{0,4})?)" + _WRAP
               + r"(\d{1,2}(?:\.\d{1,4})?)([NSEW])"),
     lambda g: g[0] + g[1] + g[2]),
    # "57" + wrap + "-00N" (IV 206/26) — degrees at line end, minutes next line
    (re.compile(r"(\d{1,3})" + _WRAP
               + r"(-\d{1,2}(?:\.\d{1,4})?)([NSEW])"),
     lambda g: g[0] + g[1] + g[2]),
    # "27-09" + wrap + ".1N" (IV 204/26) — wrap inside the decimal minutes
    (re.compile(r"(\d{1,3}-\d{1,2}(?:\.\d{1,4})?)" + _WRAP
               + r"(\.\d{1,4})([NSEW])"),
     lambda g: g[0] + g[1] + g[2]),
    # "12-" + wrap + "28.85N" (IV 466/25) — degrees-hyphen at line end; the hyphen is
    # consumed by the pattern and must be re-inserted
    (re.compile(r"(\d{1,3})-" + _WRAP
               + r"(\d{1,2}(?:\.\d{1,4})?)([NSEW])"),
     lambda g: g[0] + "-" + g[1] + g[2]),
)


def _rejoin_token_valid(token: str) -> bool:
    m = _REJOIN_TOKEN.match(token)
    if not m:
        return False
    deg = int(m.group(1))
    minutes = float(m.group(2))
    if minutes >= 60.0:
        return False
    if m.group(3) in ("N", "S"):
        return deg <= 90
    return deg <= 180


def rejoin_wrapped_coords(text: str) -> str:
    """Join DDM coordinate tokens split across line wraps (idempotent).

    Only merges when the merged fragment forms a valid coordinate token;
    prose word-wraps ("IN AREA BO
UND BY") are left untouched.
    """
    if not text:
        return text

    previous = None
    while previous != text:
        previous = text
        for pattern, merge in _REJOIN_WRAP_SPECS:
            def _merge(m, merge=merge):
                merged = merge(m.groups())
                if _rejoin_token_valid(merged):
                    return merged
                return m.group(0)
            text = pattern.sub(_merge, text)
    return text



def repair_coordinate_token(raw_token: str) -> tuple[str, list[str]]:
    """Returns (repaired_token, applied_rules). Unchanged token -> (raw_token, [])."""
    if raw_token is None:
        return "", []
    t = str(raw_token).strip()
    if not t:
        return "", []

    applied_rules: list[str] = []

    m = RE_RULE_18.match(t)
    if m:
        deg, mins, secs, hem = m.groups()
        minutes = float(f"{mins}.{secs}") if int(secs) >= 100 or len(secs) > 2 else None
        if minutes is not None:
            if minutes >= 60:
                deg = str(int(deg) + int(minutes // 60))
                minutes = minutes % 60
            deg_int = int(deg)
            deg_str = f"{deg_int:02d}" if deg_int < 100 else f"{deg_int}"
            return f"{deg_str}-{minutes:06.3f}".rstrip('0').rstrip('.') + hem, ["rule18"]

    m = RE_RULE_19.match(t)
    if m:
        deg, mins, secs, hem = m.groups()
        return f"{deg}-{mins}.{secs}{hem}", ["rule19"]

    m = RE_RULE_20_LAT.match(t)
    if m:
        deg, mins, hem = m.groups()
        return f"{int(deg)}-{mins}{hem}", ["rule20"]

    m = RE_RULE_20_LON.match(t)
    if m:
        deg, mins, hem = m.groups()
        return f"{deg.zfill(3)}-{mins}{hem}", ["rule20"]

    m = RE_RULE_93.match(t)
    if m:
        deg, mins, frac, hem = m.groups()
        return f"{deg}-{mins}.{frac}{hem}", ["rule93"]

    return t, applied_rules


def parse_coordinate_with_provenance(raw_text: str, raw_token: str) -> Any:
    """Wraps parse_coordinates(); never fabricates hemispheres (Rule 17)."""
    from shared.models import CoordinateProvenance, DataQuality

    if not raw_token or not isinstance(raw_token, str) or not raw_token.strip():
        provenance = CoordinateProvenance(raw_token=str(raw_token or ""), lat=None, lon=None)
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("EMPTY_TOKEN")
        return provenance

    try:
        token_clean = validate_coordinate_token(raw_token)
    except ValidationError:
        provenance = CoordinateProvenance(raw_token=str(raw_token), lat=None, lon=None)
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("VALIDATION_FAILED")
        return provenance
    repaired, rules = repair_coordinate_token(token_clean)
    provenance = CoordinateProvenance(raw_token=raw_token, lat=None, lon=None)

    if not re.search(r"[NSEW]$", repaired, re.IGNORECASE):
        provenance.quality = DataQuality.AMBIGUOUS
        provenance.flags.append("MISSING_HEM")
        return provenance

    # Check if the token itself is a full pair
    parsed_coords, lat, lon, spatial = parse_coordinates(repaired)

    # If the token was a single axis (e.g. lat only), extract coordinate pair from raw_text
    if (lat is None or lon is None) and raw_text:
        # Check text with repaired token substituted
        search_text = raw_text.replace(raw_token, repaired)
        parsed_coords, lat, lon, spatial = parse_coordinates(search_text)

    if lat is None or lon is None:
        provenance.quality = DataQuality.INVALID
        provenance.flags.append("VALIDATION_FAILED")
        return provenance

    provenance.lat, provenance.lon = lat, lon
    if rules:
        provenance.quality = DataQuality.INFERRED
        provenance.repairs.extend(rules)
    else:
        provenance.quality = DataQuality.EXPLICIT

    return provenance


def convert_to_decimal(
    degrees: Any,
    minutes: Any,
    direction_or_seconds: Any = None,
    direction: Optional[str] = None
) -> float:
    """
    Converts Degrees and Decimal Minutes (or Seconds) into Signed Decimal Degrees (WGS84).
    Supports 3-arg (deg, min, dir) and 4-arg (deg, min, sec, dir).
    Returns math.nan on out-of-bounds or invalid inputs (never clamps).
    """
    try:
        deg_f = float(degrees)
        min_f = float(minutes)
    except (TypeError, ValueError):
        return float('nan')

    # Resolve arguments
    if direction is None:
        # 3-arg signature: convert_to_decimal(deg, min, dir)
        dir_str = str(direction_or_seconds or '').strip().upper()
        sec_f = 0.0
    else:
        # 4-arg signature: convert_to_decimal(deg, min, sec, dir)
        dir_str = str(direction or '').strip().upper()
        try:
            sec_f = float(direction_or_seconds) if direction_or_seconds is not None else 0.0
        except (TypeError, ValueError):
            return float('nan')

    # Boundary checks: degrees must be non-negative, minutes and seconds in [0, 60)
    if deg_f < 0.0 or min_f < 0.0 or min_f >= 60.0 or sec_f < 0.0 or sec_f >= 60.0:
        return float('nan')

    total_degrees = deg_f + (min_f / 60.0) + (sec_f / 3600.0)

    # Direction specific bounds
    if dir_str in ('N', 'S'):
        if total_degrees > 90.0:
            return float('nan')
        if dir_str == 'S':
            total_degrees = -total_degrees
    elif dir_str in ('E', 'W'):
        if total_degrees > 180.0:
            return float('nan')
        if dir_str == 'W':
            total_degrees = -total_degrees
    else:
        # Unknown or missing direction
        return float('nan')

    return round(total_degrees, 6)


def _is_valid_latlon(lat_deg: Any, lat_min: Any, lon_deg: Any, lon_min: Any) -> bool:
    """
    Strict coordinate value validation:
      - |latitude| <= 90, |longitude| <= 180
      - 0 <= minutes < 60
    """
    try:
        lat_d = float(lat_deg)
        lat_m = float(lat_min)
        lon_d = float(lon_deg)
        lon_m = float(lon_min)
    except (TypeError, ValueError):
        return False
    if lat_m < 0 or lat_m >= 60 or lon_m < 0 or lon_m >= 60:
        return False
    if abs(lat_d) + lat_m / 60.0 > 90.0:
        return False
    if abs(lon_d) + lon_m / 60.0 > 180.0:
        return False
    return True


# Standalone axis tokens for 'AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO
# <lon>' bulletins (NAVAREA VIII 1102/26): latitudes and longitudes are
# listed SEPARATELY, so the pair-based pattern extracts nothing.
RE_AXIS_LAT = re.compile(r"(?<![\d.])(\d{1,2})-(\d{2}(?:\.\d+)?)([NS])(?![\d.])")
RE_AXIS_LON = re.compile(r"(?<![\d.])(\d{1,3})-(\d{2}(?:\.\d+)?)([EW])(?![\d.])")


def _bbox_from_axis_tokens(raw_text: str):
    """
    Builds a closed rectangle ring for 'AREA BOUNDED WITHIN' bulletins
    whose latitudes and longitudes are listed as separate axis ranges
    (e.g. 14-47.2N TO 14-50.9N AND 074-02.8E TO 074-08.15E).
    Returns (spatial, centroid_lat, centroid_lon) or (None, None, None).
    Gated on the bbox phrase so unrelated lat/lon mentions never
    fabricate an area (fail-closed outside the known format).
    """
    from shared.geometry_classifier import RE_BBOX

    if not raw_text or not RE_BBOX.search(raw_text.upper()):
        return None, None, None

    lats = set()
    for m in RE_AXIS_LAT.finditer(raw_text):
        deg, mins, hem = m.groups()
        if _is_valid_latlon(deg, mins, "0", "0"):
            val = convert_to_decimal(deg, mins, hem)
            if not math.isnan(val):
                lats.add(val)
    lons = set()
    for m in RE_AXIS_LON.finditer(raw_text):
        deg, mins, hem = m.groups()
        if _is_valid_latlon("0", "0", deg, mins):
            val = convert_to_decimal(deg, mins, hem)
            if not math.isnan(val):
                lons.add(val)

    if len(lats) != 2 or len(lons) != 2:
        return None, None, None  # not a clean two-corner range: fail closed

    lat_s, lat_n = sorted(lats)
    lon_w, lon_e = sorted(lons)
    ring = [
        [lon_w, lat_s], [lon_e, lat_s], [lon_e, lat_n], [lon_w, lat_n], [lon_w, lat_s],
    ]
    spatial = {"type": "Polygon", "coordinates": [ring]}
    return spatial, round((lat_s + lat_n) / 2, 6), round((lon_w + lon_e) / 2, 6)


# --- Coordinate PAIR extraction (multi-format, priority-ordered) ------------
#
# The live coordinator corpus (Oct 2026) uses four pair syntaxes. Patterns
# are applied in priority order and matched spans are consumed, so a
# coordinate is never extracted twice or misread by a looser pattern:
#
#   1. Peru fractional-hyphen pair (rule-18 semantics, XVI):
#        '11-49-992S 077-28-025W'  ->  3-digit tail = thousandths of a minute
#   2. DMS hyphen pair (XIII '51-27-57N 143-26-43E',
#      XVI '12-01-53.4S 077-10-29.1W' with decimal seconds)
#   3. Standard hyphen DMM pair — now with tolerant lat/lon separation
#      (whitespace, ',', '/', or Chile's 'LAT. 52-20.10S. LONG. 069-04.60W.'
#      wording, Australia's '14-45.98S /159-08.93E', glued 'NN-NN.NNE' tails)
#   4. Spaced-hyphen pair with separated hemispheres (South Africa VII:
#      '28 - 35.8 S 013 - 54.7 E')
#   5. Space/tab-separated DMM pair (Canada XVIII '68 27.660N 113 23.366W',
#      Pakistan IX '24 43.00N 066 50.40E')
#
# Every pattern requires an explicit hemisphere letter: no hemisphere is
# ever fabricated (Rule 17), and out-of-range values are skipped rather
# than clamped.

# Lat/lon separation inside a pair: whitespace, comma, slash, a trailing
# '.' after the latitude, the Chilean 'LONG.'/'LON.' wording, and the
# 'N - E' dash separator (NAVAREA III 0122/26 '18-00N - 071-00E').
_PAIR_SEP = r"[\s,/]*(?:\.\s*)?(?:LONG\.?\s*|LON\.?\s*)?[\s,/]*(?:-[\s,/]*)?"

RE_PAIR_PERU = re.compile(
    r"(\d{1,2})-(\d{2})-(\d{3})([NS])" + _PAIR_SEP +
    r"(\d{1,3})-(\d{2})-(\d{3})([EW])",
    re.IGNORECASE,
)
RE_PAIR_DMS = re.compile(
    r"(\d{1,2})-(\d{2})-(\d{1,2}(?:[.,]\d+)?)\s*([NS])" + _PAIR_SEP +
    r"(\d{1,3})-(\d{2})-(\d{1,2}(?:[.,]\d+)?)\s*([EW])",
    re.IGNORECASE,
)
# European decimal-comma minutes (III 0086/26 '44-05,12N 013-45,27E')
# and single-digit minutes (SWEDISH 175/26 '018-4.7E') share this
# pattern: ',' is normalized to '.' at extraction.
RE_PAIR_DMM = re.compile(
    r"(\d{1,2})-(\d{1,2}(?:[.,]\d+)?)\s*([NS])" + _PAIR_SEP +
    r"(\d{1,3})-(\d{1,2}(?:[.,]\d+)?)\s*([EW])",
    re.IGNORECASE,
)
RE_PAIR_DMM_SPACED = re.compile(
    r"(\d{1,3})\s*-\s*(\d{1,2}(?:[.,]\d+)?)\s+([NS])\s+"
    r"(\d{1,3})\s*-\s*(\d{1,2}(?:[.,]\d+)?)\s+([EW])",
    re.IGNORECASE,
)
# Space-separated DMS with seconds (IX 118/26 '25 02 37.67N 054 59 18.27E'):
# must be tried BEFORE RE_PAIR_SPACE, or the space-DMM pattern misreads
# '25 02 37.67N' as deg 25 / min 02 and the seconds as the next latitude.
RE_PAIR_SPACE_DMS = re.compile(
    r"(\d{1,2})[ \t]+(\d{2})[ \t]+(\d{1,2}(?:[.,]\d+)?)\s*([NS])[\s,]+"
    r"(\d{1,3})[ \t]+(\d{2})[ \t]+(\d{1,2}(?:[.,]\d+)?)\s*([EW])",
    re.IGNORECASE,
)
RE_PAIR_SPACE = re.compile(
    r"(\d{1,2})[ \t]+(\d{1,2}(?:[.,]\d+)?)\s*([NS])[\s,]+"
    r"(\d{1,3})[ \t]+(\d{1,2}(?:[.,]\d+)?)\s*([EW])",
    re.IGNORECASE,
)

# Last-pass mixed-syntax pairing (IX 489/22 '23 59.10N, 038-01.70E'):
# lat and lon written in DIFFERENT syntaxes (one space-separated, one
# hyphen-separated) that no uniform pair pattern matches together. Only
# spans the higher-priority patterns left unconsumed are claimed, and
# the gap between lat and lon may hold nothing but whitespace/comma/
# dash — a word ('TO', 'AND', 'LONG.') rejects the pairing.
RE_TOKEN_LAT = re.compile(
    r"(\d{1,2})(?:[ \t]+|-\s*)(\d{1,2}(?:[.,]\d+)?)\s*([NS])", re.IGNORECASE)
RE_TOKEN_LON = re.compile(
    r"(\d{1,3})(?:[ \t]+|-\s*)(\d{1,2}(?:[.,]\d+)?)\s*([EW])", re.IGNORECASE)
_ADJACENT_GAP = re.compile(r"^[\s,;.\-]{0,12}$")


# Hemisphere-bearing coordinate-looking token (loose completeness count and
# rejected-token scan). One token per hemisphere letter attached to digits:
# every extracted pair accounts for exactly two.
RE_LOOSE_HEM_TOKEN = re.compile(r"\d[\d.,-]*\s*[NSEW]\b")
# Decimal-minute value with NO hemisphere letter ('18-30.5 ' from a partial
# or wrapped position): missing_hemisphere — never guessed (Rule 17).
RE_MISSING_HEM_TOKEN = re.compile(
    r"(?<![A-Za-z0-9.-])(\d{1,3}-\d{1,2}\.\d{1,4})(?!\s*[NSEW])(?=[\s,;]|$)"
)


def _extract_coord_pairs(raw_text: str):
    """Extracts validated coordinate pairs from text in ALL supported
    syntaxes. Returns a position-ordered list of
    (kind, lat, lon, canonical_str); out-of-range pairs are skipped
    (never clamped), and no pair is ever extracted twice."""
    consumed: list[tuple[int, int]] = []
    found = []

    for rex, kind in (
        (RE_PAIR_PERU, "peru"),
        (RE_PAIR_DMS, "dms"),
        (RE_PAIR_DMM, "dmm"),
        (RE_PAIR_DMM_SPACED, "dmm_spaced"),
        (RE_PAIR_SPACE_DMS, "dms_space"),
        (RE_PAIR_SPACE, "dmm_space"),
    ):
        for m in rex.finditer(raw_text):
            s, e = m.span()
            if any(s >= a and s < b for a, b in consumed):
                continue  # already claimed by a higher-priority pattern
            g = m.groups()
            if kind == "peru":
                lat_d, lat_m, lat_tail, lat_h, lon_d, lon_m, lon_tail, lon_h = g
                lat_min = float(f"{lat_m}.{lat_tail}")
                lon_min = float(f"{lon_m}.{lon_tail}")
                if lat_min >= 60.0 or lon_min >= 60.0:
                    continue
                if not _is_valid_latlon(lat_d, lat_min, lon_d, lon_min):
                    continue
                lat = convert_to_decimal(lat_d, lat_min, lat_h)
                lon = convert_to_decimal(lon_d, lon_min, lon_h)
                canon = (f"{lat_d}-{lat_min:06.3f}".rstrip('0').rstrip('.') + lat_h
                         + " " + f"{lon_d.zfill(3)}-{lon_min:06.3f}".rstrip('0').rstrip('.') + lon_h)
            elif kind in ("dms", "dms_space"):
                lat_d, lat_m, lat_s, lat_h, lon_d, lon_m, lon_s, lon_h = g
                lat_s = lat_s.replace(",", ".")
                lon_s = lon_s.replace(",", ".")
                if not _is_valid_latlon(lat_d, lat_m, lon_d, lon_m):
                    continue
                lat = convert_to_decimal(lat_d, lat_m, lat_s, lat_h)
                lon = convert_to_decimal(lon_d, lon_m, lon_s, lon_h)
                canon = (f"{lat_d}-{lat_m}-{lat_s}{lat_h} "
                         f"{lon_d}-{lon_m}-{lon_s}{lon_h}")
            else:
                lat_d, lat_m, lat_h, lon_d, lon_m, lon_h = g
                lat_m = lat_m.replace(",", ".")
                lon_m = lon_m.replace(",", ".")
                if not _is_valid_latlon(lat_d, lat_m, lon_d, lon_m):
                    continue
                lat = convert_to_decimal(lat_d, lat_m, lat_h)
                lon = convert_to_decimal(lon_d, lon_m, lon_h)
                canon = f"{lat_d}-{lat_m}{lat_h} {lon_d}-{lon_m}{lon_h}"

            if lat is None or lon is None or math.isnan(lat) or math.isnan(lon):
                continue
            consumed.append((s, e))
            found.append((m.start(), kind, lat, lon, canon))

    # Last pass (mixed syntaxes): adjacent lat/lon tokens written in
    # different syntaxes the uniform patterns cannot pair together.
    # Claims only unconsumed spans, so nothing already extracted is
    # ever re-claimed or misread.
    def _unclaimed(start, end):
        return not any(start >= a and start < b for a, b in consumed)

    lat_tokens = [
        (m.start(), m.end(), m) for m in RE_TOKEN_LAT.finditer(raw_text)
        if _unclaimed(m.start(), m.end())
    ]
    lon_tokens = [
        (m.start(), m.end(), m) for m in RE_TOKEN_LON.finditer(raw_text)
        if _unclaimed(m.start(), m.end())
    ]
    claimed_lons = set()
    for lat_start, lat_end, lm in lat_tokens:
        for lon_start, lon_end, om in lon_tokens:
            if lon_start < lat_end or lon_start in claimed_lons:
                continue
            if not _ADJACENT_GAP.match(raw_text[lat_end:lon_start]):
                break
            lat_d, lat_m, lat_h = lm.groups()
            lon_d, lon_m, lon_h = om.groups()
            lat_m = lat_m.replace(",", ".")
            lon_m = lon_m.replace(",", ".")
            if not _is_valid_latlon(lat_d, lat_m, lon_d, lon_m):
                break
            lat = convert_to_decimal(lat_d, lat_m, lat_h)
            lon = convert_to_decimal(lon_d, lon_m, lon_h)
            if lat is None or lon is None or math.isnan(lat) or math.isnan(lon):
                break
            canon = f"{lat_d}-{lat_m}{lat_h} {lon_d}-{lon_m}{lon_h}"
            consumed.append((lat_start, lon_end))
            claimed_lons.add(lon_start)
            found.append((lat_start, "dmm_mixed", lat, lon, canon))
            break

    found.sort(key=lambda item: item[0])
    return [(kind, lat, lon, canon) for _s, kind, lat, lon, canon in found]


def _classify_loose_token(token: str):
    """Failure reason for a hemisphere-bearing token the pair patterns
    refused, or None when the token is well-formed (an unpaired axis
    value inside a 'BOUNDED WITHIN' range listing is not an error)."""
    t = token.strip()
    m = re.match(r"^(\d{1,3})-(\d{1,2}(?:[.,]\d+)?)\s*([NSEW])$", t)
    if not m:
        return None
    deg_s, min_s, hem = m.groups()
    try:
        deg_f = float(deg_s)
        min_f = float(min_s.replace(",", "."))
    except ValueError:
        return "validation_failed"
    if min_f >= 60.0:
        return "validation_failed"
    limit = 90.0 if hem in ("N", "S") else 180.0
    if deg_f + min_f / 60.0 > limit:
        return "validation_failed"
    return None


def _scan_rejected_tokens(text: str) -> list:
    """Rejected coordinate tokens with reasons (silent-discard fix):
    out-of-range hemisphere-bearing values ('91-00.0N' ->
    validation_failed) and decimal-minute values missing their hemisphere
    letter ('18-30.5 ' -> missing_hemisphere). Well-formed unpaired
    tokens (axis listings) are NOT errors and are skipped."""
    rejected = []
    for m in RE_LOOSE_HEM_TOKEN.finditer(text):
        reason = _classify_loose_token(m.group(0))
        if reason:
            rejected.append({"token": m.group(0).strip(), "reason": reason})
    for m in RE_MISSING_HEM_TOKEN.finditer(text):
        rejected.append({"token": m.group(1), "reason": "missing_hemisphere"})
    return rejected


def parse_coordinates_detailed(raw_text: str, context_text: Optional[str] = None):
    """
    parse_coordinates() with a structured parse report (geometry basis +
    accepted/rejected tokens). Line-wrapped coordinate tokens are
    rejoined before extraction. Returns
    (parsed_coords_list, primary_lat, primary_lon, spatial_geojson, report):

      report["flags"]        qa_flags entries for the record:
                             COORD_COUNT_MISMATCH (loose coordinate-looking
                             tokens exceed the extracted pairs — never
                             build a polygon from the remainder),
                             AMBIGUOUS_FALLBACK (geometry came from a
                             fallback, not the source wording),
                             RIG_AREA_CONFLICT (rig keyword + boundary
                             phrase with few positions), MISSING_HEM,
                             VALIDATION_FAILED
      report["basis"]        how the geometry was decided, e.g.
                             "keyword:area_bounded" / "heuristic:sequential"
                             / "fallback:legacy_polygon"
      report["data_quality"] EXPLICIT (keyword-explicit), INFERRED
                             (heuristic), AMBIGUOUS (fallback); None when
                             no geometry was built
      report["accepted"]     [{"canonical", "kind"}] extracted pairs
      report["rejected"]     [{"token", "reason"}] refused tokens
    """
    if not raw_text or not isinstance(raw_text, str):
        return [], None, None, None, {
            "flags": [], "basis": None, "data_quality": None,
            "accepted": [], "rejected": [],
        }

    text = rejoin_wrapped_coords(raw_text)
    pairs = _extract_coord_pairs(text)

    parsed_coords = []
    points = []
    for _kind, lat, lon, canon in pairs:
        points.append([lon, lat])
        parsed_coords.append(canon)

    accepted = [
        {"canonical": canon, "kind": kind} for kind, _lat, _lon, canon in pairs
    ]
    rejected = _scan_rejected_tokens(text)

    flags = []
    for r in rejected:
        if r["reason"] == "validation_failed" and "VALIDATION_FAILED" not in flags:
            flags.append("VALIDATION_FAILED")
        elif r["reason"] == "missing_hemisphere" and "MISSING_HEM" not in flags:
            flags.append("MISSING_HEM")

    spatial = None
    primary_lat = None
    primary_lon = None
    basis = None
    quality = None

    if points:
        # Completeness check: a loose count of hemisphere-bearing
        # coordinate-looking tokens above the extracted pairs means the
        # text holds positions the patterns refused — never close them
        # into a polygon.
        loose_count = len(RE_LOOSE_HEM_TOKEN.findall(text))
        count_mismatch = loose_count > 2 * len(points)
        if count_mismatch:
            flags.append("COORD_COUNT_MISMATCH")

        if len(points) == 1:
            primary_lat = points[0][1]
            primary_lon = points[0][0]
            spatial = {"type": "Point", "coordinates": points[0]}
            basis = "explicit:single_position"
        else:
            # Centroid calculation for multi-point, polygon, and linestring
            primary_lat = round(sum(p[1] for p in points) / len(points), 6)
            primary_lon = round(sum(p[0] for p in points) / len(points), 6)
            archetype, basis, cls_flags = classify_geometry_archetype_detailed(
                text, points, context_text)
            for f in cls_flags:
                if f not in flags:
                    flags.append(f)

            if archetype == "multipoint":
                # Discrete scattered locations (e.g. 'IN VICINITY OF'
                # wellhead/platform lists, buoy lists): individual
                # markers, never a connected shape. Prevents the
                # tangled-polygon bug.
                spatial = {"type": "MultiPoint", "coordinates": points}
            elif archetype == "bounding_box":
                if count_mismatch:
                    spatial = {"type": "MultiPoint", "coordinates": points}
                    basis = "fallback:count_mismatch"
                else:
                    # 'AREA BOUNDED WITHIN': two opposite corners define
                    # the rectangle — expand into a proper closed ring
                    # rather than a 2-point corridor LineString.
                    lon_a, lat_a = points[0]
                    lon_b, lat_b = points[1]
                    spatial = {"type": "Polygon", "coordinates": [[
                        [lon_a, lat_a], [lon_b, lat_a], [lon_b, lat_b],
                        [lon_a, lat_b], [lon_a, lat_a],
                    ]]}
            elif archetype == "linestring":
                # Sequential track/route/trackline: open path, never
                # auto-closed. A source that repeats the first vertex at
                # the end (IV 153/26's closed listing) describes a ring:
                # drop the duplicated closing vertex so the line stays open.
                if len(points) > 1 and points[0] == points[-1]:
                    points = points[:-1]
                spatial = {"type": "LineString", "coordinates": points}
            elif len(points) == 2:
                spatial = {"type": "LineString", "coordinates": points}
                if basis is None:
                    basis = "fallback:two_point_line"
            elif len(points) == 3 and basis is None:
                # THREE unlabelled open positions can never close into
                # a declared ring: a LineString would invent a path
                # (A5). Discrete markers + review flag. Larger
                # unlabelled lists fall through to the ring guard: a
                # 5-position list is geometrically indistinguishable
                # from a genuine 5-corner area (XII 151/26 sub-area B),
                # so only the ring topology can decide.
                if "AMBIGUOUS_FALLBACK" not in flags:
                    flags.append("AMBIGUOUS_FALLBACK")
                spatial = {"type": "MultiPoint", "coordinates": points}
                basis = "fallback:unlabelled_points"
            else:
                # Legacy default for bounded areas / unknown multi-vertex
                # arrays: closed polygon ring — but only if the ring is a
                # valid, non-self-intersecting boundary (>= 3 unique
                # vertices) AND the completeness check passed.
                ring = points if points[0] == points[-1] else points + [points[0]]
                unique_vertices = {tuple(p) for p in ring}
                ring_ok = len(unique_vertices) >= 3 and ring_is_simple(ring)
                if ring_ok and not count_mismatch:
                    spatial = {"type": "Polygon", "coordinates": [ring]}
                    if basis is None:
                        basis = "fallback:legacy_polygon"
                elif count_mismatch:
                    # Refused positions present: never close the
                    # remainder into a ring (A1 completeness check).
                    if "AMBIGUOUS_FALLBACK" not in flags:
                        flags.append("AMBIGUOUS_FALLBACK")
                    spatial = {"type": "MultiPoint", "coordinates": points}
                    basis = "fallback:count_mismatch"
                elif basis is None:
                    # Bowtie/crooked order with NO keyword evidence:
                    # discrete markers + review flag, never a
                    # fabricated shape or path (A5).
                    if "AMBIGUOUS_FALLBACK" not in flags:
                        flags.append("AMBIGUOUS_FALLBACK")
                    spatial = {"type": "MultiPoint", "coordinates": points}
                    basis = "fallback:bowtie"
                else:
                    # Keyword-declared boundary enumeration ('LINES
                    # JOINING' / bounded-area wording) in crooked list
                    # order: keep the legacy OPEN PATH. The memo
                    # pipelines (IV/XII ring-to-trackline contract:
                    # 206/26 iceberg limits, 862/24) rely on never
                    # receiving marker clouds for declared tracks.
                    spatial = {"type": "LineString", "coordinates": points}

            if basis:
                if basis.startswith("keyword:") or basis.startswith("explicit:"):
                    quality = "EXPLICIT"
                elif basis.startswith("heuristic:"):
                    quality = "INFERRED"
                else:
                    quality = "AMBIGUOUS"
            if "AMBIGUOUS_FALLBACK" in flags:
                quality = "AMBIGUOUS"
    else:
        # 'AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO <lon>' lists
        # its axes separately (no pairs): fall back to axis tokens so
        # these bounded-area warnings plot as rectangles instead of
        # nothing.
        bbox_spatial, bbox_lat, bbox_lon = _bbox_from_axis_tokens(text)
        if bbox_spatial:
            return [], bbox_lat, bbox_lon, bbox_spatial, {
                "flags": [], "basis": "keyword:bounding_box",
                "data_quality": "EXPLICIT", "accepted": [], "rejected": [],
            }
        if RE_LOOSE_HEM_TOKEN.search(text):
            flags.append("COORD_COUNT_MISMATCH")

    report = {
        "flags": flags,
        "basis": basis,
        "data_quality": quality,
        "accepted": accepted,
        "rejected": rejected,
    }
    return parsed_coords, primary_lat, primary_lon, spatial, report


def parse_coordinates(raw_text: str, context_text: Optional[str] = None):
    """
    Extracts navigational coordinates from text (see the pattern block
    above): hyphen DMM (incl. glued tails and 'LAT./LONG.' wording), DMS
    with (decimal) seconds, Peru fractional-hyphen, spaced-hyphen (South
    Africa) and space/tab-separated DMM (Canada, Pakistan). Line-wrapped
    coordinate tokens are rejoined before extraction.
    Returns: (parsed_coords_list, primary_lat, primary_lon, spatial_geojson)
    For polygons and line segments, primary_lat and primary_lon represent
    the centroid. Use parse_coordinates_detailed() for the qa report
    (basis, data_quality, accepted/rejected tokens).
    context_text (optional) is the surrounding clause/item text used for
    keyword classification only (e.g. an 'IN AREAS BOUND BY' preamble
    outside the sub-area segment); coordinates are extracted from
    raw_text alone.
    """
    parsed_coords, lat, lon, spatial, _report = parse_coordinates_detailed(
        raw_text, context_text)
    return parsed_coords, lat, lon, spatial


RE_LETTERED_CLAUSE = re.compile(r"^[ \t]*([A-Z])\.[\s]+(?=\d)", re.MULTILINE)


def parse_block_geometries(raw_text: str):
    """
    Clause-aware geometry parse for the dedicated single-block parsers
    (NAVAREA I, XI, Baltic): lettered sub-areas ('A. 12-34.5N ...') that
    directly introduce coordinates are parsed as SEPARATE geometries
    (NAVAREA XI 0475/26: areas A/B/C must never merge into one shape).
    Rejoins line-wrapped tokens, aggregates qa flags and worst-case data
    quality across clauses.

    Returns (geoms, coords_text, qa_flags, data_quality) where geoms is a
    list of (label, spatial, lat, lon) and coords_text the canonical
    coordinate strings of all clauses in order.
    """
    text = rejoin_wrapped_coords(raw_text or "")
    marks = [(m.start(), m.group(1)) for m in RE_LETTERED_CLAUSE.finditer(text)]
    clauses = []
    if marks:
        preamble = text[:marks[0][0]].strip()
        if preamble:
            clauses.append((None, preamble))
        for k, (start, label) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
            seg = text[start:end].strip()
            if seg:
                clauses.append((label, seg))
    else:
        clauses.append((None, text))

    _dq_order = {"EXPLICIT": 0, "INFERRED": 1, "AMBIGUOUS": 2}
    geoms = []
    coords_text = []
    qa_flags = []
    data_quality = None

    for label, clause_text in clauses:
        if not clause_text:
            continue
        coords, lat, lon, spatial, report = parse_coordinates_detailed(clause_text)
        coords_text.extend(coords)
        for flag in report.get("flags") or []:
            if flag not in qa_flags:
                qa_flags.append(flag)
        basis = report.get("basis")
        if basis:
            entry = "geometry_basis:" + basis
            if entry not in qa_flags:
                qa_flags.append(entry)
        clause_quality = report.get("data_quality")
        if clause_quality and (
            data_quality is None
            or _dq_order[clause_quality] > _dq_order[data_quality]
        ):
            data_quality = clause_quality
        if spatial:
            geoms.append((label, spatial, lat, lon))

    return geoms, coords_text, qa_flags, data_quality


# --- hazard classification negative guards (audit finding F4, 2026-10-30) --
#
# Sentences that announce a CANCELLATION (or state that a reported
# hazard is NO LONGER present) describe the CANCELLED warning, not this
# one: a pure cancel notice repeats the dead warning's vocabulary and
# substring matching tagged the NOTICE with the dead warning's hazard
# (NAVAREA XI 0479/26 tagged 'drifting'). Such sentences are stripped
# before keyword matching; a notice whose text is only cancellations
# classifies as 'general'.
RE_CANCEL_SENTENCE = re.compile(r"(?:^|[.!?\n])[^.!?\n]*\bCANCEL(?:L?ATION|L?ED|L?ING|S?)\b[^.!?\n]*[.!?\n]?", re.IGNORECASE)
RE_NO_LONGER_SENTENCE = re.compile(r"(?:^|[.!?\n])[^.!?\n]*\bNO LONGER\b[^.!?\n]*[.!?\n]?", re.IGNORECASE)


def classify_hazard_categories(raw_text: str) -> list[str]:
    """Classifies all matching maritime hazard categories based on terminology.

    Priority + negative guards (audit finding F4, 2026-10-30):
      - electronic interference is checked FIRST, so GNSS/GPS jamming
        warnings that mention nearby platforms/rigs never file as
        'offshore' as their primary category;
      - cancellation/retraction sentences are stripped before keyword
        matching (see the guards above);
      - space/rocket-debris re-entry areas are launch-related
        (military), never 'drifting' objects.
    """
    if not raw_text or not isinstance(raw_text, str):
        return ["general"]

    text = RE_NO_LONGER_SENTENCE.sub(
        " ", RE_CANCEL_SENTENCE.sub(" ", raw_text.upper()))
    if not re.search(r"[A-Z]{3}", text):
        # Only cancellation/retraction sentences remained: a pure
        # cancel notice carries no hazard of its own.
        return ["general"]

    categories: list[str] = []

    if any(k in text for k in ["GNSS", "DGPS", "GPS", "GLONASS", "GALILEO",
            "BEIDOU", "AIS INTERFERENCE", "RADAR INTERFERENCE",
            "INTERFERENCE", "JAMMING", "SPOOFING"]):
        categories.append("electronic")

    military_pattern = (r"\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|"
                        r"MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|"
                        r"NAVAL EXERCISES|MILITARY EXERCISE|SPACE DEBRIS|"
                        r"ROCKET DEBRIS|ROCKET LAUNCH)\b")
    if re.search(military_pattern, text):
        categories.append("military")

    if any(k in text for k in ["LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON",
            "UNLIT", "EXTINGUISHED", "OFF AIR"]):
        categories.append("aton")

    if any(k in text for k in ["SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING",
            "DREDGING", "ANCHOR", "CHAIN LOST", "SUNKEN WRECK"]):
        categories.append("subsea")

    if any(k in text for k in ["DRIFTING", "DERELICT", "MINE", "CONTAINER",
            "ADRIFT"]):
        categories.append("drifting")

    if any(k in text for k in ["RIG", "PLATFORM", "JACK-UP"]):
        categories.append("offshore")

    return categories if categories else ["general"]



def classify_hazard(raw_text: str) -> str:
    """Classifies primary maritime hazard category (first matched category)."""
    cats = classify_hazard_categories(raw_text)
    return cats[0] if cats else "general"


def compute_differential(
    scraped_warnings: List[Dict[str, Any]],
    scraped_messages: List[Dict[str, Any]],
    existing_warnings: Dict[str, Dict[str, Any]],
    existing_checksums: Set[Tuple[str, str]],
    key_fn: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Deterministically computes differential actions between scraped data and current database state.
    Supports canonical_id and custom key function.
    Returns: {'skip': [...], 'new': [...], 'update': [...], 'cancel': [...]}
    """
    scraped_warnings = scraped_warnings if scraped_warnings is not None else []
    scraped_messages = scraped_messages if scraped_messages is not None else []
    existing_warnings = existing_warnings if existing_warnings is not None else {}
    existing_checksums = existing_checksums if existing_checksums is not None else set()

    msg_map: Dict[str, Dict[str, Any]] = {}
    for m in scraped_messages:
        if isinstance(m, dict):
            if m.get("warning_id"):
                msg_map[str(m["warning_id"])] = m
            if m.get("canonical_id"):
                msg_map[str(m["canonical_id"])] = m

    to_skip = []
    to_insert_new = []
    to_update = []

    seen_ids = set()

    for warn in scraped_warnings:
        if not isinstance(warn, dict):
            continue
        if key_fn is not None:
            wid = key_fn(warn)
        else:
            wid = warn.get("canonical_id") or warn.get("warning_id")
        if not wid:
            continue
        seen_ids.add(wid)

        raw_msg = msg_map.get(wid) or msg_map.get(warn.get("warning_id", "")) or {}
        chk = raw_msg.get("checksum_sha256", "")

        existing_record = existing_warnings.get(wid)

        if existing_record:
            is_active = existing_record.get("status") == "active"
            checksum_matches = (
                (wid, chk) in existing_checksums or
                (warn.get("warning_id", ""), chk) in existing_checksums
            )

            if is_active and checksum_matches:
                to_skip.append(wid)
            else:
                to_update.append((warn, raw_msg))
        else:
            to_insert_new.append((warn, raw_msg))

    to_cancel = [
        wid for wid, record in existing_warnings.items()
        if record.get("status") == "active" and wid not in seen_ids
    ]

    return {
        "skip": to_skip,
        "new": to_insert_new,
        "update": to_update,
        "cancel": to_cancel
    }
