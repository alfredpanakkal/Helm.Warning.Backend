import { RawMessage, NavWarning, GeoJsonGeometry, ParsedData } from '../../types/maritime';
import { parseCoordinates, validateNavareaBounds } from '../coordinates';
import { classifyHazard, determineSeverity } from '../classification';
import { calculateSha256, parseMaritimeIssuedDate, extractCancellationDirectives } from '../utils';

export const NAVAREA_1_CONFIG = {
  SOURCE_ID: 'ukho-navarea-1',
  NAVAREA_ID: 'NA I',
  SOURCE_URL: 'https://msi.admiralty.co.uk/RadioNavigationalWarnings',
  SCHEDULE: 'Every 6 hours',
  AUTHORITY: 'UK Hydrographic Office (UKHO) Admiralty'
};

export function parseNavarea1Warning(
  rawBlock: string,
  referenceHeader: string
): {
  rawMessage: RawMessage;
  navWarning: NavWarning;
  spatial: GeoJsonGeometry | null;
} {
  const warningId = referenceHeader.includes('NAVAREA I ')
    ? referenceHeader.split('NAVAREA I ').pop()?.trim() || referenceHeader
    : referenceHeader.trim();

  const lines = rawBlock
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  const title = lines[0] || '';

  const { parsedCoords, primaryLat, primaryLon, spatial, spatialBundle } = parseCoordinates(rawBlock);

  const datePattern = /(\d{6}\s+UTC\s+[A-Z]{3}\s+\d{4})/i;
  const dateMatch = title.match(datePattern) || rawBlock.match(datePattern);
  const issuedText = dateMatch ? dateMatch[1] : null;

  const hazard = classifyHazard(rawBlock);
  const severity = determineSeverity(hazard, rawBlock);
  const checksum = calculateSha256(rawBlock);
  const { cancelsIds, selfCancelsAt } = extractCancellationDirectives(rawBlock);

  const boundsCheck =
    primaryLat !== null && primaryLon !== null
      ? validateNavareaBounds(primaryLat, primaryLon, NAVAREA_1_CONFIG.NAVAREA_ID)
      : { isValid: true };
  const verification = boundsCheck.isValid
    ? parsedCoords.length > 0 ? 'verified' : 'needs_review'
    : 'needs_review';

  const rawMessage: RawMessage = {
    warning_id: warningId,
    source_id: NAVAREA_1_CONFIG.SOURCE_ID,
    subject_header: referenceHeader.trim(),
    full_raw_text: rawBlock,
    received_timestamp: new Date().toISOString(),
    checksum_sha256: checksum
  };

  const navWarning: NavWarning = {
    id: `nav1-${warningId.replace(/[^a-zA-Z0-9_-]/g, '_')}`,
    warning_id: warningId,
    publisher_id: NAVAREA_1_CONFIG.AUTHORITY,
    source_id: NAVAREA_1_CONFIG.SOURCE_ID,
    navarea: NAVAREA_1_CONFIG.NAVAREA_ID,
    series: 'NAVAREA I',
    source_warning_id: warningId,
    title: title,
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

export function parseNavarea1Content(content: string): ParsedData {
  const pattern = /---\s*(NAVAREA\s+I\s+.*?)\s*---\n([\s\S]*?)(?=\n---\s*NAVAREA\s+I|$)/gi;
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
      const { rawMessage, navWarning, spatial } = parseNavarea1Warning(block.trim(), header.trim());
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
