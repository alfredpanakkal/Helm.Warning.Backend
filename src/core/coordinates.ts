import { GeoJsonGeometry } from '../types/maritime';

/**
 * Convert degrees, minutes, and optional seconds to signed decimal degrees (WGS84).
 * Matches shared/coordinates.py convert_to_decimal.
 */
export function convertToDecimal(
  degrees: string | number,
  minutes: string | number,
  seconds?: string | number | null,
  direction: string = 'N'
): number {
  let decimal = parseFloat(String(degrees));

  if (minutes !== undefined && minutes !== null && String(minutes).length > 0) {
    decimal += parseFloat(String(minutes)) / 60.0;
  }

  if (seconds !== undefined && seconds !== null && String(seconds).length > 0) {
    decimal += parseFloat(String(seconds)) / 3600.0;
  }

  const dir = (direction || 'N').toUpperCase();
  if (dir === 'S' || dir === 'W') {
    decimal = -decimal;
  }

  return Math.round(decimal * 1000000) / 1000000;
}

export interface ParsedCoordinatesResult {
  parsedCoords: string[];
  primaryLat: number | null;
  primaryLon: number | null;
  spatial: GeoJsonGeometry | null;
}

/**
 * Extract navigational coordinates from text.
 * Handles varied precision formats:
 * - DD-MM.MM[N/S] DDD-MM.MM[E/W] (degrees and decimal minutes)
 * - DD-MM.MM-SS.SS[N/S] DDD-MM.MM-SS.SS[E/W] (degrees, minutes, seconds)
 * - DD-MM[N/S] DDD-MM[E/W] (degrees and minutes without decimals)
 *
 * Matches shared/coordinates.py parse_coordinates.
 */
export function parseCoordinates(rawText: string): ParsedCoordinatesResult {
  const pattern = /(\d{2,3})-(\d{2}(?:\.\d+)?)(?:-(\d{2}(?:\.\d+)?))?([NS])\s+(\d{2,3})-(\d{2}(?:\.\d+)?)(?:-(\d{2}(?:\.\d+)?))?([EW])/gi;
  const parsedCoords: string[] = [];
  const points: [number, number][] = []; // [lon, lat]

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(rawText)) !== null) {
    const latDeg = match[1];
    const latMin = match[2];
    const latSec = match[3];
    const latDir = match[4].toUpperCase();

    const lonDeg = match[5];
    const lonMin = match[6];
    const lonSec = match[7];
    const lonDir = match[8].toUpperCase();

    const lat = convertToDecimal(latDeg, latMin, latSec, latDir);
    const lon = convertToDecimal(lonDeg, lonMin, lonSec, lonDir);

    points.push([lon, lat]);

    let latStr = `${latDeg}-${latMin}`;
    if (latSec) latStr += `-${latSec}`;
    latStr += latDir;

    let lonStr = `${lonDeg}-${lonMin}`;
    if (lonSec) lonStr += `-${lonSec}`;
    lonStr += lonDir;

    parsedCoords.push(`${latStr} ${lonStr}`);
  }

  let spatial: GeoJsonGeometry | null = null;
  let primaryLat: number | null = null;
  let primaryLon: number | null = null;

  if (points.length === 1) {
    primaryLat = points[0][1];
    primaryLon = points[0][0];
    spatial = { type: 'Point', coordinates: points[0] };
  } else if (points.length >= 4) {
    primaryLat = Math.round((points.reduce((acc, p) => acc + p[1], 0) / points.length) * 1000000) / 1000000;
    primaryLon = Math.round((points.reduce((acc, p) => acc + p[0], 0) / points.length) * 1000000) / 1000000;

    const isClosed =
      points[0][0] === points[points.length - 1][0] &&
      points[0][1] === points[points.length - 1][1];
    const closedPoints = isClosed ? points : [...points, points[0]];

    spatial = {
      type: 'Polygon',
      coordinates: [closedPoints]
    };
  } else if (points.length >= 2) {
    primaryLat = points[0][1];
    primaryLon = points[0][0];
    spatial = {
      type: 'LineString',
      coordinates: points
    };
  }

  return {
    parsedCoords,
    primaryLat,
    primaryLon,
    spatial
  };
}

/**
 * Format coordinates as a standard display string.
 */
export function formatCoordinateString(lat: number, lon: number): string {
  const latDir = lat >= 0 ? 'N' : 'S';
  const lonDir = lon >= 0 ? 'E' : 'W';

  const latAbs = Math.abs(lat);
  const lonAbs = Math.abs(lon);

  const latDeg = Math.floor(latAbs);
  const latMin = (latAbs - latDeg) * 60;

  const lonDeg = Math.floor(lonAbs);
  const lonMin = (lonAbs - lonDeg) * 60;

  const pad2 = (n: number) => String(n).padStart(2, '0');
  const pad3 = (n: number) => String(n).padStart(3, '0');

  return `${pad2(latDeg)}-${latMin.toFixed(3)}${latDir} ${pad3(lonDeg)}-${lonMin.toFixed(3)}${lonDir}`;
}
