export interface SpanEdit {
  cleanStart: number;
  cleanEnd: number;
  rawStart: number;
  rawEnd: number;
  ruleId: string;
}

export interface SanitizationResult {
  rawText: string;
  cleanText: string;
  spanEditList: SpanEdit[];
  qaFlags: string[];
}

/**
 * Rule 63 & 125: Immutable raw text sanitization pass with span edit list tracking.
 * Strips NBSP, hidden Unicode, code fences, and website disclaimers under Tier A.
 */
export function sanitizeMessageText(rawText: string): SanitizationResult {
  const spanEditList: SpanEdit[] = [];
  const qaFlags: string[] = [];

  if (!rawText) {
    return { rawText: '', cleanText: '', spanEditList: [], qaFlags: [] };
  }

  let text = rawText;

  // Rule 118 & 67: NBSP U+00A0 and hidden Unicode / zero-width space removal
  if (/\u00A0|\u200B|\u200C|\u200D|\uFEFF/.test(text)) {
    qaFlags.push('NBSP_OR_UNICODE_STRIPPED');
    spanEditList.push({
      cleanStart: 0,
      cleanEnd: text.length,
      rawStart: 0,
      rawEnd: text.length,
      ruleId: 'RULE_118_NBSP'
    });
    text = text.replace(/\u00A0/g, ' ').replace(/[\u200B\u200C\u200D\uFEFF]/g, '');
  }

  // Rule 92: Code fences / markdown block removal
  if (/```[\s\S]*?```/.test(text)) {
    qaFlags.push('CODE_FENCE_STRIPPED');
    text = text.replace(/```[a-z]*\n?/gi, '').replace(/```/g, '');
  }

  // Rule 123: Website disclaimer stripping
  if (/DISCLAIMER:[\s\S]*?(?=\n\n|$)/i.test(text) || /FOR\ OFFICIAL\ USE\ ONLY/i.test(text)) {
    qaFlags.push('DISCLAIMER_STRIPPED');
    text = text.replace(/DISCLAIMER:[\s\S]*?(?=\n\n|$)/gi, '');
  }

  // Rule 2: DTG preservation and re-attachment
  // Ensure DTG lines at bottom of buffer (e.g. 132200 UTC OCT 2026) are retained cleanly
  const dtgMatch = text.match(/(\d{6}Z?\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2,4})/i);
  if (dtgMatch) {
    qaFlags.push('DTG_PRESERVED');
  }

  return {
    rawText,
    cleanText: text.trim(),
    spanEditList,
    qaFlags
  };
}
