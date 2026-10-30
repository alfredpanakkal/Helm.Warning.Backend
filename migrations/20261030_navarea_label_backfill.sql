-- ============================================================================
-- ONE-TIME DATA BACKFILL (audit finding F3) - navarea column labels
-- Migration: 20261030_navarea_label_backfill.sql
--
-- Apply AFTER merging PR #69 (feat/navarea-column-normalization): the sync
-- must already write bare coordinator codes, otherwise the next scrape
-- re-introduces prefixed labels. This script is IDEMPOTENT - if applied
-- before #69 lands, simply re-run it after; a clean re-run updates 0 rows.
--
-- What it does (labels only - NO geometry, status, or raw_text changes,
-- no FKs touched, nothing deleted, nothing cancelled):
--   1. 'NAVAREA II'  -> 'II'   (strip the 'NAVAREA ' display prefix)
--   2. 'AUSCOAST A'..'AUSCOAST H' -> 'X'  (AUSCOAST files under NAVAREA X)
-- Anything already bare ('II', 'X', ...) is untouched.
--
-- Safety properties (verified against 20261019_global_navarea_pipeline_adapted.sql):
--   * navarea is TEXT NOT NULL with NO CHECK constraint; no table has a
--     foreign key to it; the active-spatial and review-queue views select
--     it dynamically, so they follow the new values automatically.
--   * canonical_id is NOT touched - it keeps its 'NAVAREA '/'AUSCOAST '
--     prefix and remains the unique key and cancel cross-ref anchor.
--   * Runs in ONE transaction; any failure rolls back with zero writes.
--   * updated_at is bumped because the row genuinely changed; the
--     scrape skip logic is keyed on canonical_id, not updated_at, so
--     ingestion behavior is unaffected.
-- ============================================================================

BEGIN;

-- 1. Strip the 'NAVAREA ' prefix (idempotent: matches only prefixed rows).
UPDATE public.nav_warnings
SET navarea = regexp_replace(navarea, '^NAVAREA ', ''),
    updated_at = clock_timestamp()
WHERE navarea LIKE 'NAVAREA %';

-- 2. Fold every AUSCOAST pseudo-region label into bare 'X'.
UPDATE public.nav_warnings
SET navarea = 'X',
    updated_at = clock_timestamp()
WHERE navarea LIKE 'AUSCOAST%';

COMMIT;

-- Verification A (must return ZERO rows):
SELECT canonical_id, navarea FROM public.nav_warnings
WHERE navarea LIKE 'NAVAREA %' OR navarea LIKE 'AUSCOAST%';

-- Verification B - distribution check: every navarea should now be a bare
-- coordinator code ('I'..'XXI', 'X' covering AUSCOAST). Paste this output
-- back into the chat if any value other than a bare code appears.
SELECT navarea, count(*) FROM public.nav_warnings
GROUP BY navarea ORDER BY navarea;
