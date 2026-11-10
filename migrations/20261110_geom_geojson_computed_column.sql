-- migrations/20261110_geom_geojson_computed_column.sql
-- PostgREST computed column for public.nav_warning_geometries.
--
-- Audit 2026-11-10: the Supabase Parsing Audit's geometry fetch failed with
-- PGRST200 because PostgREST parses select=st_asgeojson(geom_postgis) as an
-- embedded resource, not a function call. PostgREST computed columns use no
-- function-call syntax: expose the GeoJSON payload through a single-argument
-- function over the table's row type, selected as a plain column
-- (select=...,geom_geojson).
--
-- The stored column is geography(Geometry, 4326) NOT NULL; PostGIS lives in
-- the 'public' schema on this project's Supabase (live check 2026-11-10), so
-- the body is schema-qualified and the function pins its search_path (same
-- hardening applied to is_admin()).
--
-- Grants: EXECUTE is revoked from public/anon/authenticated (new functions
-- default to EXECUTE for PUBLIC) and granted to service_role only. The audit
-- job authenticates with the service-role key. The function runs with the
-- invoker's privileges: table RLS and grants are untouched.
--
-- ROLLBACK:
--   drop function if exists public.geom_geojson(public.nav_warning_geometries);
--   notify pgrst, 'reload schema';

-- 42P13 guard: a pre-existing geom_geojson(nav_warning_geometries) with a
-- different input parameter name blocks CREATE OR REPLACE (live apply hit
-- "cannot change name of input parameter \"rec\""). Drop first so the
-- migration is re-runnable regardless of any prior definition.
drop function if exists public.geom_geojson(public.nav_warning_geometries);

create or replace function public.geom_geojson(g public.nav_warning_geometries)
returns jsonb
language sql
stable
set search_path = public, pg_catalog
as $$
    select public.st_asgeojson(g.geom_postgis)::jsonb
$$;

revoke all on function public.geom_geojson(public.nav_warning_geometries)
    from public, anon, authenticated;
grant execute on function public.geom_geojson(public.nav_warning_geometries)
    to service_role;

-- PostgREST must reload its schema cache to expose the computed column.
notify pgrst, 'reload schema';
