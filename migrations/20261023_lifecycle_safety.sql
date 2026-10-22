-- ============================================================================
-- Migration: 20261023_lifecycle_safety.sql
-- Data-lifecycle safety: archiving is a change in visibility and status,
-- never a deletion of parsed data.
--
--   1. status_changed_at on nav_warnings (status_basis already exists from
--      20261019) so every lifecycle transition is timestamped and auditable.
--   2. ingestion_generations run ledger — one row per sync run, read by the
--      Data Bank frontend, so "where did the warnings go?" is answerable.
--   3. nav_warnings_archive view for the Data Bank: archived warnings stay
--      searchable WITHOUT a geometry JOIN requirement.
--   4. upsert_nav_warning RPC hardening: a re-parse that yields no valid
--      geometry PRESERVES the previous geometry (and Tier A) instead of
--      silently deleting geometry rows and hiding the warning from the map.
--      Replacements are inserted BEFORE old rows are deleted, so a failed
--      geometry insert can never leave a Tier-A warning with zero geoms.
-- ============================================================================

-- 1. Status transition audit columns ---------------------------------------
ALTER TABLE public.nav_warnings
    ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_nav_warnings_source_status
    ON public.nav_warnings (source_id, status);

-- 2. Run ledger (ingestion_generations) --------------------------------------
CREATE TABLE IF NOT EXISTS public.ingestion_generations (
    generation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL,
    navarea TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed', 'empty_feed')),
    parsed_count INTEGER NOT NULL DEFAULT 0,
    active_count INTEGER,
    evidence_hash TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ingestion_generations_source_time
    ON public.ingestion_generations (source_id, started_at DESC);

ALTER TABLE public.ingestion_generations ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'ingestion_generations'
      AND policyname = 'public read ingestion_generations'
  ) THEN
    CREATE POLICY "public read ingestion_generations"
      ON public.ingestion_generations
      FOR SELECT TO anon, authenticated USING (true);
  END IF;
END $$;

-- 3. Archive view for the Data Bank (no geometry requirement) ---------------
CREATE OR REPLACE VIEW public.nav_warnings_archive AS
  SELECT
    id, canonical_id, navarea, source_id, title, area_text, categories,
    status, status_basis, status_changed_at, triage_tier, data_quality,
    parsing_method, qa_flags, unplotted_reason, valid_from, valid_to,
    raw_text, created_at, updated_at
  FROM public.nav_warnings
  WHERE status <> 'active'
  ORDER BY status_changed_at DESC NULLS LAST;

-- 4. Geometry-preserving upsert RPC ------------------------------------------
--    Replaces the 20261022 definition. Behavioral changes:
--      * New geometries are inserted FIRST; the previous rows are deleted
--        only after at least one replacement was accepted (keyed by geom_id).
--      * If the incoming payload has no geometry (or all inserts fail) and
--        the warning already has geometries, the previous geometries are
--        PRESERVED, Tier A is kept (chk_tier_a_invariants satisfied:
--        unplotted_reason cleared), and a 'geometry_preserved_previous_run'
--        qa_flag is appended for review.
--      * Demotion to Tier C happens ONLY when the warning genuinely has
--        zero geometry rows after the upsert.
CREATE OR REPLACE FUNCTION public.upsert_nav_warning(p_payload jsonb)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $func$
DECLARE
    v_master      jsonb := p_payload->'master';
    v_geoms       jsonb := p_payload->'geometries';
    v_id          uuid;
    v_valid_from  timestamptz;
    v_valid_to    timestamptz;
    g             jsonb;
    v_ftype       text;
    v_gid         uuid;
    v_kept        int := 0;
    v_existing    int := 0;
    v_new_ids     uuid[] := '{}';
BEGIN
    -- Tolerant date parsing: guard against unparseable free text
    BEGIN
        v_valid_from := NULLIF(v_master->>'valid_from', '')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
        v_valid_from := NULL;
    END;

    BEGIN
        v_valid_to := NULLIF(v_master->>'valid_to', '')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
        v_valid_to := NULL;
    END;

    INSERT INTO public.nav_warnings (
        canonical_id, navarea, title, area_text, categories, status,
        triage_tier, data_quality, parsing_method, qa_flags,
        unplotted_reason, valid_from, valid_to, raw_text, source_id
    ) VALUES (
        v_master->>'canonical_id',
        v_master->>'navarea',
        v_master->>'title',
        v_master->>'area_text',
        COALESCE(ARRAY(SELECT jsonb_array_elements_text(v_master->'categories')), '{}'),
        COALESCE(v_master->>'status', 'active'),
        COALESCE(v_master->>'triage_tier', 'C'),
    rom = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to,
        raw_text = EXCLUDED.raw_text,
        source_id = EXCLUDED.source_id,
        updated_at = now()
    RETURNING id INTO v_id;

    v_existing := (
        SELECT count(*) FROM public.nav_warning_geometries WHERE warning_id = v_id
    );

    IF v_geoms IS NOT NULL AND jsonb_array_length(v_geoms) > 0 THEN
        FOR g IN SELECT * FROM jsonb_array_elements(v_geoms)
        LOOP
            -- Map payload feature_type into the CHECK-constraint vocabulary
            v_ftype := COALESCE(
                CASE upper(g->>'feature_type')
                    WHEN 'LINESTRING'      THEN 'LINE'
                    WHEN 'MULTILINESTRING' THEN 'LINE'
                    WHEN 'MULTIPOINT'      THEN 'POINT'
                    WHEN 'MULTIPOLYGON'    THEN 'POLYGON'
                    WHEN 'POINT'           THEN 'POINT'
                    WHEN 'POLYGON'         THEN 'POLYGON'
                    WHEN 'CORRIDOR'        THEN 'CORRIDOR'
                    WHEN 'SWEEP_ARC'       THEN 'SWEEP_ARC'
                    WHEN 'BOUNDING_BOX'    THEN 'BOUNDING_BOX'
                    ELSE NULL
                END,
                'POINT'
            );

            -- Tolerant per-geometry insert: skip invalid GeoJSON instead of
            -- aborting the whole warning
            BEGIN
                INSERT INTO public.nav_warning_geometries (
                    warning_id, zone_label, feature_type,
                    buffetted_reason = 'no_valid_geometry'
         WHERE id = v_id;
    END IF;

    RETURN v_id;
END;
$func$;

-- Verify the fix took effect:
SELECT proname, pg_get_function_arguments(oid) AS args
FROM pg_proc
WHERE proname = 'upsert_nav_warning';
