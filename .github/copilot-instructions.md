# Copilot & Agent Instructions for Helm.Warning.Backend

When working on this repository, you MUST follow the architectural contracts and safety invariants documented in [agent.md](../agent.md):

1. **Safety Invariant (Rule 0)**: This repository processes official Navigational Warnings (NAVWARNs) under IMO/IHO standards. Spatial accuracy is safety-critical. Never invent coordinates, never clamp out-of-range latitudes/longitudes, and never guess missing hemispheres.
2. **Immutable Provenance (Rule 125)**: Scraped raw bulletin text is hashed with SHA-256 and stored in `public.raw_messages`. `raw_text` in `public.nav_warnings` must remain verbatim from the issuing authority.
3. **Deterministic Parsing**: All coordinate parsing must use `shared/utils.py` and `shared/splitter.py`. Do not write custom coordinate regexes in scrapers or runners.
4. **H02 Triage Precedence Gate**: Tiers A (Auto-Plot), B (Review Queue), and C (Quarantine/Suppressed). Tier C requires a valid `unplotted_reason`.
5. **No Destructive Operations**: A warning missing from a single harvest must never be marked cancelled or deleted unless the harvest represents a credible complete snapshot (`SYNC_CANCEL_MIN_FEED_COUNT`, `SYNC_CANCEL_MIN_FEED_FRACTION`).
6. **Supabase Parsing Audit**:
   - `audit_only` mode makes ZERO writes and ZERO Gemini calls.
   - `propose_corrections` writes only to `correction_proposals` with `status = 'proposed'`.
   - `apply_approved` requires `status = 'approved'`, checks UUIDs, blocks geometry fields, re-validates against raw text, and executes atomic conditional updates.
   - Foreign keys to `nav_warnings` or `audit_runs` must use plain `REFERENCES` without `CASCADE`.
7. **Secret Hygiene**: Never log or output `SUPABASE_KEY` or `GEMINI_API_KEY`.
8. **Test Execution**: Before completing tasks, always run `python3 -m unittest discover tests`.
