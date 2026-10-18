import {
  GeoJsonGeometry,
  SpatialBundle,
  SpatialCircle,
  SpatialCorridor,
  DriftVector
} from '../types/maritime';

/**
 * Strict coordinate value validation.
 * Latitude requires |lat| <= 90, minutes < 60, seconds < 60.
 * Longitude requires |lon| <= 180, minutes < 60, seconds < 60.
 * 91°00'N is INVALID (never clamped). 0° and 180° longitudes are valid.
 */
export function validateCoordinateValues(
  deg: number,
  min: number,
  sec: number = 0,
  isLatitude: boolean
): { valid: boolean; error?: string } {
  if (isNaN(deg) || isNaN(min) || isNaN(sec)) {
    return { valid: false, error: 'NAN_VALUE' };
  }
  if (min < 0 || min >= 60 || sec < 0 || sec >= 60) {
    return { valid: false, error: 'MIN_SEC_OUT_OF_RANGE' };
  }

  const absVal = Math.abs(deg) + min / 60.0 + sec / 3600.0;
  if (isLatitude) {
    if (absVal > 90.000001) {
      return { valid: false, error: 'LATITUDE_OUT_OF_RANGE' };
    }
  } else {
    if (absVal > 180.000001) {
      return { valid: false, error: 'LONGITUDE_OUT_OF_RANGE' };
    }
  }

  return { valid: true };
}

export type CoordinateValidation = {
  valid: boolean;
  value?: number;
  reason?: string;
};

export type CoordinateProvenance = {
  rawText: string;
  parser: 'rule' | 'ai_proposal';
  hemisphereExplicit: boolean;
  confidence?: number;
  reviewRequired: boolean;
  validationFlags: string[];
};

export function validateAxis(
  degrees: number,
  minutes: number,
  hemisphere: string,
  axis: 'lat' | 'lon'
): CoordinateValidation {
  const hem = hemisphere.toUpperCase();
  const validHemispheres = axis === 'lat' ? ['N', 'S'] : ['E', 'W'];
  const limit = axis === 'lat' ? 90 : 180;

  if (!Number.isFinite(degrees) || !Number.isFinite(minutes)) {
    return { valid: false, reason: 'NON_FINITE_VALUE' };
  }

  if (!validHemispheres.includes(hem)) {
    return { valid: false, reason: 'AXIS_HEMISPHERE_MISMATCH' };
  }

  if (degrees < 0 || !Number.isInteger(degrees) || degrees > limit) {
    return { valid: false, reason: 'DEGREES_OUT_OF_RANGE' };
  }

  if (minutes < 0 || minutes >= 60) {
    return { valid: false, reason: 'MINUTES_OUT_OF_RANGE' };
  }

  if (degrees === limit && minutes > 0) {
    return { valid: false, reason: 'AXIS_OUT_OF_RANGE' };
  }

  const magnitude = degrees + minutes / 60;
  const value = hem === 'S' || hem === 'W' ? -magnitude : magnitude;

  return { valid: true, value };
}

/**
 * Convert degrees, minutes, and optional seconds to signed decimal degrees (WGS84).
 * Returns NaN if strict range validation fails.
 */
export function convertToDecimal(
  degrees: string | number,
  minutes: string | number,
  seconds?: string | number | null,
  direction: string = 'N'
): number {
  const deg = parseFloat(String(degrees));
  const min = minutes !== undefined && minutes !== null && String(minutes).length > 0 ? parseFloat(String(minutes)) : 0;
  const sec = seconds !== undefined && seconds !== null && String(seconds).length > 0 ? parseFloat(String(seconds)) : 0;

  const dir = (direction || 'N').toUpperCase();
  const isLat = dir === 'N' || dir === 'S';

  const check = validateCoordinateValues(deg, min, sec, isLat);
  if (!check.valid) {
    return NaN;
  }

  let decimal = Math.abs(deg) + min / 60.0 + sec / 3600.0;
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
  qaFlags: string[];
  dataQuality: 'EXPLICIT' | 'INFERRED' | 'AMBIGUOUS' | 'INVALID';
  unplottedReason?: string | null;
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
  if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
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
  if (isNaN(lat1) || isNaN(lon1) || isNaN(lat2) || isNaN(lon2)) return 0;
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
  return Math.round((Math.abs(area) / 2) * 10) / 10;
}

