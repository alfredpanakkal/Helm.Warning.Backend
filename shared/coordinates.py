#!/usr/bin/env python3
"""
shared/coordinates.py - Coordinate parsing and conversion utilities

Provides functionality for:
- Parsing coordinate strings in various formats
- Converting to WGS84 decimal degrees
- Generating GeoJSON geometries
- Validating coordinate values
"""

import re
from typing import List, Tuple, Optional, Dict, Any

def convert_to_decimal(degrees: str, minutes: str, seconds: Optional[str] = None,
                      direction: str = 'N') -> float:
    """
    Convert degrees, minutes, and optional seconds to signed decimal degrees (WGS84).
    """
    decimal = float(degrees)

    if minutes:
        decimal += float(minutes) / 60.0
    if seconds:
        decimal += float(seconds) / 3600.0

    if direction.upper() in ['S', 'W']:
        decimal = -decimal

    return round(decimal, 6)

def parse_coordinates(raw_text: str) -> Tuple[List[str], Optional[float], Optional[float], Optional[Dict]]:
    """
    Extract navigational coordinates from text.

    Handles varied precision formats:
    - DD-MM.MM[N/S] DDD-MM.MM[E/W] (degrees and decimal minutes)
    - DD-MM.MM-SS.SS[N/S] DDD-MM.MM-SS.SS[E/W] (degrees, minutes, seconds)
    - DD-MM[N/S] DDD-MM[E/W] (degrees and minutes without decimals)
    """
    pattern = r'(\d{2,3})-(\d{2}(?:\.\d+)?)(?:-(\d{2}(?:\.\d+)?))?([NS])\s+(\d{2,3})-(\d{2}(?:\.\d+)?)(?:-(\d{2}(?:\.\d+)?))?([EW])'
    matches = list(re.finditer(pattern, raw_text, re.IGNORECASE))

    parsed_coords = []
    points = []

    for match in matches:
        lat_deg, lat_min, lat_sec, lat_dir = match.group(1), match.group(2), match.group(3), match.group(4).upper()
        lon_deg, lon_min, lon_sec, lon_dir = match.group(5), match.group(6), match.group(7), match.group(8).upper()

        lat = convert_to_decimal(lat_deg, lat_min, lat_sec, lat_dir)
        lon = convert_to_decimal(lon_deg, lon_min, lon_sec, lon_dir)

        points.append([lon, lat])

        lat_str = f"{lat_deg}-{lat_min}" + (f"-{lat_sec}" if lat_sec else "") + lat_dir
        lon_str = f"{lon_deg}-{lon_min}" + (f"-{lon_sec}" if lon_sec else "") + lon_dir
        parsed_coords.append(f"{lat_str} {lon_str}")

    spatial = None
    primary_lat = None
    primary_lon = None

    if points:
        if len(points) == 1:
            primary_lat = points[0][1]
            primary_lon = points[0][0]
            spatial = {"type": "Point", "coordinates": points[0]}
        elif len(points) >= 4:
            primary_lat = round(sum(p[1] for p in points) / len(points), 6)
            primary_lon = round(sum(p[0] for p in points) / len(points), 6)
            closed_points = points if points[0] == points[-1] else points + [points[0]]
            spatial = {"type": "Polygon", "coordinates": [closed_points]}
        else:
            primary_lat = points[0][1]
            primary_lon = points[0][0]
            spatial = {"type": "LineString", "coordinates": points}

    return parsed_coords, primary_lat, primary_lon, spatial

def validate_coordinate(lat: Optional[float], lon: Optional[float]) -> bool:
    """Validate coordinate values."""
    if lat is None or lon is None:
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180

def format_coordinate_string(lat: float, lon: float) -> str:
    """Format coordinates as a display string."""
    lat_dir = 'N' if lat >= 0 else 'S'
    lon_dir = 'E' if lon >= 0 else 'W'

    lat_abs = abs(lat)
    lon_abs = abs(lon)

    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60

    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60

    return f"{lat_deg:02d}-{lat_min:06.3f}{lat_dir} {lon_deg:03d}-{lon_min:06.3f}{lon_dir}"

def create_point_geometry(lon: float, lat: float) -> Dict[str, Any]:
    """Create a GeoJSON Point geometry."""
    return {"type": "Point", "coordinates": [lon, lat]}

def create_polygon_geometry(points: List[Tuple[float, float]]) -> Dict[str, Any]:
    """Create a GeoJSON Polygon geometry."""
    closed_points = points if points[0] == points[-1] else points + [points[0]]
    return {"type": "Polygon", "coordinates": [closed_points]}

def create_linestring_geometry(points: List[Tuple[float, float]]) -> Dict[str, Any]:
    """Create a GeoJSON LineString geometry."""
    return {"type": "LineString", "coordinates": points}
