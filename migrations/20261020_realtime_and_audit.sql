-- Migration: 20261020_realtime_and_audit.sql
-- Enables Realtime publication, sets up raw_messages audit table, configures RLS,
-- harmonizes duplicate_of_id UUID type, updates review queue view,
-- and defines atomic upsert_nav_warning RPC with safe date parsing.

-- 1. Realtime Publication
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
    BEGIN
      ALTER PUBLICATION supabase_realtime ADD TABLE public.nav_warnings;
    EXCEPTION WHEN duplicate_object THEN
      NULL;
    END;
    BEGIN
      ALTER PUBLICATION supabase_realtime ADD TABLE public.nav_warning_geometries;
    EXCEPTION WHEN duplicate_object THEN
      NULL;
    END;
  END IF;
END $$;

-- 2. Audit Logging Table (raw_messages)
CREATE TABLE IF NOT EXISTS public.raw_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id text NOT NULL,
    source_id text NOT NULL,
    subject_header text,
    full_raw_text text NOT NULL,
    received_timestamp timestamptz DEFAULT now(),
    checksum_sha256 text NOT NULL,
    UNIQUE (warning_id, source_id, checksum_sha256)
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_checksum
    ON public.raw_messages (source_id, checksum_sha256);

CREATE INDEX IF NOT EXISTS idx_raw_messages_warning_id
    ON public.raw_messages (warning_id);

-- 3. Row-Level Security (RLS) Configuration
ALTER TABLE public.nav_warnings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.nav_warning_geometries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.raw_messages ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'nav_warnings' AND policyname = 'public read nav_warnings') THEN
    CREATE POLICY "public read nav_warnings" ON public.nav_warnings FOR SELECT TO anon, authenticated USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'nav_warning_geometries' AND policyname = 'public read geometries') THEN
    CREATE POLICY "public read geometries" ON public.nav_warning_geometries FOR SELECT TO anon, authenticated USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'raw_messages' AND policyname = 'public read raw_messages') THEN
    CREATE POLICY "public read raw_messages" ON public.raw_messages FOR SELECT TO anon, authenticated USING (true);
  END IF;
END $$;

-- 4. Harmonize duplicate_of_id and update review queue view
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'nav_warnings' AND column_name = 'duplicate_of_id' AND data_type = 'text'
  ) THEN
    ALTER TABLE public.nav_warnings DROP COLUMN duplicate_of_id CASCADE;
    ALTER TABLE public.nav_warnings ADD COLUMN duplicate_of_id uuid REFERENCES public.nav_warnings(id);
  ELSIF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'nav_warnings' AND column_name = 'duplicate_of_id'
  ) THEN
    ALTER TABLE public.nav_warnings ADD COLUMN duplicate_of_id uuid REFERENCES public.nav_warnings(id);
  END IF;
END $$;

CREATE OR REPLACE VIEW public.nav_warnings_review_queue AS
  SELECT 
    id, canonical_id, navarea, title, area_text, categories,
    status, triage_tier, data_quality, parsing_method,
    qa_flags, unplotted_reason, duplicate_of_id, raw_text,
    valid_from, valid_to, created_at, updated_at
  FROM public.nav_warnings
  WHERE triage_tier = 'B' AND status <> 'cancelled';

-- 5. Atomic Upsert RPC with safe date casting & CVE-safe search_path
CREATE OR REPLACE FUNCTION public.upsert_nav_warning(p_payload jsonb)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_master      jsonb := p_payload->'master';
    v_geoms       jsonb := p_payload->'geometries';
    v_id          uuid;
    v_valid_from  timestamptz;
    v_valid_to    timestamptz;
    g             jsonb;
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
        qa_flags = EXCLUDED.qa_flags,
        valid_from = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to,
        raw_text = EXCLUDED.raw_text,
        updated_at = now()
    RETURNING id INTO v_id;

    -- Replace child geometries atomically
    DELETE FROM public.nav_warning_geometries WHERE warning_id = v_id;

    IF v_geoms IS NOT NULL AND jsonb_array_length(v_geoms) > 0 THEN
        FOR g IN SELECT * FROM jsonb_array_elements(v_geoms)
        LOOP
            INSERT INTO public.nav_warning_geometries (
                warning_id, zone_label, feature_type,
                buffer_nm, geom_postgis
            ) VALUES (
                v_id,
                g->>'zone_label',
                COALESCE(g->>'feature_type', 'point'),
                COALESCE((g->>'buffer_nm')::numeric, 0),
                ST_GeomFromGeoJSON(g->'geojson')::geography
            );
        END LOOP;
    END IF;

    RETURN v_id;
END;
$$;
