import { RawMessage, NavWarning, GeoJsonGeometry, ParsedData } from '../../types/maritime';
import { parseCoordinates } from '../coordinates';
import { classifyHazard } from '../classification';
import { calculateSha256 } from '../utils';

export const NAVAREA_1_CONFIG = {
  SOURCE_ID: 'ukho-navarea-1',
  NAVAREA_ID: 'I',
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

  const { parsedCoords, primaryLat, primaryLon, spatial } = parseCoordinates(rawBlock);

  const datePattern = /(\d{6}\s+UTC\s+[A-Z]{3}\s+\d{4})/i;
  const dateMatch = title.match(datePattern) || rawBlock.match(datePattern);
  const issuedText = dateMatch ? dateMatch[1] : null;

  const hazard = classifyHazard(rawBlock);
  const checksum = calculateSha256(rawBlock);

  const rawMessage: RawMessage = {
    warning_id: warningId,
    source_id: NAVAREA_1_CONFIG.SOURCE_ID,
    subject_header: referenceHeader.trim(),
    full_raw_text: rawBlock,
    received_timestamp: new Date().toISOString(),
    checksum_sha256: checksum
  };

  const navWarning: NavWarning = {
    warning_id: warningId,
    source_id: NAVAREA_1_CONFIG.SOURCE_ID,
    navarea: NAVAREA_1_CONFIG.NAVAREA_ID,
    title: title,
    issued_text: issuedText,
    coordinates: parsedCoords.length > 0 ? parsedCoords.join(', ') : null,
    latitude: primaryLat,
    longitude: primaryLon,
    category: hazard,
    status: 'active',
    raw_text: rawBlock,
    spatial: spatial || undefined
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
