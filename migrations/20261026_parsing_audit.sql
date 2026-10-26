-- migrations/20261026_parsing_audit.sql
-- Persistent audit history and AI correction proposals.
-- Does not alter or delete existing NAVAREA warnings.

CREATE TABLE IF NOT EXISTS public.parsing_audit_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN (
            'running', 'succeeded', 'partial', 'failed'
        )),
    mode text NOT NULL
        CHECK (mode IN (
            'audit_only', 'propose_corrections', 'apply_approved'
        )),
    navarea_filter text,
    model_name text,
    expected_count integer,
    examined_count integer NOT NULL DEFAULT 0,
    issue_count integer NOT NULL DEFAULT 0,
    proposal_count integer NOT NULL DEFAULT 0,
    applied_count integer NOT NULL DEFAULT 0,
    failed_count integer NOT NULL DEFAULT 0,
    scan_complete boolean NOT NULL DEFAULT false,
    report jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.parsing_correction_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_run_id uuid NOT NULL
        REFERENCES public.parsing_audit_runs(id),
    warning_record_id uuid NOT NULL
        REFERENCES public.nav_warnings(id),
    canonical_id text NOT NULL,
    navarea text,
    field_name text NOT NULL,
    original_value jsonb,
    proposed_value jsonb,
    raw_evidence text,
    explanation text NOT NULL,
    confidence numeric
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    validation jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'approved', 'rejected',
            'applied', 'stale', 'failed'
        )),
    reviewed_by text,
    reviewed_at timestamptz,
    applied_at timestamptz,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parsing_audit_runs_started
    ON public.parsing_audit_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_parsing_audit_runs_status
    ON public.parsing_audit_runs (status);

CREATE INDEX IF NOT EXISTS idx_parsing_proposals_run
    ON public.parsing_correction_proposals (audit_run_id);

CREATE INDEX IF NOT EXISTS idx_parsing_proposals_warning
    ON public.parsing_correction_proposals (canonical_id);

CREATE INDEX IF NOT EXISTS idx_parsing_proposals_pending
    ON public.parsing_correction_proposals (status, created_at)
    WHERE status = 'pending';

ALTER TABLE public.parsing_audit_runs
    ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.parsing_correction_proposals
    ENABLE ROW LEVEL SECURITY;

-- No public SELECT, INSERT, UPDATE or DELETE policies.
-- Use the existing trusted backend/service-role access pattern.
-- Never expose the service-role key in the frontend.
