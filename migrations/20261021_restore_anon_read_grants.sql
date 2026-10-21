-- ============================================================================
-- Migration: 20261021_restore_anon_read_grants.sql
-- Restores public (anon/authenticated) SELECT grants lost during the
-- 20261019/20 schema rework. Frontend (helm.navwarning) reads return
-- 42501 "permission denied" without these, even though RLS policies exist
-- (RLS filters rows; it does not grant table access).
-- ============================================================================

-- 1. Grant SELECT on all existing public tables & views to anon + authenticated
GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon, authenticated;

-- 2. Service role keeps full access
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;

-- 3. Future-proof: objects created later (by any role) get the same grants
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO service_role;

-- 4. Keep sensitive audit data out of public reach
REVOKE SELECT ON public.nav_warning_audits FROM anon, authenticated;

-- 5. Re-verify (should all be true)
-- SELECT has_table_privilege('anon','nav_warnings','SELECT'),
--        has_table_privilege('anon','nav_warnings_active_spatial','SELECT'),
--        has_table_privilege('anon','nav_warnings_review_queue','SELECT'),
--        has_table_privilege('anon','raw_messages','SELECT');
