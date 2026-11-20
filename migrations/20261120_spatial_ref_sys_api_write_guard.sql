-- Supabase Free-tier workaround for the Supabase-managed ownership of PostGIS spatial_ref_sys.
-- The direct table REVOKE in 20261115_spatial_ref_sys_read_only.sql cannot remove
-- grants issued by supabase_admin on Production. Keep PostgreSQL grants unchanged
-- and reject public-role writes at the PostgREST Data API boundary instead.
--
-- This does not protect direct database connections, Realtime, Storage, or other
-- non-PostgREST paths. It also does not clear the underlying Security Advisor lint.

BEGIN;

CREATE SCHEMA IF NOT EXISTS private AUTHORIZATION postgres;

GRANT USAGE ON SCHEMA private TO authenticator, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION private.block_spatial_ref_sys_writes()
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
DECLARE
    request_method text := upper(coalesce(current_setting('request.method', true), ''));
    request_path text := lower(trim(both '/' from coalesce(current_setting('request.path', true), '')));
    request_role text := coalesce(
        nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
        nullif(current_setting('role', true), 'none'),
        current_user
    );
BEGIN
    IF request_method IN ('POST', 'PUT', 'PATCH', 'DELETE')
       AND request_path IN ('spatial_ref_sys', 'public.spatial_ref_sys')
       AND request_role IN ('anon', 'authenticated') THEN
        RAISE SQLSTATE 'PGRST' USING
            MESSAGE = jsonb_build_object(
                'code', '42501',
                'message', 'Writes to spatial_ref_sys are blocked for client roles',
                'details', 'The PostGIS SRID catalogue is read-only through the Data API.',
                'hint', 'Use spatial_ref_sys for reference lookups only.'
            )::text,
            DETAIL = jsonb_build_object('status', 403)::text;
    END IF;
END;
$function$;

REVOKE ALL ON FUNCTION private.block_spatial_ref_sys_writes() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION private.block_spatial_ref_sys_writes()
    TO authenticator, anon, authenticated, service_role;

-- Do not silently replace another project's existing pre-request hook.
DO $hook_guard$
DECLARE
    existing_hook text;
BEGIN
    SELECT config
      INTO existing_hook
      FROM (
          SELECT unnest(s.setconfig) AS config
            FROM pg_catalog.pg_db_role_setting AS s
           WHERE s.setrole = 'authenticator'::regrole
      ) AS role_settings
     WHERE config LIKE 'pgrst.db_pre_request=%'
     LIMIT 1;

    IF existing_hook IS NOT NULL
       AND existing_hook <> 'pgrst.db_pre_request=private.block_spatial_ref_sys_writes' THEN
        RAISE EXCEPTION
            'authenticator already has a different pgrst.db_pre_request hook: %',
            existing_hook;
    END IF;
END;
$hook_guard$;

ALTER ROLE authenticator
    SET pgrst.db_pre_request = 'private.block_spatial_ref_sys_writes';

NOTIFY pgrst, 'reload config';

COMMIT;
