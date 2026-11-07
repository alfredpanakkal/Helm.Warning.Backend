-- migrations/20261107_st_asgeojson_public_wrapper.sql
-- Audit 2026-11-07: the Supabase Parsing Audit's geometry fetch failed for
-- every batch with PGRST200 ("Could not find a relationship between
-- 'nav_warning_geometries' and 'st_asgeojson'"), which the audit script then
-- silently downgraded to zero geometries — 700+ false
-- TIER_A_ZERO_GEOMETRIES errors in the report. Root cause: Supabase installs
-- PostGIS in the 'extensions' schema, so PostgREST cannot resolve
-- select=st_asgeojson(geom_postgis) — no public.st_asgeojson function exists
-- in the exposed schema. This migration exposes a thin public wrapper so the
-- computed column resolves. Idempotent and guarded: it never replaces a
-- st_asgeojson(geometry) function that already exists in public (e.g. a
-- PostGIS install that lives in public).

do $$
begin
    if not exists (
        select 1
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where p.proname = 'st_asgeojson'
          and n.nspname = 'public'
          and pg_get_function_identity_arguments(p.oid) = 'geometry'
    ) then
        execute $fn$
            create function public.st_asgeojson(geom geometry)
            returns text
            language sql
            stable
            as $body$
                select extensions.st_asgeojson(geom)
            $body$;
        $fn$;
    end if;
end $$;

-- PostgREST must reload its schema cache to expose the new function.
notify pgrst, 'reload schema';
