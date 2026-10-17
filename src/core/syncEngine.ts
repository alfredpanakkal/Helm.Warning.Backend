import { NavWarning, RawMessage, DifferentialResult } from '../types/maritime';

export interface ExistingWarningRecord {
  warning_id: string;
  status: string;
  raw_text?: string;
  source_id?: string;
}

export interface ExistingChecksumRecord {
  warning_id: string;
  checksum_sha256: string;
}

/**
 * Compute differential actions between scraped data and current database state.
 * Direct translation of shared/sync.py compute_differential.
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

  const toSkip: string[] = [];
  const toInsertNew: Array<{ warn: NavWarning; msg: RawMessage }> = [];
  const toUpdate: Array<{ warn: NavWarning; msg: RawMessage }> = [];
  const seenIds = new Set<string>();

  for (const warn of scrapedWarnings) {
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
  for (const warn of scrapedWarnings) {
    if (warn.cancels_ids && Array.isArray(warn.cancels_ids)) {
      for (const cid of warn.cancels_ids) {
        explicitCancels.add(cid.trim().toLowerCase());
      }
    }
  }

  const toCancel: string[] = [];
  for (const [wid, record] of Object.entries(existingWarnings)) {
    if (record.status === 'active') {
      const isAbsent = !seenIds.has(wid);
      const isExplicitlyCancelled =
        explicitCancels.has(wid.toLowerCase()) ||
        Array.from(explicitCancels).some((c) => wid.toLowerCase().endsWith(c));

      if (isAbsent || isExplicitlyCancelled) {
        toCancel.push(wid);
      }
    }
  }

  return {
    skip: toSkip,
    new: toInsertNew,
    update: toUpdate,
    cancel: toCancel
  };
}
