import {
  GeoJsonGeometry,
  SpatialBundle,
  SpatialCircle,
  SpatialCorridor,
  DriftVector
} from '../types/maritime';

/**
 * Convert degrees, minutes, and optional seconds to signed decimal degrees (WGS84).
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
  spatialBundle: SpatialBundle | null;
  circles: SpatialCircle[];
  corridors: SpatialCorridor[];
  driftVectors: DriftVector[];
}

export const NAVAREA_BOUNDING_BOXES: Record<string, { minLat: number; maxLat: number; minLon: number; maxLon: number }> = {
  Baltic: { minLat: 53.0, maxLat: 66.5, minLon: 9.0, maxLon: 31.0 },
  'NA I': { minLat: 48.0, maxLat: 75.0, minLon: -25.0, maxLon: 15.0 },
  'NA XI': { minLat: -12.0, maxLat: 55.0, minLon: 95.0, maxLon: 180.0 }
};

export function validateNavareaBounds(
  lat: number,
  lon: number,
  navarea: string
): { isValid: boolean; warning?: string } {
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return { isValid: false, warning: `Coordinates out of WGS84 range: [${lat}, ${lon}]` };
  }

  const box = NAVAREA_BOUNDING_BOXES[navarea];
  if (!box) {
    return { isValid: true };
  }

  const inBounds =
    lat >= box.minLat &&
    lat <= box.maxLat &&
    lon >= box.minLon &&
    lon <= box.maxLon;

  if (!inBounds) {
    return {
      isValid: false,
      warning: `Position [${lat.toFixed(4)}, ${lon.toFixed(4)}] is outside designated ${navarea} bounding box`
    };
  }

  return { isValid: true };
}

/**
 * Great-circle distance between two WGS84 points in Nautical Miles.
 */
export function computeDistanceNm(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R_NM = 3440.065; // Earth radius in NM
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R_NM * c * 100) / 100;
}

/**
 * Planar approximation of polygon area in square Nautical Miles.
 */
export function computePolygonAreaSqNm(coords: [number, number][]): number {
  if (coords.length < 3) return 0;
  let area = 0;
  const rad = Math.PI / 180;
  const meanLat = (coords.reduce((acc, c) => acc + c[1], 0) / coords.length) * rad;
  const cosMeanLat = Math.cos(meanLat);

  for (let i = 0; i < coords.length - 1; i++) {
    const x1 = coords[i][0] * 60 * cosMeanLat;
    const y1 = coords[i][1] * 60;
    const x2 = coords[i + 1][0] * 60 * cosMeanLat;
    const y2 = coords[i + 1][1] * 60;
    area += x1 * y2 - x2 * y1;
  }
  return Math.round(Math.abs(area) / 2 * 10) / 10;
}

/**
 * Compute corridor polygon around a LineString of [lon, lat] coordinates given width in NM.
 */
export function computeLineCorridor(
  points: [number, number][],
  widthNm: number
): [number, number][] {
  if (points.length < 2 || widthNm <= 0) return points;

  const leftSide: [number, number][] = [];
  const rightSide: [number, number][] = [];
  const halfWidth = widthNm / 2;

  for (let i = 0; i < points.length; i++) {
    let dx = 0;
    let dy = 0;

    if (i < points.length - 1) {
      dx += points[i + 1][0] - points[i][0];
      dy += points[i + 1][1] - points[i][1];
    }
    if (i > 0) {
      dx += points[i][0] - points[i - 1][0];
      dy += points[i][1] - points[i - 1][1];
    }

    const midLat = points[i][1];
    const cosLat = Math.max(0.1, Math.cos((midLat * Math.PI) / 180));
    const len = Math.sqrt((dx * cosLat) * (dx * cosLat) + dy * dy);

    if (len === 0) continue;

    // Normal vector perpendicular to path
    const normX = -dy / len;
    const normY = (dx * cosLat) / len;

    // Offset in decimal degrees (1 deg lat = 60 NM)
    const offLat = (normY * halfWidth) / 60;
    const offLon = (normX * halfWidth) / (60 * cosLat);

    leftSide.push([points[i][0] + offLon, points[i][1] + offLat]);
    rightSide.unshift([points[i][0] - offLon, points[i][1] - offLat]);
  }

  const corridor = [...leftSide, ...rightSide];
  if (corridor.length > 0) {
    corridor.push(corridor[0]); // close polygon
  }
  return corridor;
}

/**
 * Extract navigational coordinates and spatial features from text.
 * Generates Point, Polygon, LineString, SpatialCircle, and SpatialCorridor.
 */
