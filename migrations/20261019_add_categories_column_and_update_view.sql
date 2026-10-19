-- ============================================================================
-- SUPABASE MIGRATION: 20261019_add_categories_column_and_update_view.sql
-- Description: Adds categories TEXT[] array to public.nav_warnings and updates
--              public.nav_warnings_active_spatial view to include categories.
-- ============================================================================

-- 1. Safely add the missing column to the master table
ALTER TABLE public.nav_warnings ADD COLUMN IF NOT EXISTS categories TEXT[] DEFAULT '{}';

-- 2. Drop the existing view
DROP VIEW IF EXISTS public.nav_warnings_active_spatial CASCADE;

-- 3. Recreate the view with the new categories column included
CREATE VIEW public.nav_warnings_active_spatial AS
  SELECT 
    w.id AS warning_id,
    w.canonical_id,
    w.navarea,
    w.title,
    w.area_text,
    w.categories,
    w.status,
    w.triage_tier,
    w.data_quality,
    w.valid_from,
    w.valid_to,
    w.radio_frequencies,
    w.space_launch_mission,
    g.geom_id,
    g.zone_label,
    g.feature_type,
    g.buffer_nm,
    g.corridor_half_width_nm,
    g.altitude_floor_m,
    g.altitude_ceiling_fl,
    g.geom_postgis,
    ST_AsGeoJSON(g.geom_postgis)::jsonb AS geojson_blob
  FROM public.nav_warnings w
  JOIN public.nav_warning_geometries g ON w.id = g.warning_id
  WHERE w.status = 'active'
    AND w.triage_tier = 'A';