/**
 * Detect segment intersection for self-intersecting bowtie polygon check.
 */
function doSegmentsIntersect(
  p1: [number, number],
  p2: [number, number],
  p3: [number, number],
  p4: [number, number]
): boolean {
  const ccw = (a: [number, number], b: [number, number], c: [number, number]) => {
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0]);
  };
  return (
    ccw(p1, p3, p4) !== ccw(p2, p3, p4) && ccw(p1, p2, p3) !== ccw(p1, p2, p4)
  );
}

/**
 * Check if a polygon is self-intersecting and compute a reordered proposal.
 */
export function checkSelfIntersectingPolygon(
  points: [number, number][]
): { isSelfIntersecting: boolean; reorderedPoints: [number, number][] } {
  if (points.length < 4) return { isSelfIntersecting: false, reorderedPoints: points };

  // Remove duplicate closing point if present
  const pts = points[0][0] === points[points.length - 1][0] && points[0][1] === points[points.length - 1][1]
    ? points.slice(0, -1)
    : [...points];

  let isSelfIntersecting = false;
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 2; j < pts.length; j++) {
      if (i === 0 && j === pts.length - 1) continue; // adjacent
      if (doSegmentsIntersect(pts[i], pts[(i + 1) % pts.length], pts[j], pts[(j + 1) % pts.length])) {
        isSelfIntersecting = true;
        break;
      }
    }
    if (isSelfIntersecting) break;
  }

  if (!isSelfIntersecting) return { isSelfIntersecting: false, reorderedPoints: points };

  // Polar angle sort proposal around centroid
  const cX = pts.reduce((a, b) => a + b[0], 0) / pts.length;
  const cY = pts.reduce((a, b) => a + b[1], 0) / pts.length;

  const reordered = [...pts].sort((a, b) => {
    const angleA = Math.atan2(a[1] - cY, a[0] - cX);
    const angleB = Math.atan2(b[1] - cY, b[0] - cX);
    return angleA - angleB;
  });

  reordered.push(reordered[0]);
  return { isSelfIntersecting: true, reorderedPoints: reordered };
}

/**
 * Rule 111: Spelled-Number Quantity Lexer.
 * Replaces spelled numbers adjacent to unit nouns before distance/radius parsing.
 */
export function replaceSpelledNumbers(text: string): { cleanText: string; replaced: boolean } {
  const dictionary: Record<string, string> = {
    HALF: '0.5',
    ONE: '1',
    TWO: '2',
    THREE: '3',
    FOUR: '4',
    FIVE: '5',
    SIX: '6',
    SEVEN: '7',
    EIGHT: '8',
    NINE: '9',
    TEN: '10',
    ELEVEN: '11',
    TWELVE: '12',
    THIRTEEN: '13',
    FOURTEEN: '14',
    FIFTEEN: '15',
    SIXTEEN: '16',
    SEVENTEEN: '17',
    EIGHTEEN: '18',
    NINETEEN: '19',
    TWENTY: '20',
    COUPLE: '2'
  };

  const unitsRegex = /\b(HALF|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY|COUPLE)\s+(MILES?|NM|NAUTICAL\s+MILES?|CABLES?|BERTHS?|KNOTS?|YARDS?|METERS?|METRES?|MTR|SHACKLES?)\b/gi;

  let replaced = false;
  const cleanText = text.replace(unitsRegex, (fullMatch, word, unit) => {
    const upperWord = word.toUpperCase();
    if (dictionary[upperWord]) {
      replaced = true;
      return `${dictionary[upperWord]} ${unit}`;
    }
    return fullMatch;
  });

  return { cleanText, replaced };
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

    const normX = -dy / len;
    const normY = (dx * cosLat) / len;

    const offLat = (normY * halfWidth) / 60;
    const offLon = (normX * halfWidth) / (60 * cosLat);

    leftSide.push([points[i][0] + offLon, points[i][1] + offLat]);
    rightSide.unshift([points[i][0] - offLon, points[i][1] - offLat]);
  }

  const corridor = [...leftSide, ...rightSide];
  if (corridor.length > 0) {
    corridor.push(corridor[0]);
  }
  return corridor;
}

