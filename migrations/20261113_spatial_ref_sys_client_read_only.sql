-- Remove unnecessary client-side write privileges on PostGIS spatial_ref_sys.
-- Preserve public coordinate-reference-system lookups and service-role grants.

BEGIN;

REVOKE ALL PRIVILEGES ON TABLE public.spatial_ref_sys
    FROM anon, authenticated;

-- PostGIS clients need to read the CRS catalogue; they do not need to mutate it.
GRANT SELECT ON TABLE public.spatial_ref_sys TO anon, authenticated;

DO $assert$
BEGIN
    IF NOT has_table_privilege('anon', 'public.spatial_ref_sys', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.spatial_ref_sys', 'SELECT') THEN
        RAISE EXCEPTION 'Client roles must retain spatial_ref_sys SELECT';
    END IF;

    IF has_table_privilege('anon', 'public.spatial_ref_sys', 'INSERT')
       OR has_table_privilege('anon', 'public.spatial_ref_sys', 'UPDATE')
       OR has_table_privilege('anon', 'public.spatial_ref_sys', 'DELETE')
       OR has_table_privilege('anon', 'public.spatial_ref_sys', 'TRUNCATE')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'INSERT')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'UPDATE')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'DELETE')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'TRUNCATE') THEN
        RAISE EXCEPTION 'Client roles retain unexpected spatial_ref_sys write privileges';
    END IF;
END;
$assert$;

COMMIT;
