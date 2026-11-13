-- Align the database Tier-A QA gate with shared.models.qa_flags_require_review().
--
-- geometry_basis:* is the only informational QA flag family. Every other
-- non-empty flag requires review and must not be newly assigned to Tier A.
--
-- Existing Tier-A rows include legacy/manual QA flags. Do not mass-demote or
-- rewrite them here. The trigger permits unrelated updates to unchanged legacy
-- rows, while blocking inserts and changes to triage_tier/qa_flags that would
-- newly publish a flagged warning as Tier A. Historical exceptions require
-- individual evidence review before any cleanup.

BEGIN;

CREATE OR REPLACE FUNCTION public.qa_flags_require_review(p_qa_flags jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog, public
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.jsonb_array_elements_text(
            CASE
                WHEN pg_catalog.jsonb_typeof(p_qa_flags) = 'array'
                    THEN p_qa_flags
                ELSE '[]'::jsonb
            END
        ) AS flag(value)
        WHERE flag.value IS NULL
           OR (
               flag.value <> ''
               AND flag.value NOT LIKE 'geometry_basis:%'
           )
    );
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

    -- Legacy Tier-A exceptions already exist. Allow unrelated edits to those
    -- rows, but do not allow a new row or a changed publication gate to create
    -- or perpetuate a newly changed Tier-A QA violation.
    IF TG_OP = 'INSERT' THEN
        RAISE EXCEPTION
            'Tier A warnings cannot carry review-required QA flags'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.triage_tier IS DISTINCT FROM OLD.triage_tier
       OR NEW.qa_flags IS DISTINCT FROM OLD.qa_flags THEN
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

-- Executable migration assertions for the same policy cases covered in Python.
DO $assert$
BEGIN
    IF public.qa_flags_require_review('[]'::jsonb) THEN
        RAISE EXCEPTION 'empty QA flags must be informational';
    END IF;
    IF public.qa_flags_require_review('["geometry_basis:keyword:rig"]'::jsonb) THEN
        RAISE EXCEPTION 'geometry_basis flags must remain informational';
    END IF;
    IF NOT public.qa_flags_require_review('["COORD_COUNT_MISMATCH"]'::jsonb) THEN
        RAISE EXCEPTION 'coordinate mismatch must require review';
    END IF;
    IF NOT public.qa_flags_require_review('[null]'::jsonb) THEN
        RAISE EXCEPTION 'JSON null QA flags must require review';
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

COMMIT;
