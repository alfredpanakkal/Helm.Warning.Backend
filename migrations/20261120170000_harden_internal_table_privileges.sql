-- Defense-in-depth ACL hardening for internal NAVWARN tables.
--
-- RLS remains the row-access boundary. This migration removes unnecessary
-- table privileges that RLS does not govern (notably TRUNCATE, TRIGGER,
-- REFERENCES and PostgreSQL 17 MAINTAIN), and removes all API-role privileges
-- from service-role-only tables.
--
-- Public read contracts (nav_warnings, geometries, raw_messages, ingestion
-- metadata, snapshots, source registry and public views) are intentionally
-- left unchanged. Admin-only tables retain authenticated grants and policies.
--
-- spatial_ref_sys is deliberately excluded: it is owned by supabase_admin on
-- Free-tier Production. Its Data API writes are guarded separately by
-- private.block_spatial_ref_sys_writes() through pgrst.db_pre_request.

BEGIN;

-- These privileges are not needed by PostgREST clients. Revoke them from the
-- API roles on application tables owned by the migration role. The ownership
-- filter deliberately skips Supabase-managed objects such as spatial_ref_sys.
DO $revoke_non_crud$
DECLARE
    v_relation record;
BEGIN
    FOR v_relation IN
        SELECT c.oid::regclass AS relation_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
          AND c.relname <> 'spatial_ref_sys'
    LOOP
        EXECUTE format(
            'REVOKE TRUNCATE, REFERENCES, TRIGGER, MAINTAIN ON TABLE %s FROM anon, authenticated',
            v_relation.relation_name
        );
    END LOOP;
END;
$revoke_non_crud$;

-- The parser audit, operator audit and ingestion child tables are backend
-- records. Their RLS policies intentionally provide no direct API-role access;
-- service_role is the only supported application access path.
REVOKE ALL PRIVILEGES ON TABLE
    public.nav_warning_audits,
    public.parsing_audit_runs,
    public.parsing_correction_proposals,
    public.nav_warning_cancellations,
    public.nav_warning_schedules
FROM anon, authenticated;

-- Optional/legacy internal tables are not present in every historical schema.
-- Revoke their API-role grants when they exist; never change service_role.
DO $revoke_optional_internal$
DECLARE
    v_table_name text;
    v_relation regclass;
BEGIN
    FOREACH v_table_name IN ARRAY ARRAY[
        'public.raw_artifacts',
        'public.pipeline_logs',
        'public.scraper_runs',
        'public.nav_warning_guard_snapshot',
        'public.nav_warnings_archive_legacy'
    ]
    LOOP
        v_relation := to_regclass(v_table_name);
        IF v_relation IS NOT NULL THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON TABLE %s FROM anon, authenticated',
                v_relation
            );
        END IF;
    END LOOP;
END;
$revoke_optional_internal$;

-- These tables retain authenticated admin-only policies. Remove the redundant
-- anonymous grants without changing authenticated admin access.
REVOKE ALL PRIVILEGES ON TABLE
    public.admin_users,
    public.manual_ingest_queue,
    public.pipeline_runs
FROM anon;

-- Fail the migration if the intended service-only boundary is not actually
-- enforced, or if the service role lost its required access.
DO $assert_service_only$
DECLARE
    v_table_name text;
    v_relation regclass;
BEGIN
    FOREACH v_table_name IN ARRAY ARRAY[
        'public.nav_warning_audits',
        'public.parsing_audit_runs',
        'public.parsing_correction_proposals',
        'public.nav_warning_cancellations',
        'public.nav_warning_schedules',
        'public.raw_artifacts',
        'public.pipeline_logs',
        'public.scraper_runs',
        'public.nav_warning_guard_snapshot',
        'public.nav_warnings_archive_legacy'
    ]
    LOOP
        v_relation := to_regclass(v_table_name);
        IF v_relation IS NULL THEN
            CONTINUE;
        END IF;

        IF NOT (
            SELECT relrowsecurity
            FROM pg_class
            WHERE oid = v_relation
        ) THEN
            RAISE EXCEPTION 'RLS must remain enabled on %', v_table_name;
        END IF;

        IF has_table_privilege('anon', v_relation, 'SELECT')
           OR has_table_privilege('anon', v_relation, 'INSERT')
           OR has_table_privilege('anon', v_relation, 'UPDATE')
           OR has_table_privilege('anon', v_relation, 'DELETE')
           OR has_table_privilege('authenticated', v_relation, 'SELECT')
           OR has_table_privilege('authenticated', v_relation, 'INSERT')
           OR has_table_privilege('authenticated', v_relation, 'UPDATE')
           OR has_table_privilege('authenticated', v_relation, 'DELETE') THEN
            RAISE EXCEPTION 'API-role table privileges remain on service-only table %', v_table_name;
        END IF;

        IF NOT has_table_privilege('service_role', v_relation, 'SELECT')
           OR NOT has_table_privilege('service_role', v_relation, 'INSERT')
           OR NOT has_table_privilege('service_role', v_relation, 'UPDATE')
           OR NOT has_table_privilege('service_role', v_relation, 'DELETE') THEN
            RAISE EXCEPTION 'service_role access was not preserved on %', v_table_name;
        END IF;
    END LOOP;
END;
$assert_service_only$;

DO $assert_admin_only$
BEGIN
    IF has_table_privilege('anon', 'public.admin_users', 'SELECT')
       OR has_table_privilege('anon', 'public.manual_ingest_queue', 'SELECT')
       OR has_table_privilege('anon', 'public.pipeline_runs', 'SELECT') THEN
        RAISE EXCEPTION 'Anonymous SELECT privilege remains on an admin-only table';
    END IF;

    IF NOT has_table_privilege('authenticated', 'public.admin_users', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.manual_ingest_queue', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.pipeline_runs', 'SELECT') THEN
        RAISE EXCEPTION 'Authenticated admin SELECT access was not preserved';
    END IF;
END;
$assert_admin_only$;

COMMIT;
