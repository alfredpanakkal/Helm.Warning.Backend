-- Align the database Tier-A QA gate with shared.models.qa_flags_require_review().
--
-- geometry_basis:* is the only informational QA flag family. Every other
-- non-empty flag requires review and must not be newly assigned to Tier A.
--
-- Existing Tier-A rows include legacy/manual QA flags. Do not mass-demote or
-- rewrite them here. The trigger permits unrelated updates to unchanged legacy
-- rows, while blocking inserts and changes to triage_tier/qa_flags that would
-- newly publish a flagged warning as Tier A. Reactivation is also protected:
-- a legacy exception cannot become visible again without review.

BEGIN;

CREATE OR REPLACE FUNCTION public.qa_flags_require_review(p_qa_flags jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog, public
AS $function$
    SELECT CASE
        WHEN p_qa_flags IS NULL THEN false
        WHEN pg_catalog.jsonb_typeof(p_qa_flags) <> 'array' THEN true
        ELSE EXISTS (
            SELECT 1
            FROM pg_catalog.jsonb_array_elements_text(p_qa_flags) AS flag(value)
            WHERE flag.value IS NULL
               OR (
                   flag.value <> ''
                   AND left(flag.value, length('geometry_basis:')) <> 'geometry_basis:'
               )
        )
    END;
$function$;

CREATE OR REPLACE FUNCTION public.enforce_tier_a_qa_flag_parity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
    IF NEW.triage_tier IS DISTINCT FROM 'A'
       OR NOT public.qa_flags_require_review(NEW.qa_flags) THEN
        RETURN NEW;
    END IF;

    -- Legacy Tier-A exceptions may receive unrelated edits, but cannot be
    -- newly inserted, reclassified, assigned changed QA flags, or reactivated.
    IF TG_OP = 'INSERT' THEN
        RAISE EXCEPTION
            'Tier A warnings cannot carry review-required QA flags'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.triage_tier IS DISTINCT FROM OLD.triage_tier
       OR NEW.qa_flags IS DISTINCT FROM OLD.qa_flags
       OR (
           NEW.status = 'active'
           AND NEW.status IS DISTINCT FROM OLD.status
       ) THEN
        RAISE EXCEPTION
            'Tier A warnings cannot carry review-required QA flags'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trg_tier_a_qa_flag_parity ON public.nav_warnings;
CREATE TRIGGER trg_tier_a_qa_flag_parity
BEFORE INSERT OR UPDATE ON public.nav_warnings
FOR EACH ROW
EXECUTE FUNCTION public.enforce_tier_a_qa_flag_parity();

-- Helper-function assertions. SQL NULL matches Python's empty-list behavior;
-- JSON null and all other non-array JSON values fail closed.
DO $assert$
BEGIN
    IF public.qa_flags_require_review(NULL::jsonb) THEN
        RAISE EXCEPTION 'SQL NULL QA flags must not require review';
    END IF;
    IF public.qa_flags_require_review('[]'::jsonb) THEN
        RAISE EXCEPTION 'empty QA flags must be informational';
    END IF;
    IF public.qa_flags_require_review('[""]'::jsonb) THEN
        RAISE EXCEPTION 'empty-string QA flag must remain informational';
    END IF;
    IF public.qa_flags_require_review('["geometry_basis:keyword:rig"]'::jsonb) THEN
        RAISE EXCEPTION 'geometry_basis flags must remain informational';
    END IF;
    IF NOT public.qa_flags_require_review('["geometryXbasis:keyword:rig"]'::jsonb) THEN
        RAISE EXCEPTION 'LIKE wildcard lookalike must require review';
    END IF;
    IF NOT public.qa_flags_require_review('["geometry-basis:keyword:rig"]'::jsonb) THEN
        RAISE EXCEPTION 'hyphenated lookalike must require review';
    END IF;
    IF NOT public.qa_flags_require_review('["COORD_COUNT_MISMATCH"]'::jsonb) THEN
        RAISE EXCEPTION 'coordinate mismatch must require review';
    END IF;
    IF NOT public.qa_flags_require_review('[null]'::jsonb) THEN
        RAISE EXCEPTION 'JSON null QA flag must require review';
    END IF;
    IF NOT public.qa_flags_require_review('null'::jsonb) THEN
        RAISE EXCEPTION 'top-level JSON null must require review';
    END IF;
    IF NOT public.qa_flags_require_review('{"flag":"verified_by_admin"}'::jsonb) THEN
        RAISE EXCEPTION 'JSON object QA flags must require review';
    END IF;
    IF NOT public.qa_flags_require_review('"verified_by_admin"'::jsonb) THEN
        RAISE EXCEPTION 'JSON string QA flags must require review';
    END IF;
    IF NOT public.qa_flags_require_review('["geometry_basis:keyword:rig",null]'::jsonb) THEN
        RAISE EXCEPTION 'mixed informational/JSON null flags must require review';
    END IF;
    IF NOT public.qa_flags_require_review('["geometry_preserved_previous_run"]'::jsonb) THEN
        RAISE EXCEPTION 'preserved geometry must require review';
    END IF;
    IF NOT public.qa_flags_require_review('["geometry_basis:keyword:rig","verified_by_admin"]'::jsonb) THEN
        RAISE EXCEPTION 'mixed informational/review flags must require review';
    END IF;
END;
$assert$;

-- Exercise the real trigger function against a disposable temporary table.
-- This verifies INSERT/UPDATE behavior without writing to nav_warnings.
CREATE TEMP TABLE tier_a_qa_flag_trigger_test (
    id integer PRIMARY KEY,
    triage_tier text NOT NULL,
    qa_flags jsonb,
    status text NOT NULL,
    title text
) ON COMMIT DROP;

CREATE TRIGGER trg_tier_a_qa_flag_parity_test
BEFORE INSERT OR UPDATE ON pg_temp.tier_a_qa_flag_trigger_test
FOR EACH ROW
EXECUTE FUNCTION public.enforce_tier_a_qa_flag_parity();

DO $trigger_assert$
BEGIN
    -- A clean Tier-A insert is accepted.
    INSERT INTO pg_temp.tier_a_qa_flag_trigger_test
        (id, triage_tier, qa_flags, status, title)
    VALUES (1, 'A', '["geometry_basis:keyword:rig"]', 'active', 'clean');

    -- A review-required Tier-A insert is rejected.
    BEGIN
        INSERT INTO pg_temp.tier_a_qa_flag_trigger_test
            (id, triage_tier, qa_flags, status, title)
        VALUES (2, 'A', '["COORD_COUNT_MISMATCH"]', 'active', 'invalid');
        RAISE EXCEPTION 'review-required Tier-A INSERT unexpectedly succeeded';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- A Tier-B row cannot be promoted to Tier A while carrying review flags.
    INSERT INTO pg_temp.tier_a_qa_flag_trigger_test
        (id, triage_tier, qa_flags, status, title)
    VALUES (3, 'B', '["verified_by_admin"]', 'active', 'review');
    BEGIN
        UPDATE pg_temp.tier_a_qa_flag_trigger_test
           SET triage_tier = 'A'
         WHERE id = 3;
        RAISE EXCEPTION 'review-required Tier-B to Tier-A promotion unexpectedly succeeded';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- A clean Tier-A row cannot acquire a review-required QA flag.
    BEGIN
        UPDATE pg_temp.tier_a_qa_flag_trigger_test
           SET qa_flags = '["COORD_COUNT_MISMATCH"]'
         WHERE id = 1;
        RAISE EXCEPTION 'review-required QA flag update unexpectedly succeeded';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- Simulate a pre-existing legacy exception by disabling only the
    -- disposable test-table trigger during fixture setup.
    ALTER TABLE pg_temp.tier_a_qa_flag_trigger_test
        DISABLE TRIGGER trg_tier_a_qa_flag_parity_test;
    INSERT INTO pg_temp.tier_a_qa_flag_trigger_test
        (id, triage_tier, qa_flags, status, title)
    VALUES (4, 'A', '["verified_by_admin"]', 'expired', 'legacy');
    ALTER TABLE pg_temp.tier_a_qa_flag_trigger_test
        ENABLE TRIGGER trg_tier_a_qa_flag_parity_test;

    -- Unrelated edits to an unchanged legacy exception remain allowed.
    UPDATE pg_temp.tier_a_qa_flag_trigger_test
       SET title = 'legacy title corrected'
     WHERE id = 4;

    -- But changing its QA flags or reactivating it is rejected.
    BEGIN
        UPDATE pg_temp.tier_a_qa_flag_trigger_test
           SET qa_flags = '["geometry_basis:keyword:rig"]'
         WHERE id = 4;
        RAISE EXCEPTION 'legacy QA flag change unexpectedly succeeded';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
    BEGIN
        UPDATE pg_temp.tier_a_qa_flag_trigger_test
           SET status = 'active'
         WHERE id = 4;
        RAISE EXCEPTION 'legacy Tier-A reactivation unexpectedly succeeded';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    -- Deactivation remains permitted.
    UPDATE pg_temp.tier_a_qa_flag_trigger_test
       SET status = 'superseded'
     WHERE id = 4;
END;
$trigger_assert$;

COMMIT;
