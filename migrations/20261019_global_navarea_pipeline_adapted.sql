-- ============================================================================
-- SUPABASE / POSTGRESQL PRODUCTION MIGRATION
-- Project: Global Navigational Warnings (NAVAREA / AUSCOAST Pipeline)
-- Migration: 20261019_global_navarea_pipeline_adapted.sql
-- Compliance: Helm Rules H01–H13, Rules 1–125, PostGIS Antimeridian Safe
-- ============================================================================

-- Step 1: Enable Prerequisite Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- Step 2: Master Warning Envelope Table
CREATE TABLE IF NOT EXISTS public.nav_warnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_id TEXT UNIQUE NOT NULL, -- e.g. 'NAVAREA IV 1042/26', 'AUSCOAST 045/26'
    navarea TEXT NOT NULL,
    source_id TEXT NOT NULL,
    publisher_id TEXT,
    series TEXT,
    warning_number INTEGER,
    warning_year INTEGER,
    title TEXT NOT NULL,
    area_text TEXT,
    raw_text TEXT NOT NULL, -- Immutable raw text provenance (Rule 125)
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'expired', 'superseded', 'unverified')),
    status_basis TEXT,
    data_quality TEXT NOT NULL DEFAULT 'EXPLICIT' CHECK (data_quality IN ('EXPLICIT', 'INFERRED', 'AMBIGUOUS', 'INVALID')),
    triage_tier TEXT NOT NULL DEFAULT 'C' CHECK (triage_tier IN ('A', 'B', 'C')),
    parsing_method TEXT NOT NULL DEFAULT 'RULE' CHECK (parsing_method IN ('RULE', 'AI')),
    unplotted_reason TEXT CHECK (unplotted_reason IS NULL OR unplotted_reason IN (
        'no_coordinates', 'parse_failure', 'meta_list', 'text_unavailable',
        'empty_stub', 'cancellation_only', 'truncated_clause', 'missing_hemisphere',
        'duplicate_of', 'validation_failed', 'no_valid_geometry'
    )),
    cancels_ids TEXT[] NOT NULL DEFAULT '{}',
    qa_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    span_edits JSONB NOT NULL DEFAULT '[]'::jsonb,
    radio_communications JSONB NOT NULL DEFAULT '[]'::jsonb,
    radio_frequencies TEXT[] NOT NULL DEFAULT '{}',
    categories TEXT[] NOT NULL DEFAULT '{}',
    space_launch_mission TEXT,
    altitude_ceiling_fl INTEGER,
    shoal_depth_m DOUBLE PRECISION,
    is_depth_unknown BOOLEAN NOT NULL DEFAULT FALSE,
    tow_length_m DOUBLE PRECISION,
    tow_speed_kts DOUBLE PRECISION,
    applicable_vessel_filter TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    issued_at TIMESTAMPTZ,
    duplicate_of_id UUID REFERENCES public.nav_warnings(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    -- Helm Rule H02 Precedence Constraint: Tier A records CANNOT be invalid, ambiguous, or unplotted
    CONSTRAINT chk_tier_a_invariants CHECK (
        triage_tier != 'A' OR (
            data_quality = 'EXPLICIT'
            AND unplotted_reason IS NULL
            AND parsing_method = 'RULE'
            AND status != 'superseded'
        )
    ),

    -- Rule 31 Bathymetry Sentinel Constraint: Exclude unmeasured -9999.0 sentinels
    CONSTRAINT chk_shoal_depth_sentinel CHECK (
        shoal_depth_m IS NULL OR (
            shoal_depth_m > -50.0 
            AND shoal_depth_m != -9999.0 
            AND shoal_depth_m < 12000.0
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_nav_warnings_canonical_id ON public.nav_warnings(canonical_id);
CREATE INDEX IF NOT EXISTS idx_nav_warnings_status ON public.nav_warnings(status);
CREATE INDEX IF NOT EXISTS idx_nav_warnings_tier ON public.nav_warnings(triage_tier);
CREATE INDEX IF NOT EXISTS idx_nav_warnings_navarea ON public.nav_warnings(navarea);
CREATE INDEX IF NOT EXISTS idx_nav_warnings_valid_range ON public.nav_warnings(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_nav_warnings_cancels_ids ON public.nav_warnings USING GIN (cancels_ids);
CREATE INDEX IF NOT EXISTS idx_nav_warnings_qa_flags ON public.nav_warnings USING GIN (qa_flags);

-- Step 3: Normalized Geometries Child Table
-- Uses PostGIS geography(Geometry, 4326) for antimeridian safety.
-- Redundant geojson_blob column completely removed; dynamically computed in views.
CREATE TABLE IF NOT EXISTS public.nav_warning_geometries (
    geom_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id UUID NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    zone_label TEXT, -- e.g. 'AREA A', 'STAGE 1 RECOVERY', 'CORRIDOR BRAVO'
    feature_type TEXT NOT NULL CHECK (feature_type IN ('POINT', 'LINE', 'POLYGON', 'CORRIDOR', 'SWEEP_ARC', 'BOUNDING_BOX')),
    geom_postgis geography(Geometry, 4326) NOT NULL,
    buffer_nm DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    corridor_half_width_nm DOUBLE PRECISION,
    altitude_floor_m DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    altitude_ceiling_fl INTEGER,
    sweep_start_azimuth DOUBLE PRECISION,
    sweep_end_azimuth DOUBLE PRECISION,
    sweep_radius_nm DOUBLE PRECISION,
    snapping_rule TEXT NOT NULL DEFAULT 'NONE' CHECK (snapping_rule IN ('NONE', 'COASTAL_CONTOUR')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_warning_geometries_postgis 
  ON public.nav_warning_geometries USING GIST (geom_postgis);
CREATE INDEX IF NOT EXISTS idx_warning_geometries_wid 
  ON public.nav_warning_geometries (warning_id);

-- Step 4: Maritime Entities Child Table (Vessels, Rigs, Flotillas, Depths)
CREATE TABLE IF NOT EXISTS public.nav_warning_entities (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id UUID NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('VESSEL', 'OFFSHORE_RIG', 'BUOY', 'CABLE', 'PIPELINE', 'WRECK', 'OBSTRUCTION')),
    entity_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'PRIMARY' CHECK (role IN (
        'PRIMARY', 'LEAD_TUG', 'BRAKE_TUG', 'CHASE_BOAT', 'GUARD_VESSEL', 'CASUALTY', 'STANDBY', 'ATTENDANT'
    )),
    callsign TEXT,
    mmsi TEXT,
    tow_length_m DOUBLE PRECISION,
    tow_speed_kts DOUBLE PRECISION,
    streamer_count INTEGER,
    streamer_length_m DOUBLE PRECISION,
    streamer_breadth_m DOUBLE PRECISION,
    streamer_depth_m DOUBLE PRECISION,
    clearance_requested_nm DOUBLE PRECISION,
    depth_m DOUBLE PRECISION,
    depth_status TEXT CHECK (depth_status IN ('MEASURED', 'UNKNOWN', 'APPROXIMATE', 'DRYING')),
    datum_ref TEXT DEFAULT 'LAT',
    radio_channels JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT chk_entity_depth_sentinel CHECK (
        depth_m IS NULL OR (depth_m > -50.0 AND depth_m != -9999.0 AND depth_m < 12000.0)
    )
);

CREATE INDEX IF NOT EXISTS idx_warning_entities_wid ON public.nav_warning_entities(warning_id);
CREATE INDEX IF NOT EXISTS idx_warning_entities_type ON public.nav_warning_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_warning_entities_mmsi ON public.nav_warning_entities(mmsi) WHERE mmsi IS NOT NULL;

-- Step 5: Chart References Child Table
CREATE TABLE IF NOT EXISTS public.nav_warning_charts (
    chart_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id UUID NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    authority TEXT, -- e.g. 'BA', 'SAN', 'JP', 'US'
    chart_number TEXT NOT NULL,
    int_equivalent TEXT,
    is_international BOOLEAN NOT NULL DEFAULT FALSE,
    raw_citation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_warning_charts_wid ON public.nav_warning_charts(warning_id);
CREATE INDEX IF NOT EXISTS idx_warning_charts_number ON public.nav_warning_charts(chart_number);

-- Step 6: Operational Schedules Child Table (Indexed Intervals)
CREATE TABLE IF NOT EXISTS public.nav_warning_schedules (
    schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id UUID NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    active_range TSTZRANGE GENERATED ALWAYS AS (tstzrange(window_start, window_end, '[)')) STORED,
    is_alternate BOOLEAN NOT NULL DEFAULT FALSE,
    recurrence_rule TEXT,
    days_of_week INTEGER[], -- 0=Sunday..6=Saturday
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT chk_schedule_window_order CHECK (window_start < window_end)
);

CREATE INDEX IF NOT EXISTS idx_warning_schedules_wid ON public.nav_warning_schedules(warning_id);
CREATE INDEX IF NOT EXISTS idx_warning_schedules_active_range 
  ON public.nav_warning_schedules USING GIST (active_range);

-- Step 7: Compound Cancellation Child Table
CREATE TABLE IF NOT EXISTS public.nav_warning_cancellations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cancelling_warning_id UUID NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    target_canonical_id TEXT NOT NULL, -- Human-readable reference e.g. '156/26' or 'NAVAREA I 206/26'
    target_warning_id UUID REFERENCES public.nav_warnings(id) ON DELETE SET NULL, -- Resolved when target exists in DB
    cancellation_type TEXT NOT NULL DEFAULT 'EXPLICIT_NOTICE' CHECK (
        cancellation_type IN ('EXPLICIT_NOTICE', 'IN_FORCE_OMISSION', 'PARAGRAPH_SELF_CANCEL')
    ),
    paragraph_ref TEXT, -- e.g. 'THIS PARA', 'PARA 2'
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_cancellations_source ON public.nav_warning_cancellations(cancelling_warning_id);
CREATE INDEX IF NOT EXISTS idx_cancellations_target_canonical ON public.nav_warning_cancellations(target_canonical_id);
CREATE INDEX IF NOT EXISTS idx_cancellations_target_uuid ON public.nav_warning_cancellations(target_warning_id);

-- Step 8: Human Review Audit Log Table
CREATE TABLE IF NOT EXISTS public.nav_warning_audits (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id UUID NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    operator_id TEXT NOT NULL,
    previous_tier TEXT NOT NULL,
    new_tier TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    signature_hash TEXT NOT NULL,
    diff_patch JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_warning_audits_wid ON public.nav_warning_audits(warning_id);

-- Step 9: Active Spatial GIS View (ECDIS / Leaflet)
-- Antimeridian-Safe: Uses geography(Geometry, 4326)
-- Eliminates redundant storage: Dynamically computes geojson_blob via ST_AsGeoJSON
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
    ST_AsGeoJSON(g.geom_postgis)::jsonb AS geojson_blob
  FROM public.nav_warnings w
  JOIN public.nav_warning_geometries g ON w.id = g.warning_id
  WHERE w.status = 'active'
    AND w.triage_tier = 'A';

-- Step 10: Operator Review Queue View (Tier B Warnings Requiring Triage)
CREATE OR REPLACE VIEW public.nav_warnings_review_queue AS
  SELECT 
    w.id AS warning_id,
    w.canonical_id,
    w.navarea,
    w.title,
    w.status,
    w.triage_tier,
    w.data_quality,
    w.parsing_method,
    w.qa_flags,
    w.unplotted_reason,
    w.raw_text,
    w.span_edits,
    w.issued_at,
    w.created_at
  FROM public.nav_warnings w
  WHERE w.triage_tier = 'B'
    AND w.status = 'active'
  ORDER BY w.issued_at DESC NULLS LAST;
