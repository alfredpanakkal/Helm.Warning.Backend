import { RawMessage, NavWarning, GeoJsonGeometry, ParsedData } from '../../types/maritime';
import { parseCoordinates, validateNavareaBounds } from '../coordinates';
import { classifyHazard, determineSeverity } from '../classification';
import { calculateSha256, parseMaritimeIssuedDate, extractCancellationDirectives } from '../utils';

export const BALTIC_CONFIG = {
  SOURCE_ID: 'sma-baltic-subarea',
  NAVAREA_ID: 'Baltic',
  SOURCE_URL: 'https://navvarn.sjofartsverket.se/en/Navigationsvarningar/VHF',
  SCHEDULE: 'Every 6 hours',
  AUTHORITY: 'Swedish Maritime Administration (Sjöfartsverket)'
};

export function parseBalticWarning(
  rawBlock: string,
  referenceHeader: string
): {
  rawMessage: RawMessage;
  navWarning: NavWarning;
  spatial: GeoJsonGeometry | null;
} {
  const headerClean = referenceHeader.trim();
  const headerNoArea = headerClean.replace(/\s*\[.*?\]/g, '').trim();

  let warningId: string;
  if (headerNoArea.includes('BALTIC SEA NAV WARN')) {
    const num = headerNoArea.split('BALTIC SEA NAV WARN').pop()?.trim() || '';
    warningId = `BALTIC ${num}`;
  } else if (headerNoArea.includes('SWEDISH NAV WARN')) {
    const num = headerNoArea.split('SWEDISH NAV WARN').pop()?.trim() || '';
    warningId = `SWEDISH ${num}`;
  } else {
    warningId = headerNoArea;
  }

  const lines = rawBlock
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  const datePattern = /(\d{6}\s+UTC\s+[A-Z]{3})/i;
  let issuedText: string | null = null;
  let title = '';

  for (const line of lines) {
    const dMatch = line.match(datePattern);
    if (dMatch && !issuedText) {
      issuedText = dMatch[1];
    } else if (!title && !dMatch) {
      title = line;
    }
  }

  const yrMatch = warningId.match(/\/(\d{2})$/);
  if (yrMatch && issuedText && !/\b20\d{2}\b/.test(issuedText)) {
    const fullYear = `20${yrMatch[1]}`;
    issuedText = `${issuedText} ${fullYear}`;
  }

  const { parsedCoords, primaryLat, primaryLon, spatial, spatialBundle } = parseCoordinates(rawBlock);
  const hazard = classifyHazard(rawBlock);
  const severity = determineSeverity(hazard, rawBlock);
  const checksum = calculateSha256(rawBlock);
  const { cancelsIds, selfCancelsAt } = extractCancellationDirectives(rawBlock);

  const boundsCheck =
    primaryLat !== null && primaryLon !== null
      ? validateNavareaBounds(primaryLat, primaryLon, BALTIC_CONFIG.NAVAREA_ID)
      : { isValid: true };
  const verification = boundsCheck.isValid
    ? parsedCoords.length > 0 ? 'verified' : 'needs_review'
    : 'needs_review';

  const rawMessage: RawMessage = {
    warning_id: warningId,
    source_id: BALTIC_CONFIG.SOURCE_ID,
    subject_header: headerClean,
    full_raw_text: rawBlock,
    received_timestamp: new Date().toISOString(),
    checksum_sha256: checksum
  };

  const navWarning: NavWarning = {
    id: `baltic-${warningId.replace(/[^a-zA-Z0-9_-]/g, '_')}`,
    warning_id: warningId,
    publisher_id: BALTIC_CONFIG.AUTHORITY,
    source_id: BALTIC_CONFIG.SOURCE_ID,
    navarea: BALTIC_CONFIG.NAVAREA_ID,
    series: 'Baltic Sub-Area',
    source_warning_id: warningId,
    title: title || headerNoArea,
    issued_text: issuedText,
    issued_date: parseMaritimeIssuedDate(issuedText),
    coordinates: parsedCoords.length > 0 ? parsedCoords.join(', ') : null,
    latitude: primaryLat,
    longitude: primaryLon,
    category: hazard,
    severity: severity,
    status: 'active',
    raw_text: rawBlock,
    spatial: spatialBundle || spatial || undefined,
    is_verified: verification === 'verified',
    verification: verification,
    cancels_ids: cancelsIds.length > 0 ? cancelsIds : undefined,
    valid_to: selfCancelsAt || undefined,
    created_at: new Date().toISOString()
  };

  return { rawMessage, navWarning, spatial };
}

export function parseBalticContent(content: string): ParsedData {
  const pattern = /---\s*(.*?)\s*---\n([\s\S]*?)(?=\n---\s*|$)/g;
  const parsedData: ParsedData = {
    raw_messages: [],
    nav_warnings: [],
    spatial_features: []
  };

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(content)) !== null) {
    const header = match[1];
    const block = match[2];
    if (header && block.trim()) {
      const { rawMessage, navWarning, spatial } = parseBalticWarning(block.trim(), header.trim());
      parsedData.raw_messages.push(rawMessage);
      parsedData.nav_warnings.push(navWarning);
      if (spatial) {
        parsedData.spatial_features.push({
          warning_id: navWarning.warning_id,
          category: navWarning.category,
          geometry: spatial
        });
      }
    }
  }

  return parsedData;
}
