/**
 * Common utilities for Helm Navigational Warning System
 * Matches shared/utils.py
 */

export function cleanText(text: string): string {
  if (!text) return '';

  let cleaned = text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\xa0/g, ' ')
    .replace(/\u2028/g, '\n')
    .replace(/\u2029/g, '\n');

  // Collapse whitespaces
  return cleaned.replace(/\s+/g, ' ').trim();
}

/**
 * Fast synchronous SHA-256 implementation using pure TypeScript.
 * Produces standard hex string matching hashlib.sha256(text.encode('utf-8')).hexdigest()
 */
export function calculateSha256(str: string): string {
  function rightRotate(value: number, amount: number) {
    return (value >>> amount) | (value << (32 - amount));
  }

  const mathPow = Math.pow;
  const maxWord = mathPow(2, 32);
  let lengthProperty = 'length';
  let i: number, j: number;
  let result = '';

  const words: number[] = [];
  const asciiBitLength = str.length * 8;

  const hash: number[] = [];
  const k: number[] = [];
  let primeCounter = 0;

  const isComposite: Record<number, boolean> = {};
  for (let candidate = 2; primeCounter < 64; candidate++) {
    if (!isComposite[candidate]) {
      for (i = 0; i < 313; i += candidate) {
        isComposite[i] = true;
      }
      hash[primeCounter] = (mathPow(candidate, 0.5) * maxWord) | 0;
      k[primeCounter++] = (mathPow(candidate, 1 / 3) * maxWord) | 0;
    }
  }

  str += '\x80';
  while ((str.length % 64) - 56) str += '\x00';
  for (i = 0; i < str.length; i++) {
    j = str.charCodeAt(i);
    if (j >> 8) return ''; // non-ascii check fallback
    words[i >> 2] |= j << (((3 - i) % 4) * 8);
  }
  words[words.length] = (asciiBitLength / maxWord) | 0;
  words[words.length] = asciiBitLength;

  for (j = 0; j < words.length; ) {
    const w = words.slice(j, (j += 16));
    const oldHash = hash.slice(0);

    for (i = 0; i < 64; i++) {
      const w15 = w[i - 15],
        w2 = w[i - 2];

      const s0 = rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3);
      const s1 = rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10);
      w[i] =
        i < 16
          ? w[i]
          : ((w[i - 16] + s0 + w[i - 7] + s1) | 0);

      const ch = (hash[4] & hash[5]) ^ (~hash[4] & hash[6]);
      const maj = (hash[0] & hash[1]) ^ (hash[0] & hash[2]) ^ (hash[1] & hash[2]);
      const temp1 = (hash[7] + (rightRotate(hash[4], 6) ^ rightRotate(hash[4], 11) ^ rightRotate(hash[4], 25)) + ch + k[i] + (w[i] | 0)) | 0;
      const temp2 = ((rightRotate(hash[0], 2) ^ rightRotate(hash[0], 13) ^ rightRotate(hash[0], 22)) + maj) | 0;

      hash[7] = hash[6];
      hash[6] = hash[5];
      hash[5] = hash[4];
      hash[4] = (hash[3] + temp1) | 0;
      hash[3] = hash[2];
      hash[2] = hash[1];
      hash[1] = hash[0];
      hash[0] = (temp1 + temp2) | 0;
    }

    for (i = 0; i < 8; i++) {
      hash[i] = (hash[i] + oldHash[i]) | 0;
    }
  }

  for (i = 0; i < 8; i++) {
    for (j = 3; j >= 0; j--) {
      const b = (hash[i] >> (8 * j)) & 255;
      result += (b < 16 ? '0' : '') + b.toString(16);
    }
  }
  return result;
}

const MONTH_MAP: Record<string, string> = {
  JAN: '01',
  FEB: '02',
  MAR: '03',
  APR: '04',
  MAY: '05',
  JUN: '06',
  JUL: '07',
  AUG: '08',
  SEP: '09',
  OCT: '10',
  NOV: '11',
  DEC: '12'
};

/**
 * Parses maritime DTG (Date-Time Group) broadcast string into YYYY-MM-DD.
 * e.g. "100600 UTC OCT 2026" -> "2026-10-10"
 */
export function parseMaritimeIssuedDate(text: string | null | undefined): string | null {
  if (!text) return null;

  const match = text.match(/(\d{2})\d{4}\s+UTC\s+([A-Z]{3})\s+(\d{4})/i);
  if (match) {
    const day = match[1];
    const month = MONTH_MAP[match[2].toUpperCase()] || '01';
    const year = match[3];
    return `${year}-${month}-${day}`;
  }

  const matchNoYear = text.match(/(\d{2})\d{4}\s+UTC\s+([A-Z]{3})/i);
  if (matchNoYear) {
    const day = matchNoYear[1];
    const month = MONTH_MAP[matchNoYear[2].toUpperCase()] || '01';
    const year = new Date().getFullYear();
    return `${year}-${month}-${day}`;
  }

  const isoMatch = text.match(/\b(\d{4}-\d{2}-\d{2})\b/);
  if (isoMatch) return isoMatch[1];

  return null;
}

/**
 * Extract cancellation directives from warning text per Rules Register R206.
 * Extracts superseded warning IDs and self-cancellation timestamp.
 */
export function extractCancellationDirectives(rawText: string): {
  cancelsIds: string[];
  selfCancelsAt: string | null;
} {
  const cancelsIds: string[] = [];
  let selfCancelsAt: string | null = null;

  if (!rawText) return { cancelsIds, selfCancelsAt };

  // Match: CANCEL 0450/26 or CANCEL NAVAREA I 512/26 or CANCEL SWEDISH 160/26
  const cancelPattern = /\bCANCEL\s+(?:THIS\s+MSG\b|([A-Z0-9_\-\s\/]+?\d+\/\d{2}))/gi;
  let match: RegExpExecArray | null;

  while ((match = cancelPattern.exec(rawText)) !== null) {
    if (match[1]) {
      const cleanId = match[1].trim().replace(/\.$/, '');
      if (cleanId && !cleanId.toUpperCase().includes('THIS MSG')) {
        cancelsIds.push(cleanId);
      }
    }
  }

  // Self-cancellation date
  const selfCancelMatch = rawText.match(/CANCEL\s+THIS\s+MSG(?:\s+AT)?\s+([0-9]{4,6}Z?\s+[A-Z]{3}(?:\s+\d{2,4})?)/i);
  if (selfCancelMatch) {
    selfCancelsAt = selfCancelMatch[1].trim();
  }

  return { cancelsIds, selfCancelsAt };
}

