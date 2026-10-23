#!/usr/bin/env python3
"""
shared/geometry_classifier.py — Deterministic geometry-archetype classification.

Fixes the tangled-polygon map bug: parse_coordinates() previously forced any
coordinate array with >= 4 points into an auto-closed Polygon, which draws a
fake, self-intersecting exclusion zone when the points are actually discrete
locations ("IN VICINITY OF" wellhead/platform lists) or a sequential survey
track.

Classification returns one of:
  "multipoint"  — discrete, independent locations; render as markers,
                  never as a connected shape or convex hull
  "linestring"  — sequential track/route; render as an open polyline
  None           — no keyword evidence; caller falls back to legacy
                  behaviour (polygon >= 4 points, else linestring)

Rule-first only (no AI fallback, per pipeline policy). Keyword-derived
geometry is a display decision, not a provenance claim: it does not alter
data_quality or triage tiers, which remain governed by shared/models.

Validated against live bulletins (Oct 2026):
  NAVAREA VIII 961/26  (SEABED SURVEY ... IN VICINITY OF, 9 scattered) -> multipoint
  NAVAREA VIII 1096/26 (WELL HEAD PLATFORM ... VICINITY OF, 30 pts)     -> multipoint
Sequential-vs-scattered detection uses the adjacent-nearest-neighbour test:
  scattered sets score ~0.1-0.15, a realistically sampled survey track ~1.0.
Threshold 0.70; only trusted for n >= 5 (small scattered sets can pass by
chance — observed at n=4).
"""

from __future__ import annotations

import math
import re
from typing import Optional, Sequence

EARTH_RADIUS_M = 6_371_000.0
SEQUENTIAL_NN_THRESHOLD = 0.70
MIN_SEQUENTIAL_N = 5

# Word boundaries are mandatory: without them RIG matches "ORIGINAL"
# and LINE matches "COASTLINE".
RE_BOUNDED = re.compile(r"AREA\s+BOUNDED\s+BY|LINES?\s+JOINING|BOUNDING\s+LINES?")
RE_POINT_OPS = re.compile(
    r"\b(?:WELL\s*HEAD|WELLHEAD|PLATFORM|RIG|BUOY|LIGHT\s*VESSEL|LV|WRECK)\b"
)
RE_LINEAR_OPS = re.compile(r"\b(?:TRACK|ROUTE|TOW|TOWING|CABLE\s*LAY|PIPELINE|SWEEP)\b")
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


def classify_geometry_archetype(
    raw_text: str, points: Sequence[Sequence[float]]
) -> Optional[str]:
    """
    Classifies a warning's coordinate array into a display archetype.

    raw_text: the clause/body text the coordinates were extracted from
              (the SAME text passed to parse_coordinates — no re-parsing).
    points:   GeoJSON-order [lon, lat] pairs from the shared parser.
    Returns "multipoint" | "linestring" | None (None -> legacy behaviour).
    """
    if not raw_text or len(points) < 2:
        return None
    text = raw_text.upper()

    # Explicit bounded area keeps the legacy polygon rendering.
    if RE_BOUNDED.search(text):
        return None

    # Discrete structures (wellheads, rigs, buoys) and 'vicinity of' lists
    # are scattered individual locations — never a connected shape.
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
