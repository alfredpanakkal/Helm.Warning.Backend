export interface SplitMessageResult {
  header: string;
  body: string;
  rawFragment: string;
  isDuplicate: boolean;
  duplicateOfId?: string;
  navareaCode: string;
  serialYearKey: string;
}

export interface SplitterBatchResult {
  messages: SplitMessageResult[];
  rawHeaderCount: number;
  splitCount: number;
  countMismatchWarning: boolean;
  qaFlags: string[];
}

/**
 * Rule 106: Dual-Criteria Coordinator Splitter and Segmentation Engine.
 * Supports NAVAREA I, II, III, IV, V, VII, IX, X, XVI with independent header counting.
 */
export function splitCoordinatorBulletins(bulletinText: string): SplitterBatchResult {
  const qaFlags: string[] = [];

  if (!bulletinText || !bulletinText.trim()) {
    return {
      messages: [],
      rawHeaderCount: 0,
      splitCount: 0,
      countMismatchWarning: false,
      qaFlags: ['EMPTY_BULLETIN']
    };
  }

  // Independent Header Counting with whitespace tolerance
  const headerCountRegex = /(?:NAVAREA|NAV|BALTIC|HYDRO|ARGENTINE)\s*(?:[I|V|X]+|\d{1,2}|-[0-9]+-)?\s*\d{1,4}\s*[\/\-]\s*\d{2,4}/gi;
  const rawHeadersFound = bulletinText.match(headerCountRegex) || [];
  const rawHeaderCount = rawHeadersFound.length;

  // Regional Splitter Regexes (Rule 106)
  // Region I & II: ^\s*NAVAREA (I|II) \d+/\d{2,4}
  // Region V: bare serial line \d{3,4}/\d{2}
  // Region VI / Argentine: ^NAVAREA\s*-\s*(\d{3,4})-(\d{4})
  // Region IX & IV: split before ^(?:DTG-line\n)?NAVAREA (IX|IV) \d+/\d+
  const splitRegex = /(?=(?:(?:^\s*|\n\s*)(?:NAVAREA|NAV|BALTIC)\s+(?:[I|V|X]+|\d{1,2})\s+\d{1,4}\/\d{2,4}|^\s*NAVAREA\s*-\s*\d{3,4}-\d{4}|^\s*\d{3,4}\/\d{2}\s*$))/gi;

  const rawBlocks = bulletinText.split(splitRegex).map((b) => b.trim()).filter(Boolean);

  const seenBodies = new Map<string, string>(); // body hash -> header ID
  const messages: SplitMessageResult[] = [];

  rawBlocks.forEach((block) => {
    const lines = block.split('\n');
    const header = lines[0]?.trim() || 'UNHEADERED_WARNING';
    const body = lines.slice(1).join('\n').trim();

    // Extract Navarea code and serial/year
    const navareaMatch = header.match(/(NAVAREA\s+[I|V|X\d]+|BALTIC|NAV\s+[I|V|X\d]+)/i);
    const serialMatch = header.match(/(\d{1,4})[\/\-](\d{2,4})/);

    const navareaCode = navareaMatch ? navareaMatch[1].toUpperCase() : 'UNKNOWN';
    const serialYearKey = serialMatch ? `${serialMatch[1]}/${serialMatch[2]}` : `${Date.now()}`;

    // Body duplicate check
    const bodyHash = body.replace(/\s+/g, '').toLowerCase();
    let isDuplicate = false;
    let duplicateOfId: string | undefined;

    if (bodyHash && seenBodies.has(bodyHash)) {
      isDuplicate = true;
      duplicateOfId = seenBodies.get(bodyHash);
      qaFlags.push('DUPLICATE_BODY_DETECTED');
    } else if (bodyHash) {
      seenBodies.set(bodyHash, header);
    }

    messages.push({
      header,
      body,
      rawFragment: block,
      isDuplicate,
      duplicateOfId,
      navareaCode,
      serialYearKey
    });
  });

  const splitCount = messages.length;
  const countMismatchWarning = rawHeaderCount > 0 && Math.abs(rawHeaderCount - splitCount) > 0;

  if (countMismatchWarning) {
    qaFlags.push('SPLITTER_COUNT_MISMATCH_WARN');
  }

  return {
    messages,
    rawHeaderCount,
    splitCount,
    countMismatchWarning,
    qaFlags
  };
}
