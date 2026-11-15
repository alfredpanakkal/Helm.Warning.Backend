-- Audited, severity-only maintenance path.
-- Does not call the general admin save RPC and cannot modify geometry or lifecycle fields.
BEGIN;

CREATE OR REPLACE FUNCTION public.admin_set_nav_warning_severity(
    p_warning_id uuid,
    p_severity text,
    p_expected_updated_at timestamptz,
    p_operator text DEFAULT 'severity-backfill',
    p_reason text DEFAULT 'Recomputed from stored source bulletin using canonical resolver'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_before public.nav_warnings%ROWTYPE;
    v_after public.nav_warnings%ROWTYPE;
BEGIN
    IF p_severity IS NULL OR p_severity NOT IN ('critical', 'high', 'moderate') THEN
        RAISE EXCEPTION 'INVALID_SEVERITY' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_before
      FROM public.nav_warnings
     WHERE id = p_warning_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'WARNING_NOT_FOUND' USING ERRCODE = 'P0404';
    END IF;

    IF v_before.updated_at IS DISTINCT FROM p_expected_updated_at THEN
        RAISE EXCEPTION 'STALE_UPDATED_AT' USING ERRCODE = 'P0409';
    END IF;

    IF v_before.severity IS NOT DISTINCT FROM p_severity THEN
        RETURN jsonb_build_object('warning_id', p_warning_id, 'changed', false, 'severity', v_before.severity);
    END IF;

    UPDATE public.nav_warnings
       SET severity = p_severity, updated_at = now()
     WHERE id = p_warning_id
     RETURNING * INTO v_after;

    INSERT INTO public.nav_warning_audits (
        warning_id, operator_id, action, reason,
        previous_tier, new_tier, signature_hash, diff_patch
    ) VALUES (
        p_warning_id,
        COALESCE(NULLIF(p_operator, ''), 'severity-backfill'),
        'SEVERITY_BACKFILL',
        p_reason,
        v_before.triage_tier,
        v_after.triage_tier,
        encode(convert_to(p_warning_id::text || ':' || clock_timestamp()::text, 'UTF8'), 'base64'),
        jsonb_build_object(
            'field', 'severity', 'old', v_before.severity, 'new', v_after.severity,
            'source', 'raw_text+categories', 'method', 'determine_hazard_severity'
        )
    );

    RETURN jsonb_build_object(
        'warning_id', p_warning_id, 'changed', true,
        'old_severity', v_before.severity, 'severity', v_after.severity,
        'updated_at', v_after.updated_at
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.admin_set_nav_warning_severity(uuid, text, timestamptz, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.admin_set_nav_warning_severity(uuid, text, timestamptz, text, text) TO service_role;

COMMIT;