export function parseCoordinates(rawText: string): ParsedCoordinatesResult {
  const pattern = /(?:(\d{2,3})[°\s-](\d{1,2}(?:\.\d+)?)[′']?(?:[°\s-](\d{1,2}(?:\.\d+)?)[″"])?\s*([NS]))[\s,]+(?:(\d{2,3})[°\s-](\d{1,2}(?:\.\d+)?)[′']?(?:[°\s-](\d{1,2}(?:\.\d+)?)[″"])?\s*([EW]))/gi;
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
  const circles: SpatialCircle[] = [];
  const corridors: SpatialCorridor[] = [];
  const driftVectors: DriftVector[] = [];

  // Parse radius and safety clearances across all coordinate configurations
  const radiusMatch =
    rawText.match(/radius\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:nm|nautical\s+miles?)/i) ||
    rawText.match(/within\s+(\d+(?:\.\d+)?)\s*(?:nm|nautical\s+miles?)/i);
  const metersMatch =
    rawText.match(/safety\s+zone\s+(?:of\s+)?(\d+)\s*(?:m|mtr|metres?|meters?)/i) ||
    rawText.match(/(\d+)\s*(?:mtr|metres?|meters?)\s+clearance/i);
  const clearanceMatch = rawText.match(/(\d+(?:\.\d+)?)\s*m\s+clearance/i);
  const wideBerthMatch = rawText.match(/wide\s+berth\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:nm|nautical\s+miles?|miles?)/i);

  let clearanceRadiusNm: number | null = null;
  let clearanceLabel = '';

  if (radiusMatch) {
    clearanceRadiusNm = parseFloat(radiusMatch[1]);
    clearanceLabel = `Danger Zone (${clearanceRadiusNm} NM Radius)`;
  } else if (wideBerthMatch) {
    clearanceRadiusNm = parseFloat(wideBerthMatch[1]);
    clearanceLabel = `Wide Berth Zone (${clearanceRadiusNm} NM Swath)`;
  } else if (metersMatch) {
    const meters = parseFloat(metersMatch[1]);
    clearanceRadiusNm = Math.round((meters / 1852) * 100) / 100;
    clearanceLabel = `Safety Zone (${meters}m / ${clearanceRadiusNm} NM)`;
  } else if (clearanceMatch) {
    const val = parseFloat(clearanceMatch[1]);
    clearanceRadiusNm = val <= 20 ? val : Math.round((val / 1852) * 100) / 100;
    clearanceLabel = `Clearance Zone (${clearanceRadiusNm} NM)`;
  }

  // Parse drift directions
  const driftMatch = rawText.match(/drifting\s+(eastward|westward|northward|southward|northeast|northwest|southeast|southwest|east|west|north|south)/i);
  const driftBearingMap: Record<string, number> = {
    north: 0,
    northward: 0,
    northeast: 45,
    east: 90,
    eastward: 90,
    southeast: 135,
    south: 180,
    southward: 180,
    southwest: 225,
    west: 270,
    westward: 270,
    northwest: 315
  };

  if (points.length === 1) {
    primaryLat = points[0][1];
    primaryLon = points[0][0];
    spatial = { type: 'Point', coordinates: points[0] };

    if (clearanceRadiusNm !== null) {
      circles.push({
        center: [primaryLon, primaryLat],
        radius_nm: clearanceRadiusNm,
        label: clearanceLabel
      });
    }

    if (driftMatch) {
      const dirKey = driftMatch[1].toLowerCase();
      const bearing = driftBearingMap[dirKey] ?? 90;
      driftVectors.push({
        origin: [primaryLon, primaryLat],
        bearing_deg: bearing,
        speed_knots: 1.5,
        label: `Projected Drift (${dirKey.toUpperCase()})`
      });
    }
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

    // If clearance requested around polygon perimeter
    if (clearanceRadiusNm !== null) {
      circles.push({
        center: [primaryLon, primaryLat],
        radius_nm: clearanceRadiusNm,
        label: clearanceLabel
      });
    }
  } else if (points.length >= 2) {
    primaryLat = points[0][1];
    primaryLon = points[0][0];
    spatial = {
      type: 'LineString',
      coordinates: points
    };

    // If clearance or wide berth requested along the line, generate a corridor
    if (clearanceRadiusNm !== null) {
      const corridorPolygon = computeLineCorridor(points, clearanceRadiusNm * 2);
      corridors.push({
        path: points,
        width_nm: clearanceRadiusNm * 2,
        label: clearanceLabel,
        polygon: corridorPolygon
      });
    }
  }

  const spatialBundle: SpatialBundle | null =
    spatial || circles.length > 0 || corridors.length > 0 || driftVectors.length > 0
      ? {
          geometries: spatial ? [spatial] : [],
          circles,
          corridors,
          driftVectors
        }
      : null;

  return {
    parsedCoords,
    primaryLat,
    primaryLon,
    spatial,
    spatialBundle,
    circles,
    corridors,
    driftVectors
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
