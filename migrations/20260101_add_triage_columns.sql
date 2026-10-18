-- Idempotent triage & provenance extension for public.nav_warnings
ALTER TABLE public.nav_warnings
  ADD COLUMN IF NOT EXISTS data_quality            text DEFAULT 'EXPLICIT',
  ADD COLUMN IF NOT EXISTS parsing_method           text DEFAULT 'RULE',
  ADD COLUMN IF NOT EXISTS triage_tier              text DEFAULT 'C',
  ADD COLUMN IF NOT EXISTS qa_flags                 jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS unplotted_reason         text,
  ADD COLUMN IF NOT EXISTS duplicate_of_id          text,
  ADD COLUMN IF NOT EXISTS coordinate_provenance    jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS shoal_depth_m            double precision,
  ADD COLUMN IF NOT EXISTS tow_length_m             double precision,
  ADD COLUMN IF NOT EXISTS tow_speed_kts            double precision,
  ADD COLUMN IF NOT EXISTS applicable_vessel_filter text;

-- Review queue view for Tier B operator triage (BulletinParserStudio)
CREATE OR REPLACE VIEW public.nav_warnings_review_queue AS
  SELECT * FROM public.nav_warnings WHERE triage_tier = 'B' AND cancelled = false
  ORDER BY issue_time DESC;

-- Raw/audit store for Tier C (never rendered on the map)
CREATE INDEX IF NOT EXISTS idx_navwarn_tier
  ON public.nav_warnings (triage_tier);
CREATE INDEX IF NOT EXISTS idx_navwarn_unplotted
  ON public.nav_warnings (unplotted_reason) WHERE unplotted_reason IS NOT NULL;
