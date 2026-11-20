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
       OR has_table_privilege('anon', 'public.spatial_ref_sys', 'REFERENCES')
       OR has_table_privilege('anon', 'public.spatial_ref_sys', 'TRIGGER')
       OR has_table_privilege('anon', 'public.spatial_ref_sys', 'MAINTAIN')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'INSERT')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'UPDATE')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'DELETE')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'TRUNCATE')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'REFERENCES')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'TRIGGER')
       OR has_table_privilege('authenticated', 'public.spatial_ref_sys', 'MAINTAIN') THEN
        RAISE EXCEPTION 'Client roles retain unexpected spatial_ref_sys privileges';
    END IF;

    -- Table-level REVOKE does not prove that column-level write grants are absent.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS a
        WHERE a.attrelid = 'public.spatial_ref_sys'::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND (
              has_column_privilege('anon', a.attrelid, a.attname, 'INSERT')
              OR has_column_privilege('anon', a.attrelid, a.attname, 'UPDATE')
              OR has_column_privilege('anon', a.attrelid, a.attname, 'REFERENCES')
              OR has_column_privilege('authenticated', a.attrelid, a.attname, 'INSERT')
              OR has_column_privilege('authenticated', a.attrelid, a.attname, 'UPDATE')
              OR has_column_privilege('authenticated', a.attrelid, a.attname, 'REFERENCES')
          )
    ) THEN
        RAISE EXCEPTION 'Client roles retain column-level spatial_ref_sys write privileges';
    END IF;
END;
$assert$;

COMMIT;
