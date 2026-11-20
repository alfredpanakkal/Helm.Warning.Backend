-- Fix the PostgREST custom-error envelope for spatial_ref_sys write rejection.
--
-- Production HTTP verification found PGRST121 because the PGRST error DETAIL
-- omitted the required headers object. Keep the existing guard scope and
-- response status; only make the custom error envelope valid for PostgREST.

BEGIN;

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
            DETAIL = jsonb_build_object(
                'status', 403,
                'headers', '{}'::jsonb
            )::text;
    END IF;
END;
$function$;

REVOKE ALL ON FUNCTION private.block_spatial_ref_sys_writes() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION private.block_spatial_ref_sys_writes()
    TO authenticator, anon, authenticated, service_role;

NOTIFY pgrst, 'reload config';

COMMIT;
