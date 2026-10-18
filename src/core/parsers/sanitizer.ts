/**
 * sanitizer.ts — Message Text Sanitization Utilities
 */

export interface SanitizedOutput {
  cleanText: string;
  spanEditList: Array<{ original: string; replacement: string; reason: string }>;
  qaFlags: string[];
}

export function sanitizeMessageText(rawText: string): SanitizedOutput {
  if (!rawText) {
    return {
      cleanText: '',
      spanEditList: [],
      qaFlags: ['EMPTY_INPUT']
    };
  }

  const spanEditList: Array<{ original: string; replacement: string; reason: string }> = [];
  const qaFlags: string[] = [];

  let cleanText = rawText
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\xa0/g, ' ')
    .trim();

  // Basic whitespace normalization
  const normalized = cleanText.replace(/[ \t]+/g, ' ');
  if (normalized !== cleanText) {
    spanEditList.push({
      original: cleanText,
      replacement: normalized,
      reason: 'WHITESPACE_NORMALIZATION'
    });
    cleanText = normalized;
  }

  return {
    cleanText,
    spanEditList,
    qaFlags
  };
}
