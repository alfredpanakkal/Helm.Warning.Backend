-- Grants for the CI/ingestion service role.
-- Fixes: permission denied for table nav_warnings (SQLSTATE 42501)
-- Run in the Supabase SQL editor as postgres.

GRANT SELECT, INSERT, UPDATE, DELETE ON public.nav_warnings  TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.raw_messages TO service_role;

-- If geometry child rows are stored in a separate table, grant on it too:
-- GRANT SELECT, INSERT, UPDATE, DELETE ON public.warning_geometries TO service_role;

-- The differential engine prefers the upsert_nav_warning RPC but falls back to
-- a direct nav_warnings upsert if the RPC is unavailable, so this grant is optional.
-- Wrapped in a DO block so it never fails if the function is absent or has a
-- different signature (ERROR 42883: function does not exist).
DO $$
DECLARE
  fn oid;
BEGIN
  SELECT p.oid INTO fn
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.proname = 'upsert_nav_warning'
  LIMIT 1;
  IF fn IS NOT NULL THEN
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.upsert_nav_warning(%s) TO service_role',
                   (SELECT pg_get_function_identity_arguments(fn)));
    RAISE NOTICE 'Granted EXECUTE on upsert_nav_warning to service_role';
  ELSE
    RAISE NOTICE 'upsert_nav_warning not found; skipped (engine falls back to direct upsert)';
  END IF;
END $$;

-- Prevent recurrence: tables created manually in the SQL editor (as postgres)
-- do not inherit Supabase's default service_role grants.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT ALL ON TABLES TO service_role;
