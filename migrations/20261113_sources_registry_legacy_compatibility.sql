-- Make the source registry migration compatible with the legacy six-column table.
--
-- Production currently has (source_id, region, publisher, url, status,
-- warning_count), with zero rows. CREATE TABLE IF NOT EXISTS in the earlier
-- source-registry migration does not evolve that existing table. The frontend
-- still upserts its SourceRegistryItem contract, while the backend migration
-- also defines a smaller operational-source contract. Add both contracts
-- additively and retain all legacy columns/data.

BEGIN;

-- The frontend upsert does not send the legacy region column. Keep the column
-- and its existing values, but stop requiring it for new contract-shaped rows.
DO $legacy_region$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sources_registry'
          AND column_name = 'region'
    ) THEN
        ALTER TABLE public.sources_registry
            ALTER COLUMN region DROP NOT NULL;
    END IF;
END;
$legacy_region$;

-- Current frontend SourceRegistryItem fields (JSONB for structured values).
ALTER TABLE public.sources_registry
    ADD COLUMN IF NOT EXISTS publisher_id text,
    ADD COLUMN IF NOT EXISTS publisher_name text,
    ADD COLUMN IF NOT EXISTS navareas jsonb,
    ADD COLUMN IF NOT EXISTS scope text,
    ADD COLUMN IF NOT EXISTS discovery_url text,
    ADD COLUMN IF NOT EXISTS entrypoints text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS allowed_hosts text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS format text,
    ADD COLUMN IF NOT EXISTS languages text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS parser_id text,
    ADD COLUMN IF NOT EXISTS publication_semantics text,
    ADD COLUMN IF NOT EXISTS poll_interval_minutes integer,
    ADD COLUMN IF NOT EXISTS stale_after_minutes integer,
    ADD COLUMN IF NOT EXISTS enabled boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS verification jsonb,
    ADD COLUMN IF NOT EXISTS health jsonb,
    ADD COLUMN IF NOT EXISTS published_generation_id text,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- Also retain the operational columns declared by the backend's
-- 20261112_rpc_write_security_and_sources_registry.sql contract.
ALTER TABLE public.sources_registry
    ADD COLUMN IF NOT EXISTS navarea text,
    ADD COLUMN IF NOT EXISTS poll_interval_sec integer NOT NULL DEFAULT 86400,
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_run_at timestamptz,
    ADD COLUMN IF NOT EXISTS last_status text,
    ADD COLUMN IF NOT EXISTS active_warnings_count integer NOT NULL DEFAULT 0;

DO $assert$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sources_registry'
          AND column_name = 'publisher_name'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sources_registry'
          AND column_name = 'health'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sources_registry'
          AND column_name = 'active_warnings_count'
    ) THEN
        RAISE EXCEPTION 'sources_registry compatibility columns were not created';
    END IF;
END;
$assert$;

COMMIT;
