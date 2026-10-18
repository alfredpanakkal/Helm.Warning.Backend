import { NavWarning, RawMessage, DifferentialResult } from '../types/maritime';

export interface ExistingWarningRecord {
  warning_id: string;
  status: string;
  raw_text?: string;
  source_id?: string;
  title?: string;
  category?: string;
  navarea?: string;
}

export interface ExistingChecksumRecord {
  warning_id: string;
  checksum_sha256: string;
}

/**
 * SubjectSignature helper for supersession resolution (Section 4.2).
 * Navarea + Category + Region tokens.
 */
export function computeSubjectSignature(warn: NavWarning): string {
  const nav = (warn.navarea || '').toUpperCase();
  const cat = (warn.category || 'general').toUpperCase();
  const titleTokens = (warn.title || '').toUpperCase().split(/\s+/).slice(0, 3).join('_');
  return `${nav}::${cat}::${titleTokens}`;
}

/**
 * Compute differential actions and resolve chronological lifecycle (Milestone 3 / Section 4.2).
 */
export function computeDifferential(
  scrapedWarnings: NavWarning[],
  scrapedMessages: RawMessage[],
  existingWarnings: Record<string, ExistingWarningRecord>,
  existingChecksums: Set<string> // Set of "warning_id:::checksum_sha256"
): DifferentialResult {
  const msgMap = new Map<string, RawMessage>();
  for (const m of scrapedMessages) {
    msgMap.set(m.warning_id, m);
  }

  // Sort warnings chronologically by issued date / timestamp
  const sortedScraped = [...scrapedWarnings].sort((a, b) => {
    const timeA = new Date(a.issued_date || a.created_at || '1970-01-01').getTime();
    const timeB = new Date(b.issued_date || b.created_at || '1970-01-01').getTime();
    return timeA - timeB;
  });

  const toSkip: string[] = [];
  const toInsertNew: Array<{ warn: NavWarning; msg: RawMessage }> = [];
  const toUpdate: Array<{ warn: NavWarning; msg: RawMessage }> = [];
  const seenIds = new Set<string>();

  for (const warn of sortedScraped) {
    const wid = warn.warning_id;
    seenIds.add(wid);

    const rawMsg: RawMessage = msgMap.get(wid) || {
      warning_id: wid,
      source_id: warn.source_id,
      subject_header: warn.title || wid,
      full_raw_text: warn.raw_text,
      received_timestamp: new Date().toISOString(),
      checksum_sha256: ''
    };

    const chk = rawMsg.checksum_sha256;
    const existingRecord = existingWarnings[wid];

    if (existingRecord) {
      const isActive = existingRecord.status === 'active';
      const checksumMatches = existingChecksums.has(`${wid}:::${chk}`);

      if (isActive && checksumMatches) {
        toSkip.push(wid);
      } else {
        toUpdate.push({ warn, msg: rawMsg });
      }
    } else {
      toInsertNew.push({ warn, msg: rawMsg });
    }
  }

  const explicitCancels = new Set<string>();
  const proposedCancels = new Set<string>();

  for (const warn of sortedScraped) {
    if (warn.cancels_ids && Array.isArray(warn.cancels_ids)) {
      for (const cid of warn.cancels_ids) {
        const cleanCid = cid.trim().toLowerCase();
        // If cancellation is derived from inferred/repaired year or Rule 105, set proposed_cancel
        if (warn.qa_flags?.includes('CANCELLATION_YEAR_INHERITED') || warn.triage_tier === 'B') {
          proposedCancels.add(cleanCid);
          warn.proposed_cancel = true;
          warn.resolutionRule = 'RULE_105_PROPOSED_CANCEL';
        } else {
          explicitCancels.add(cleanCid);
          warn.resolutionRule = 'CROSS_CANCEL_EXPLICIT';
        }
      }
    }
  }

  const toCancel: string[] = [];
  // Hoist the list out of the per-warning loop and require suffix candidates
  // to be structured warning references (contain a "/"), preventing short or
  // numeric-only cancel IDs from matching unrelated warnings.
  const explicitCancelList = Array.from(explicitCancels);
  for (const [wid, record] of Object.entries(existingWarnings)) {
    if (record.status !== 'active') continue;
    const widLower = wid.toLowerCase();
    const isExplicitlyCancelled =
      explicitCancels.has(widLower) ||
      explicitCancelList.some((c) => c.includes('/') && widLower.endsWith(c));

    // Rule 105 / Inferred proposals do NOT auto-cancel live public warnings
    if (isExplicitlyCancelled) {
      toCancel.push(wid);
    }
  }

  return {
    skip: toSkip,
    new: toInsertNew,
    update: toUpdate,
    cancel: toCancel
  };
}
