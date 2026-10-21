-- ============================================================================
-- Migration: 20261022_fix_upsert_rpc_feature_type.sql
-- Fixes the upsert_nav_warning RPC that silently dropped ALL geometries:
--
--   COALESCE(g->>'feature_type', 'point')
--
-- inserted lowercase values ('point', 'linestring', 'polygon') which violate
-- nav_warning_geometries' CHECK constraint
--   feature_type IN ('POINT','LINE','POLYGON','CORRIDOR','SWEEP_ARC','BOUNDING_BOX')
-- aborting the RPC transaction. The Python sync engine then fell back to a
-- master-only upsert, producing Tier-A nav_warnings rows with ZERO
-- nav_warning_geometries rows (empty nav_warnings_active_spatial view).
--
-- This migration:
--   1. Remaps feature_type into the CHECK vocabulary (LINESTRING->LINE etc.)
--   2. Tolerates invalid GeoJSON per-geometry (skips with WARNING, keeps the rest)
--   3. Adds parsing_method / unplotted_reason / source_id to the UPDATE branch
--   4. Keeps triage_tier consistent: master forced to tier C when no geometries
--      survived (matches the chk_tier_a_invariants contract)
--
-- NOTE: after applying, re-run the region sync scripts so existing warnings
-- get their geometries written.
-- ============================================================================

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
    v_kept        int := 0;
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
        COALESCE(v_master->>'data_quality', 'EXPLICIT'),
        COALESCE(v_master->>'parsing_method', 'RULE'),
        COALESCE(v_master->'qa_flags', '[]'::jsonb),
        v_master->>'unplotted_reason',
        v_valid_from,
        v_valid_to,
        v_master->>'raw_text',
        v_master->>'source_id'
    )
    ON CONFLICT (canonical_id) DO UPDATE SET
        title = EXCLUDED.title,
        area_text = EXCLUDED.area_text,
        categories = EXCLUDED.categories,
        status = EXCLUDED.status,
        triage_tier = EXCLUDED.triage_tier,
        data_quality = EXCLUDED.data_quality,
        parsing_method = EXCLUDED.parsing_method,
        qa_flags = EXCLUDED.qa_flags,
        unplotted_reason = EXCLUDED.unplotted_reason,
        valid_from = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to,
        raw_text = EXCLUDED.raw_text,
        source_id = EXCLUDED.source_id,
        updated_at = now()
    RETURNING id INTO v_id;

    -- Replace child geometries atomically
    DELETE FROM public.nav_warning_geometries WHERE warning_id = v_id;

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
                    buffer_nm, geom_postgis
                ) VALUES (
                    v_id,
                    g->>'zone_label',
                    v_ftype,
                    COALESCE((g->>'buffer_nm')::numeric, 0),
                    ST_SetSRID(ST_GeomFromGeoJSON(g->'geojson'), 4326)::geography
                );
                v_kept := v_kept + 1;
            EXCEPTION WHEN OTHERS THEN
                RAISE WARNING 'upsert_nav_warning: skipped invalid geometry for warning %: %',
                    v_master->>'canonical_id', SQLERRM;
            END;
        END LOOP;
    END IF;

    -- Tier-A invariant: a Tier-A master must have at least one geometry.
    -- If every geometry was skipped, demote to C so the map never shows
    -- phantom Tier-A rows (matches chk_tier_a_invariants intent).
    IF v_kept = 0 AND (v_master->>'triage_tier') = 'A' THEN
        UPDATE public.nav_warnings
           SET triage_tier = 'C',
               unplotted_reason = 'no_valid_geometry'
         WHERE id = v_id;
    END IF;

    RETURN v_id;
END;
$func$;

-- Verify the fix took effect:
SELECT proname, pg_get_function_arguments(oid) AS args
FROM pg_proc
WHERE proname = 'upsert_nav_warning';
