import { RawMessage, NavWarning, GeoJsonGeometry, ParsedData } from '../../types/maritime';
import { parseCoordinates, validateNavareaBounds } from '../coordinates';
import { classifyHazard, determineSeverity } from '../classification';
import { calculateSha256, parseMaritimeIssuedDate, extractCancellationDirectives } from '../utils';

export const NAVAREA_XI_CONFIG = {
  SOURCE_ID: 'kaiho-navarea-xi',
  NAVAREA_ID: 'NA XI',
  SOURCE_URL: 'https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/disp_warnings.cgi',
  SCHEDULE: 'Every 6 hours',
  AUTHORITY: 'Japan Coast Guard (JCG Kaiho)'
};

export function parseNavareaXiWarning(
  rawBlock: string,
  referenceHeader: string
): {
  rawMessage: RawMessage;
  navWarning: NavWarning;
  spatial: GeoJsonGeometry | null;
} {
  const headerClean = referenceHeader.trim();

  const idMatch = headerClean.match(/NO\.(\d{2})-(\d{4})/i);
  let warningId: string;
  if (idMatch) {
    const yrShort = idMatch[1];
    const num = idMatch[2];
    warningId = `NAVAREA XI ${num}/${yrShort}`;
  } else {
    warningId = headerClean.replace(/NAVAREA\s+XI\s+/i, '').trim();
  }

  const lines = rawBlock
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  const datePattern = /Date:(\d{4}\/\d{2}\/\d{2}\s+\d{2}\s+UTC)/i;
  let issuedText: string | null = null;
  let title = '';

  for (const line of lines) {
    const dMatch = line.match(datePattern);
    if (dMatch && !issuedText) {
      issuedText = dMatch[1];
    } else if (!title && !dMatch && !line.includes('NO.')) {
      title = line;
    }
  }

  const { parsedCoords, primaryLat, primaryLon, spatial, spatialBundle } = parseCoordinates(rawBlock);
  const hazard = classifyHazard(rawBlock);
  const severity = determineSeverity(hazard, rawBlock);
  const checksum = calculateSha256(rawBlock);
  const { cancelsIds, selfCancelsAt } = extractCancellationDirectives(rawBlock);

  const boundsCheck =
    primaryLat !== null && primaryLon !== null
      ? validateNavareaBounds(primaryLat, primaryLon, NAVAREA_XI_CONFIG.NAVAREA_ID)
      : { isValid: true };
  const verification = boundsCheck.isValid
    ? parsedCoords.length > 0 ? 'verified' : 'needs_review'
    : 'needs_review';

  const rawMessage: RawMessage = {
    warning_id: warningId,
    source_id: NAVAREA_XI_CONFIG.SOURCE_ID,
    subject_header: headerClean,
    full_raw_text: rawBlock,
    received_timestamp: new Date().toISOString(),
    checksum_sha256: checksum
  };

  const navWarning: NavWarning = {
    id: `nav11-${warningId.replace(/[^a-zA-Z0-9_-]/g, '_')}`,
    warning_id: warningId,
    publisher_id: NAVAREA_XI_CONFIG.AUTHORITY,
    source_id: NAVAREA_XI_CONFIG.SOURCE_ID,
    navarea: NAVAREA_XI_CONFIG.NAVAREA_ID,
    series: 'NAVAREA XI',
    source_warning_id: warningId,
    title: title || headerClean,
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

export function parseNavareaXiContent(content: string): ParsedData {
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
      const { rawMessage, navWarning, spatial } = parseNavareaXiWarning(block.trim(), header.trim());
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
