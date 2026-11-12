-- ============================================================================
-- Migration: 20261112_geometry_metadata_persistence.sql
-- Align triage publication checks, persist corridor clearance, and expose
-- the complete persisted geometry metadata through the active spatial view.
-- Existing lifecycle-safe geometry replacement/preservation remains intact.

BEGIN;

ALTER TABLE public.nav_warning_geometries
    ADD COLUMN IF NOT EXISTS corridor_clearance_nm DOUBLE PRECISION;

-- Existing CHECK covers the four Tier-A database fields. This additive guard
-- prevents known partial-zone/repair markers from entering the auto-plot tier.
ALTER TABLE public.nav_warnings
    ADD CONSTRAINT chk_tier_a_qa_flags
    CHECK (
        triage_tier <> 'A'
        OR NOT (qa_flags ?| ARRAY['has_incomplete_zone', 'has_repairs'])
    ) NOT VALID;

-- Append columns only: CREATE OR REPLACE VIEW must preserve existing column order.
CREATE OR REPLACE VIEW public.nav_warnings_active_spatial AS
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
    ST_AsGeoJSON(g.geom_postgis)::jsonb AS geojson_blob,
    g.corridor_clearance_nm,
    g.sweep_radius_nm,
    g.sweep_start_azimuth,
    g.sweep_end_azimuth
  FROM public.nav_warnings w
  JOIN public.nav_warning_geometries g ON w.id = g.warning_id
  WHERE w.status = 'active'
    AND w.triage_tier = 'A';


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
                    buffer_nm, corridor_half_width_nm, corridor_clearance_nm,
                    sweep_start_azimuth, sweep_end_azimuth, sweep_radius_nm,
                    geom_postgis
                ) VALUES (
                    v_id,
                    g->>'zone_label',
                    v_ftype,
                    COALESCE((g->>'buffer_nm')::numeric, 0),
                    NULLIF(g->>'corridor_half_width_nm', '')::double precision,
                    NULLIF(g->>'corridor_clearance_nm', '')::double precision,
                    NULLIF(g->>'sweep_start_azimuth', '')::double precision,
                    NULLIF(g->>'sweep_end_azimuth', '')::double precision,
                    NULLIF(g->>'sweep_radius_nm', '')::double precision,
                    ST_SetSRID(ST_GeomFromGeoJSON(g->'geojson'), 4326)::geography
                )
                RETURNING geom_id INTO v_gid;
                v_kept := v_kept + 1;
                v_new_ids := array_append(v_new_ids, v_gid);
            EXCEPTION WHEN OTHERS THEN
                RAISE WARNING 'upsert_nav_warning: skipped invalid geometry for warning %: %',
                    v_master->>'canonical_id', SQLERRM;
            END;
        END LOOP;

        -- Replace previous geometries ONLY now that at least one replacement
        -- was accepted; the old rows are identified by geom_id.
        IF v_kept > 0 THEN
            DELETE FROM public.nav_warning_geometries
             WHERE warning_id = v_id
               AND NOT (geom_id = ANY (v_new_ids));
        END IF;
    END IF;

    -- Tier / geometry consistency after the upsert:
    IF v_kept > 0 THEN
        -- Normal path: fresh geometries exist; if a previous parse had flagged
        -- the warning as preserved, drop the stale flag on a healthy re-parse.
        UPDATE public.nav_warnings
           SET qa_flags = qa_flags - 'geometry_preserved_previous_run'
         WHERE id = v_id
           AND qa_flags @> '["geometry_preserved_previous_run"]';
    ELSIF v_existing > 0 THEN
        -- Preservation path: the incoming parse produced no geometry, but a
        -- previous run stored valid geometries. Keep them, keep Tier A
        -- (chk_tier_a_invariants: clear unplotted_reason) and flag for review.
        UPDATE public.nav_warnings
           SET triage_tier = 'A',
               unplotted_reason = NULL,
               qa_flags = COALESCE(qa_flags, '[]'::jsonb)
                          || '["geometry_preserved_previous_run"]'::jsonb
         WHERE id = v_id;
    ELSIF (v_master->>'triage_tier') = 'A' THEN
        -- Truly geometry-less warning: demote so the map never shows phantom
        -- Tier-A rows (matches chk_tier_a_invariants intent).
        UPDATE public.nav_warnings
           SET triage_tier = 'C',
               unplotted_reason = 'no_valid_geometry'
         WHERE id = v_id;
    END IF;

    RETURN v_id;
END;
$func$;

-- Confirm the RPC remains installed after replacement.
SELECT proname, pg_get_function_arguments(oid) AS args
FROM pg_proc
WHERE proname = 'upsert_nav_warning';

COMMIT;
