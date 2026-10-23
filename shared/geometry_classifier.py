#!/usr/bin/env python3
"""
shared/geometry_classifier.py — Deterministic geometry-archetype classification.

Fixes the tangled-polygon map bug: parse_coordinates() previously forced any
coordinate array with >= 4 points into an auto-closed Polygon, which draws a
fake, self-intersecting exclusion zone when the points are actually discrete
locations ("IN VICINITY OF" wellhead/platform lists) or a sequential survey
track.

Classification returns one of:
  "multipoint"   — discrete, independent locations (buoys, rigs, wrecks,
                   'VICINITY OF' lists); render as markers, never connected
  "linestring"   — sequential track/route/trackline; render as open polyline
  "bounding_box" — "AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO <lon>":
                   two opposite corners define a rectangle (NAVAREA VIII
                   1102/26 format); caller expands corners into a ring
  None            — no keyword evidence; caller falls back to legacy
                   behaviour (polygon if the ring is a valid boundary,
                   else an open LineString)

Rule-first only (no AI fallback, per pipeline policy). Keyword-derived
geometry is a display decision, not a provenance claim: it does not alter
data_quality or triage tiers, which remain governed by shared/models.

Keyword taxonomy (validated against live NAVAREA bulletins, Oct 2026):
  Area  -> AREA BOUNDED BY / BOUND BY / AREA BOUNDED WITHIN / EXCLUSION
           ZONE / RESTRICTED AREA / LINES JOINING (boundary enumeration)
  Line  -> TRACKLINE / CENTRELINE / ALONG LINE JOINING / FOLLOWING ROUTES /
           TRACK / ROUTE / TOW / TOWING / CABLE LAY / PIPELINE / SWEEP
  Point -> WELL HEAD / PLATFORM / RIG / BUOY / RACON / BEACON / MOORING /
           LIGHT VESSEL / WRECK / SHOAL / ROCK (incl. plural forms)

Sequential-vs-scattered detection uses the adjacent-nearest-neighbour test:
  scattered sets score ~0.1-0.15, a realistically sampled survey track ~1.0.
Threshold 0.70; only trusted for n >= 5 (small scattered sets can pass by
chance — observed at n=4).

Ring topology (ring_is_simple): pure-Python segment-intersection test
equivalent to Shapely's Polygon.is_valid / Turf's kinks() — no new
dependency. NAVAREA VIII 961/26's legacy ring fails this check, which is
exactly the "crooked polygon" observed on the map.
"""

from __future__ import annotations

import math
import re
from typing import Optional, Sequence

EARTH_RADIUS_M = 6_371_000.0
SEQUENTIAL_NN_THRESHOLD = 0.70
MIN_SEQUENTIAL_N = 5

# Word boundaries are mandatory: without them RIG matches "ORIGINAL" and
# LINE matches "COASTLINE". Plurals are explicit (\bRIG\b does NOT match
# "RIGS" — a bare \b...\\b token fails on word suffixes).
RE_BOUNDED = re.compile(
    r"AREA\s+BOUNDED\s+BY|BOUND\s+BY|EXCLUSION\s+ZONE|RESTRICTED\s+AREA"
    r"|LINES?\s+JOINING"
)
RE_BBOX = re.compile(r"AREA\s+BOUNDED\s+WITHIN")
RE_POINT_OPS = re.compile(
    r"\b(?:WELL\s*HEADS?|WELLHEADS?|PLATFORMS?|RIGS?|BUOYS?|RACONS?|BEACONS?"
    r"|MOORINGS?|LIGHT\s*VESSELS?|LV|WRECKS?|SHOALS?|ROCKS?)\b"
)
RE_LINEAR_OPS = re.compile(
    r"\b(?:TRACKS?|ROUTES?|TOWS?|TOWING|CABLE\s*LAY|PIPELINES?|SWEEPS?"
    r"|TRACKLINE|CENTRELINES?|ALONG\s+LINE\s+JOINING|FOLLOWING\s+ROUTES?)\b"
)
RE_SURVEY = re.compile(r"\bSURVEY\b")
RE_VICINITY = re.compile(r"VICINITY\s+OF")


def _haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _is_sequential(points: Sequence[Sequence[float]]) -> bool:
    """
    True if the array reads as a sequential track: for most points, the
    nearest neighbour is the previous or next point in listed order.
    """
    n = len(points)
    if n < 3:
        return True
    adjacent = 0
    for i in range(n):
        best_d, best_j = math.inf, -1
        for j in range(n):
            if i == j:
                continue
            d = _haversine_m(points[i], points[j])
            if d < best_d:
                best_d, best_j = d, j
        if abs(best_j - i) == 1:
            adjacent += 1
    return (adjacent / n) >= SEQUENTIAL_NN_THRESHOLD


# --- ring topology validation (pure Python; no new dependency) ---------------


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p) -> bool:
    return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def _segments_intersect(p1, p2, p3, p4) -> bool:
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def ring_is_simple(ring: Sequence[Sequence[float]]) -> bool:
    """
    True if a closed coordinate ring forms a non-self-intersecting
    polygon boundary (no bowties/crossings; adjacent edges excluded).
    A ring needs >= 4 positions (3 unique vertices + closing vertex).
    Pure-Python O(n^2) segment test — rings in NAVAREA bulletins are tiny.
    """
    if len(ring) < 4:
        return False
    n = len(ring) - 1  # number of edges in the closed ring
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges legitimately share a vertex
            if _segments_intersect(ring[i], ring[i + 1], ring[j], ring[j + 1]):
                return False
    return True


def classify_geometry_archetype(
    raw_text: str, points: Sequence[Sequence[float]]
) -> Optional[str]:
    """
    Classifies a warning's coordinate array into a display archetype.

    raw_text: the clause/body text the coordinates were extracted from
              (the SAME text passed to parse_coordinates — no re-parsing).
    points:   GeoJSON-order [lon, lat] pairs from the shared parser.
    Returns "multipoint" | "linestring" | "bounding_box" | None.
    """
    if not raw_text or len(points) < 2:
        return None
    text = raw_text.upper()

    # 'AREA BOUNDED WITHIN <lat> TO <lat> AND <lon> TO <lon>': two opposite
    # corners (NAVAREA VIII 1102/26). Expand into a rectangle ring.
    if RE_BBOX.search(text) and len(points) == 2:
        return "bounding_box"

    # Explicit bounded areas keep the legacy polygon rendering (with the
    # ring topology guard applied by the caller).
    if RE_BOUNDED.search(text):
        return None

    # Discrete structures (buoys, rigs, racons, wrecks, moorings) and
    # 'vicinity of' lists are scattered individual locations.
    if RE_POINT_OPS.search(text) or RE_VICINITY.search(text):
        return "multipoint"

    # Linear operations / surveys without 'vicinity'.
    if RE_LINEAR_OPS.search(text) or RE_SURVEY.search(text):
        if len(points) == 2:
            return "linestring"
        if len(points) >= MIN_SEQUENTIAL_N and _is_sequential(points):
            return "linestring"
        # Scattered survey points without 'vicinity': discrete markers are
        # the safe representation — a polygon would fabricate an area.
        return "multipoint"

    # No keyword evidence: caller falls back to legacy behaviour.
    return None
