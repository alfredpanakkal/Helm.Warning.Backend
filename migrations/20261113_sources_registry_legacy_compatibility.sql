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

-- The current frontend sync payload supplies navareas/parser metadata in
-- different fields and does not send the backend-only singular navarea or
-- parser_id columns. Keep them optional so a SourceRegistryItem upsert works
-- against both the legacy and fresh-table variants.
DO $backend_optional$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sources_registry'
          AND column_name = 'navarea'
    ) THEN
        ALTER TABLE public.sources_registry
            ALTER COLUMN navarea DROP NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sources_registry'
          AND column_name = 'parser_id'
    ) THEN
        ALTER TABLE public.sources_registry
            ALTER COLUMN parser_id DROP NOT NULL;
    END IF;
END;
$backend_optional$;

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


-- Keep operational numeric invariants identical to the fresh-table contract.
-- NOT VALID avoids failing this compatibility migration because of pre-existing
-- legacy rows; PostgreSQL still enforces each CHECK for new or updated rows.
DO $operational_checks$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.sources_registry'::regclass
          AND conname = 'sources_registry_poll_interval_sec_check'
    ) THEN
        ALTER TABLE public.sources_registry
            ADD CONSTRAINT sources_registry_poll_interval_sec_check
            CHECK (poll_interval_sec > 0) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.sources_registry'::regclass
          AND conname = 'sources_registry_active_warnings_count_check'
    ) THEN
        ALTER TABLE public.sources_registry
            ADD CONSTRAINT sources_registry_active_warnings_count_check
            CHECK (active_warnings_count >= 0) NOT VALID;
    END IF;
END;
$operational_checks$;

DO $assert$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (VALUES ('source_id'), ('publisher_id'), ('publisher_name'),
                     ('navareas'), ('scope'), ('discovery_url'), ('format'),
                     ('publication_semantics'), ('enabled'), ('verification'),
                     ('health'), ('updated_at'))
             AS required(column_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM information_schema.columns AS c
            WHERE c.table_schema = 'public'
              AND c.table_name = 'sources_registry'
              AND c.column_name = required.column_name
        )
    ) THEN
        RAISE EXCEPTION 'Frontend SourceRegistryItem columns are incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (VALUES ('region'), ('navarea'), ('parser_id'))
             AS optional(column_name)
        JOIN information_schema.columns AS c
          ON c.table_schema = 'public'
         AND c.table_name = 'sources_registry'
         AND c.column_name = optional.column_name
        WHERE c.is_nullable <> 'YES'
    ) THEN
        RAISE EXCEPTION 'Frontend-omitted source registry columns must be nullable';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS con
        WHERE con.conrelid = 'public.sources_registry'::regclass
          AND con.contype IN ('p', 'u')
          AND pg_catalog.pg_get_constraintdef(con.oid) LIKE '%(source_id)%'
    ) THEN
        RAISE EXCEPTION 'sources_registry source_id must remain a conflict target';
    END IF;
END;
$assert$;

COMMIT;
