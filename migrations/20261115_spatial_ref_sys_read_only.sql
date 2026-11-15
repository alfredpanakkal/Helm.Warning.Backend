-- Keep PostGIS SRID metadata readable by public map clients, but never writable.
-- spatial_ref_sys is extension metadata, not an application data table.
-- RLS remains disabled; SELECT is sufficient for ST_Transform lookups.
BEGIN;

REVOKE ALL PRIVILEGES ON TABLE public.spatial_ref_sys FROM anon, authenticated;
GRANT SELECT ON TABLE public.spatial_ref_sys TO anon, authenticated;

-- Fail the migration if either public role retains a direct write/DDL privilege.
DO $privilege_check$
DECLARE
    v_role text;
    v_privilege text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF NOT has_table_privilege(v_role, 'public.spatial_ref_sys', 'SELECT') THEN
            RAISE EXCEPTION '% must retain SELECT on public.spatial_ref_sys', v_role;
        END IF;

        FOREACH v_privilege IN ARRAY ARRAY[
            'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
        ] LOOP
            IF has_table_privilege(v_role, 'public.spatial_ref_sys', v_privilege) THEN
                RAISE EXCEPTION '% unexpectedly retains % on public.spatial_ref_sys',
                    v_role, v_privilege;
            END IF;
        END LOOP;
    END LOOP;
END;
$privilege_check$;

-- Exercise the PostGIS lookup path under each public role. This guards against
-- accidentally removing the SELECT access required by ST_Transform.
SET LOCAL ROLE anon;
DO $anon_transform_check$
BEGIN
    IF ST_SRID(ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857)) <> 3857 THEN
        RAISE EXCEPTION 'ST_Transform failed for anon';
    END IF;
END;
$anon_transform_check$;
RESET ROLE;

SET LOCAL ROLE authenticated;
DO $authenticated_transform_check$
BEGIN
    IF ST_SRID(ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857)) <> 3857 THEN
        RAISE EXCEPTION 'ST_Transform failed for authenticated';
    END IF;
END;
$authenticated_transform_check$;
RESET ROLE;

COMMIT;
