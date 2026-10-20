import { RawMessage, NavWarning, GeoJsonGeometry, ParsedData } from '../../types/maritime';
import { parseCoordinates, validateNavareaBounds } from '../coordinates';
import { classifyHazard, classifyHazardCategories, determineSeverity } from '../classification';
import { calculateSha256, parseMaritimeIssuedDate, extractCancellationDirectives } from '../utils';
import { sanitizeMessageText } from './sanitizer';

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
  const { cleanText, spanEditList, qaFlags: sanitizeFlags } = sanitizeMessageText(rawBlock);
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

  const lines = cleanText
    .split('\n')
    .map((l: string) => l.trim())
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

  const {
    parsedCoords,
    primaryLat,
    primaryLon,
    spatial,
    spatialBundle,
    qaFlags: coordFlags,
    dataQuality: coordQuality,
    unplottedReason
  } = parseCoordinates(cleanText);

  const allQaFlags = Array.from(new Set([...sanitizeFlags, ...coordFlags]));
  const categories = classifyHazardCategories(cleanText);
  const hazard = categories[0] || 'general';
  const severity = determineSeverity(hazard, cleanText);
  const checksum = calculateSha256(rawBlock);
  const { cancelsIds, selfCancelsAt } = extractCancellationDirectives(cleanText);
  const canonicalId = `NAVAREA XI ${warningId}`;

  const boundsCheck =
    primaryLat !== null && primaryLon !== null
      ? validateNavareaBounds(primaryLat, primaryLon, NAVAREA_XI_CONFIG.NAVAREA_ID)
      : { isValid: true };

  let triageTier: 'A' | 'B' | 'C' = 'A';
  if (allQaFlags.includes('MISSING_HEMISPHERE') || allQaFlags.includes('COORDINATES_OUT_OF_RANGE') || !boundsCheck.isValid) {
    triageTier = 'C';
  } else if (
    coordQuality === 'INFERRED' ||
    allQaFlags.includes('POLYGON_BOUNDING_BOX_SYNTHESIZED') ||
    allQaFlags.includes('BOWTIE_POLYGON_REORDERED') ||
    allQaFlags.includes('SPELLED_QUANTITY_NORMALIZED')
  ) {
    triageTier = 'B';
  }

  const verification = boundsCheck.isValid && triageTier !== 'C'
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
    canonical_id: canonicalId,
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
    categories: categories,
    severity: severity,
    status: 'active',
    data_quality: coordQuality,
    verification_status: verification === 'verified' ? 'human_verified' : 'unverified',
    triage_tier: triageTier,
    qa_flags: allQaFlags,
    unplottedReason: unplottedReason as any,
    spanEditList: spanEditList as any,
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
