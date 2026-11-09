-- 20261109_full_rewrite_backup.sql
-- One-off snapshot backup of the live dataset BEFORE the manual
-- full-rewrite re-scrape (SYNC_FORCE_REPARSE, full-rewrite.yml).
-- Keeps the pre-rewrite dataset intact while the re-scrape
-- overwrites nav_warnings / nav_warning_geometries / raw_messages
-- in place (upsert-only; the scraper never deletes).
--
-- Apply in Supabase SQL editor BEFORE triggering the
-- "Manual Full Rewrite" workflow_dispatch run.
-- IF NOT EXISTS: re-running never refreshes an existing backup
-- (intentional — the backup must stay the pre-rewrite snapshot).

CREATE TABLE IF NOT EXISTS public.nav_warnings_backup_20261109 AS
  SELECT * FROM public.nav_warnings;

CREATE TABLE IF NOT EXISTS public.nav_warning_geometries_backup_20261109 AS
  SELECT * FROM public.nav_warning_geometries;

CREATE TABLE IF NOT EXISTS public.raw_messages_backup_20261109 AS
  SELECT * FROM public.raw_messages;

-- Backups are read-only snapshots: no RLS policy grants write on them.
ALTER TABLE public.nav_warnings_backup_20261109 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.nav_warning_geometries_backup_20261109 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.raw_messages_backup_20261109 ENABLE ROW LEVEL SECURITY;

-- Verify after applying:
--   SELECT count(*) FROM public.nav_warnings_backup_20261109;
--   SELECT count(*) FROM public.nav_warning_geometries_backup_20261109;
--   SELECT count(*) FROM public.raw_messages_backup_20261109;
