-- Grants for the CI/ingestion service role.
-- Fixes: permission denied for table nav_warnings (SQLSTATE 42501)
-- Run in the Supabase SQL editor as postgres.

GRANT SELECT, INSERT, UPDATE, DELETE ON public.nav_warnings  TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.raw_messages TO service_role;

-- If geometry child rows are stored in a separate table, grant on it too:
-- GRANT SELECT, INSERT, UPDATE, DELETE ON public.warning_geometries TO service_role;

-- The differential engine invokes this RPC (verify the exact signature with \df+ upsert_nav_warning):
GRANT EXECUTE ON FUNCTION public.upsert_nav_warning(jsonb) TO service_role;

-- Prevent recurrence: tables created manually in the SQL editor (as postgres)
-- do not inherit Supabase's default service_role grants.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT ALL ON TABLES TO service_role;
