-- Ensure public spatial/review views execute with caller privileges and RLS.
--
-- PostgreSQL 17 supports security_invoker views. The base warning and geometry
-- tables currently grant public SELECT for the public map/data-bank contract;
-- this migration does not change that access model or any view grants. It
-- prevents these views from silently bypassing base-table RLS if those policies
-- are tightened in a future reviewed change.

BEGIN;

ALTER VIEW public.nav_warnings_active_spatial
    SET (security_invoker = true);

ALTER VIEW public.nav_warnings_review_queue
    SET (security_invoker = true);

DO $assert$
DECLARE
    active_options text[];
    review_options text[];
BEGIN
    SELECT reloptions INTO active_options
    FROM pg_class
    WHERE oid = 'public.nav_warnings_active_spatial'::regclass;

    SELECT reloptions INTO review_options
    FROM pg_class
    WHERE oid = 'public.nav_warnings_review_queue'::regclass;

    IF NOT COALESCE(active_options @> ARRAY['security_invoker=true'], false) THEN
        RAISE EXCEPTION 'nav_warnings_active_spatial is not security_invoker';
    END IF;

    IF NOT COALESCE(review_options @> ARRAY['security_invoker=true'], false) THEN
        RAISE EXCEPTION 'nav_warnings_review_queue is not security_invoker';
    END IF;

    -- Invoker views rely on caller access to their underlying RLS-protected tables.
    IF NOT COALESCE((
        SELECT relrowsecurity
        FROM pg_class
        WHERE oid = 'public.nav_warnings'::regclass
    ), false) THEN
        RAISE EXCEPTION 'nav_warnings RLS must remain enabled';
    END IF;

    IF NOT COALESCE((
        SELECT relrowsecurity
        FROM pg_class
        WHERE oid = 'public.nav_warning_geometries'::regclass
    ), false) THEN
        RAISE EXCEPTION 'nav_warning_geometries RLS must remain enabled';
    END IF;

    -- Security-invoker execution must retain the existing public read policies.
    -- Keep this assertion scoped to policy identity/role coverage; future
    -- reviewed policy predicates may legitimately narrow visible rows.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'nav_warnings'
          AND policyname = 'public read nav_warnings'
          AND cmd = 'SELECT'
          AND 'anon'::name = ANY(roles)
          AND 'authenticated'::name = ANY(roles)
    ) THEN
        RAISE EXCEPTION 'nav_warnings public SELECT policy must remain available';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'nav_warning_geometries'
          AND policyname = 'public read geometries'
          AND cmd = 'SELECT'
          AND 'anon'::name = ANY(roles)
          AND 'authenticated'::name = ANY(roles)
    ) THEN
        RAISE EXCEPTION 'nav_warning_geometries public SELECT policy must remain available';
    END IF;

    IF NOT has_table_privilege('anon', 'public.nav_warnings', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.nav_warnings', 'SELECT')
       OR NOT has_table_privilege('anon', 'public.nav_warning_geometries', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.nav_warning_geometries', 'SELECT')
       OR NOT has_table_privilege('anon', 'public.nav_warnings_active_spatial', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.nav_warnings_active_spatial', 'SELECT')
       OR NOT has_table_privilege('anon', 'public.nav_warnings_review_queue', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.nav_warnings_review_queue', 'SELECT') THEN
        RAISE EXCEPTION 'Public map and review view SELECT privileges must remain available';
    END IF;
END;
$assert$;

COMMIT;
