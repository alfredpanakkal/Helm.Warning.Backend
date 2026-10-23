-- Migration: 20261023_manual_ingest_queue.sql
-- Admin-only bulk paste queue: the admin panel inserts pasted bulletin
-- text here; the manual-ingest GitHub Action drains it (service key,
-- bypasses RLS) and upserts the parsed warnings via the normal pipeline.
-- The frontend NEVER holds a GitHub token or the Supabase service key.

-- 1. Admin allowlist (Supabase Auth user ids)
CREATE TABLE IF NOT EXISTS public.admin_users (
    user_id  uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    added_at timestamptz NOT NULL DEFAULT now()
);

-- 2. Paste queue
CREATE TABLE IF NOT EXISTS public.manual_ingest_queue (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    navarea      text,                    -- admin selection; NULL = auto-detect only
    raw_text     text NOT NULL,
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','processing','done','failed')),
    detected_navarea text,                -- region detected from the text header
    result       text,                    -- outcome message for the admin panel
    created_by   uuid DEFAULT auth.uid(),
    created_at   timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_manual_ingest_queue_status
    ON public.manual_ingest_queue (status, created_at);

-- 3. RLS: admins only (submit + read own queue). No public access.
--    The GitHub Action uses the service key and bypasses RLS.
ALTER TABLE public.admin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.manual_ingest_queue ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'admin_users' AND policyname = 'admins read admin_users') THEN
    CREATE POLICY "admins read admin_users" ON public.admin_users
      FOR SELECT TO authenticated
      USING (EXISTS (SELECT 1 FROM public.admin_users au WHERE au.user_id = auth.uid()));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'manual_ingest_queue' AND policyname = 'admins submit pastes') THEN
    CREATE POLICY "admins submit pastes" ON public.manual_ingest_queue
      FOR INSERT TO authenticated
      WITH CHECK (
        EXISTS (SELECT 1 FROM public.admin_users au WHERE au.user_id = auth.uid())
        AND created_by = auth.uid()
      );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'manual_ingest_queue' AND policyname = 'admins read paste queue') THEN
    CREATE POLICY "admins read paste queue" ON public.manual_ingest_queue
      FOR SELECT TO authenticated
      USING (EXISTS (SELECT 1 FROM public.admin_users au WHERE au.user_id = auth.uid()));
  END IF;
END $$;

-- 4. Realtime so the admin panel sees status changes live
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
    BEGIN
      ALTER PUBLICATION supabase_realtime ADD TABLE public.manual_ingest_queue;
    EXCEPTION WHEN duplicate_object THEN
      NULL;
    END;
  END IF;
END $$;
