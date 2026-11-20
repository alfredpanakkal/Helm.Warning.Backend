-- Complete security-invoker coverage for the remaining public warning views.
--
-- The active-spatial and review-queue views are covered by
-- 20261113_views_security_invoker.sql. These two views also need to execute
-- with caller privileges so their behavior cannot bypass base-table RLS.
-- Existing public SELECT grants and policies are intentionally unchanged.

BEGIN;

ALTER VIEW public.nav_warnings_archive
    SET (security_invoker = true);

ALTER VIEW public.nav_warnings_unverified_spatial
    SET (security_invoker = true);

DO $assert$
DECLARE
    archive_options text[];
    unverified_options text[];
BEGIN
    SELECT reloptions INTO archive_options
    FROM pg_class
    WHERE oid = 'public.nav_warnings_archive'::regclass;

    SELECT reloptions INTO unverified_options
    FROM pg_class
    WHERE oid = 'public.nav_warnings_unverified_spatial'::regclass;

    IF NOT COALESCE(archive_options @> ARRAY['security_invoker=true'], false) THEN
        RAISE EXCEPTION 'nav_warnings_archive is not security_invoker';
    END IF;

    IF NOT COALESCE(unverified_options @> ARRAY['security_invoker=true'], false) THEN
        RAISE EXCEPTION 'nav_warnings_unverified_spatial is not security_invoker';
    END IF;

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
       OR NOT has_table_privilege('anon', 'public.nav_warnings_archive', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.nav_warnings_archive', 'SELECT')
       OR NOT has_table_privilege('anon', 'public.nav_warnings_unverified_spatial', 'SELECT')
       OR NOT has_table_privilege('authenticated', 'public.nav_warnings_unverified_spatial', 'SELECT') THEN
        RAISE EXCEPTION 'Public archive and unverified view SELECT privileges must remain available';
    END IF;
END;
$assert$;

COMMIT;
