-- Migration: 20261112_rpc_write_security_and_sources_registry.sql
-- Secure warning writes while preserving service-role ingestion and admin imports.
-- Restore the source registry contract already consumed by the frontend.

BEGIN;

-- 1. Enforce authorization at the master warning table boundary.
-- This also protects writes made through SECURITY DEFINER RPCs.
CREATE OR REPLACE FUNCTION public.enforce_nav_warning_write_access()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF auth.role() = 'service_role' THEN
    RETURN NEW;
  END IF;

  IF auth.role() = 'authenticated'
     AND EXISTS (
       SELECT 1
       FROM public.admin_users au
       WHERE au.user_id = auth.uid()
     ) THEN
    RETURN NEW;
  END IF;

  RAISE EXCEPTION 'Not authorized to write navigational warnings'
    USING ERRCODE = '42501';
END;
$$;

DROP TRIGGER IF EXISTS trg_nav_warnings_write_access ON public.nav_warnings;
CREATE TRIGGER trg_nav_warnings_write_access
BEFORE INSERT OR UPDATE ON public.nav_warnings
FOR EACH ROW
EXECUTE FUNCTION public.enforce_nav_warning_write_access();

-- The RPC remains available to signed-in admins and the backend service role.
-- The trigger above performs the actual admin-membership check.
REVOKE ALL ON FUNCTION public.upsert_nav_warning(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.upsert_nav_warning(jsonb) FROM anon;
GRANT EXECUTE ON FUNCTION public.upsert_nav_warning(jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_nav_warning(jsonb) TO service_role;

-- 2. Restore the exact field contract queried by src/core/supabaseClient.ts.
CREATE TABLE IF NOT EXISTS public.sources_registry (
  source_id text PRIMARY KEY,
  publisher_name text NOT NULL,
  navarea text NOT NULL,
  format text NOT NULL,
  languages text[] NOT NULL DEFAULT '{}',
  parser_id text NOT NULL,
  entrypoints text[] NOT NULL DEFAULT '{}',
  poll_interval_sec integer NOT NULL DEFAULT 86400
    CHECK (poll_interval_sec > 0),
  is_active boolean NOT NULL DEFAULT true,
  last_run_at timestamptz,
  last_status text,
  active_warnings_count integer NOT NULL DEFAULT 0
    CHECK (active_warnings_count >= 0)
);

ALTER TABLE public.sources_registry ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "public read sources_registry" ON public.sources_registry;
CREATE POLICY "public read sources_registry"
  ON public.sources_registry
  FOR SELECT
  TO anon, authenticated
  USING (true);

GRANT SELECT ON public.sources_registry TO anon, authenticated;
GRANT ALL ON public.sources_registry TO service_role;

COMMIT;