/**
 * Extract navigational coordinates and spatial features from text (Rules 1-125).
 */
export function parseCoordinates(rawText: string): ParsedCoordinatesResult {
  const qaFlags: string[] = [];
  let dataQuality: 'EXPLICIT' | 'INFERRED' | 'AMBIGUOUS' | 'INVALID' = 'EXPLICIT';

  // Rule 111: Spelled number lexer
  const { cleanText, replaced: spelledReplaced } = replaceSpelledNumbers(rawText);
  if (spelledReplaced) {
    qaFlags.push('SPELLED_QUANTITY_NORMALIZED');
    dataQuality = 'INFERRED';
  }

  // Regex pattern matching WGS84 coordinates
  const pattern = /(?:(\d{1,3})[°\s-](\d{1,2}(?:\.\d+)?)[′']?(?:[°\s-](\d{1,2}(?:\.\d+)?)[″"])?\s*([NS]?))[\s,]+(?:(\d{1,3})[°\s-](\d{1,2}(?:\.\d+)?)[′']?(?:[°\s-](\d{1,2}(?:\.\d+)?)[″"])?\s*([EW]?))/gi;
  const parsedCoords: string[] = [];
  const points: [number, number][] = [];

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(cleanText)) !== null) {
    const latDeg = match[1];
    const latMin = match[2];
    const latSec = match[3];
    const latDir = (match[4] || '').toUpperCase();

    const lonDeg = match[5];
    const lonMin = match[6];
    const lonSec = match[7];
    const lonDir = (match[8] || '').toUpperCase();

    // Check for missing hemisphere (Rule 17)
    if (!latDir || !lonDir) {
      qaFlags.push('MISSING_HEMISPHERE');
      dataQuality = 'AMBIGUOUS';
      continue;
    }

    const lat = convertToDecimal(latDeg, latMin, latSec, latDir);
    const lon = convertToDecimal(lonDeg, lonMin, lonSec, lonDir);

    if (isNaN(lat) || isNaN(lon)) {
      qaFlags.push('COORDINATES_OUT_OF_RANGE');
      dataQuality = 'INVALID';
      continue;
    }

    points.push([lon, lat]);

    let latStr = `${latDeg}-${latMin}`;
    if (latSec) latStr += `-${latSec}`;
    latStr += latDir;

    let lonStr = `${lonDeg}-${lonMin}`;
    if (lonSec) lonStr += `-${lonSec}`;
    lonStr += lonDir;

    parsedCoords.push(`${latStr} ${lonStr}`);
  }

  // Rule 109: Bounding Box Synthesis (BOUNDED WITHIN lat1 TO lat2 AND lon1 TO lon2)
  if (points.length === 0) {
    const bboxMatch = cleanText.match(/BOUND(?:ED)?\s+(?:WITHIN\s+|BY\s+)(\d{1,2}(?:\.\d+)?)\s*([NS])\s+TO\s+(\d{1,2}(?:\.\d+)?)\s*([NS])\s+AND\s+(\d{1,3}(?:\.\d+)?)\s*([EW])\s+TO\s+(\d{1,3}(?:\.\d+)?)\s*([EW])/i);
    if (bboxMatch) {
      const lat1 = convertToDecimal(bboxMatch[1], 0, 0, bboxMatch[2]);
      const lat2 = convertToDecimal(bboxMatch[3], 0, 0, bboxMatch[4]);
      const lon1 = convertToDecimal(bboxMatch[5], 0, 0, bboxMatch[6]);
      const lon2 = convertToDecimal(bboxMatch[7], 0, 0, bboxMatch[8]);

      if (!isNaN(lat1) && !isNaN(lat2) && !isNaN(lon1) && !isNaN(lon2)) {
        points.push([lon1, lat1], [lon2, lat1], [lon2, lat2], [lon1, lat2], [lon1, lat1]);
        qaFlags.push('POLYGON_BOUNDING_BOX_SYNTHESIZED');
        dataQuality = 'INFERRED';
      }
    }
  }

  let spatial: GeoJsonGeometry | null = null;
  let primaryLat: number | null = null;
  let primaryLon: number | null = null;
  const circles: SpatialCircle[] = [];
  const corridors: SpatialCorridor[] = [];
  const driftVectors: DriftVector[] = [];
  let unplottedReason: string | null = null;

  if (points.length === 0) {
    unplottedReason = qaFlags.includes('MISSING_HEMISPHERE')
      ? 'missing_hemisphere'
      : 'no_coordinates';
  }

  // Parse radius and safety clearances
  const radiusMatch =
    cleanText.match(/radius\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:nm|nautical\s+miles?)/i) ||
    cleanText.match(/within\s+(\d+(?:\.\d+)?)\s*(?:nm|nautical\s+miles?)/i);
  const metersMatch =
    cleanText.match(/safety\s+zone\s+(?:of\s+)?(\d+)\s*(?:m|mtr|metres?|meters?)/i) ||
    cleanText.match(/(\d+)\s*(?:mtr|metres?|meters?)\s+clearance/i);
  const clearanceMatch = cleanText.match(/(\d+(?:\.\d+)?)\s*m\s+clearance/i);
  const wideBerthMatch = cleanText.match(/wide\s+berth\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:nm|nautical\s+miles?|miles?)/i);
  const vicinityMatch = cleanText.match(/in\s+vicinity\s+of\s+line\s+joining/i);

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
  } else if (vicinityMatch && points.length >= 2) {
    clearanceRadiusNm = 1.0; // Rule 74 / Section 4.1 default 1.0 NM corridor
    clearanceLabel = 'Vicinity Corridor (1.0 NM default)';
    qaFlags.push('CORRIDOR_DEFAULT_NOT_STATED');
    dataQuality = 'INFERRED';
  }

  // Parse drift directions
  const driftMatch = cleanText.match(/drifting\s+(eastward|westward|northward|southward|northeast|northwest|southeast|southwest|east|west|north|south)/i);
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

    // Check for self-intersecting bowtie polygon (Rule 25)
    const { isSelfIntersecting, reorderedPoints } = checkSelfIntersectingPolygon(points);
    if (isSelfIntersecting) {
      qaFlags.push('SELF_INTERSECTING_POLYGON');
      qaFlags.push('BOWTIE_POLYGON_REORDERED');
      dataQuality = 'INVALID';

      spatial = {
        type: 'Polygon',
        coordinates: [reorderedPoints]
      };
    } else {
      const isClosed =
        points[0][0] === points[points.length - 1][0] &&
        points[0][1] === points[points.length - 1][1];
      const closedPoints = isClosed ? points : [...points, points[0]];

      spatial = {
        type: 'Polygon',
        coordinates: [closedPoints]
      };
    }

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
    driftVectors,
    qaFlags,
    dataQuality,
    unplottedReason
  };
}

/**
 * Format coordinates as a standard display string.
 * Depth sentinel -9999.0 is masked in display.
 */
export function formatCoordinateString(lat: number, lon: number): string {
  if (isNaN(lat) || isNaN(lon)) return 'N/A';
  if (lat === -9999 || lon === -9999) return 'depth unknown';

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
