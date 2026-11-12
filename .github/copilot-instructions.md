# Copilot & Agent Instructions for Helm.Warning.Backend

When working on this repository, you MUST follow the architectural contracts and safety invariants documented in [agent.md](../agent.md):

1. **Safety Invariant (Rule 0)**: This repository processes official Navigational Warnings (NAVWARNs) under IMO/IHO standards. Spatial accuracy is safety-critical. Never invent coordinates, never clamp out-of-range latitudes/longitudes, and never guess missing hemispheres.
2. **Immutable Provenance (Rule 125)**: Scraped raw bulletin text is hashed with SHA-256 and stored in `public.raw_messages`. `raw_text` in `public.nav_warnings` must remain verbatim from the issuing authority.
3. **Deterministic Parsing**: All coordinate parsing must use `shared/utils.py` and `shared/splitter.py`. Do not write custom coordinate regexes in scrapers or runners.
4. **H02 Triage Precedence Gate**: Tiers A (Auto-Plot), B (Review Queue), and C (Quarantine/Suppressed). Tier C requires a valid `unplotted_reason`.
5. **No Destructive Operations**: A warning missing from a single harvest must never be marked cancelled or deleted unless the harvest represents a credible complete snapshot (`SYNC_CANCEL_MIN_FEED_COUNT`, `SYNC_CANCEL_MIN_FEED_FRACTION`).
6. **Supabase Parsing Audit**:
   - `audit_only` mode makes ZERO database writes of ANY kind (no run-ledger row) and ZERO Gemini calls.
   - `propose_corrections` writes only to `parsing_correction_proposals` with `status = 'pending'`; the Gemini model is verified fail-closed (exit 3 on unknown model) before any database access.
   - `apply_approved` requires `status = 'approved'`, checks UUIDs, blocks geometry/title/date fields, re-validates against raw text, and applies ONLY through the `admin_save_nav_warning` RPC (atomic update + `nav_warning_audits` row in one transaction, optimistic lock, `edited_by_admin` freeze flag). Direct `UPDATE` on `nav_warnings` is forbidden.
   - Foreign keys to `nav_warnings` or `parsing_audit_runs` must use plain `REFERENCES` without `CASCADE`.
7. **Secret Hygiene**: Never log or output `SUPABASE_KEY` or `GEMINI_API_KEY`.
8. **Test Execution**: Before completing tasks, always run `python3 -m unittest discover tests`.



## B4 publication and rollout invariants

- Tier A requires clean explicit RULE geometry, non-superseded status, and no `has_incomplete_zone` or `has_repairs` flags.
- Keep geometry-bearing partial/repaired/inferred/AI-parsed/otherwise flagged warnings in Tier B. Tier C is reserved for no valid operational geometry and requires a valid `unplotted_reason`.
- Preserve previously accepted geometry when a replacement parse yields no accepted geometry; route the warning to Tier B. Replace old geometry only after valid replacement geometry is accepted.
- Keep corridor clearance and sweep metadata intact through persistence and active spatial publication; the review queue includes active and superseded Tier-B warnings.
- Never rerun the B4 Production migration or bypass database write guards. Use `docs/PRODUCTION_ROLLOUT.md` for verified Production schema facts and current rollout status.
- NAVAREA XIX Sync has failed post-merge with zero jobs. Check its workflow YAML/input indentation and verify a successful rerun before calling ingestion operations fully healthy.