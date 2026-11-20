# AGENT DIRECTIVES & GUIDELINES

See [agent.md](agent.md) for the complete, authoritative knowledge base covering:
- Architectural philosophy and core invariants (Rule 0, Rule 125 immutable provenance, Rule 31 bathymetry sentinel, coordinate repair rules 18/19/20/93).
- Strict bounds enforcement (no coordinate clamping, no guessing hemispheres).
- H02 Triage Precedence Gate (Tiers A, B, C).
- PostGIS Master-Child schema, atomic RPC contracts, and plain `REFERENCES` foreign key standards.
- Supabase Parsing Audit & AI Correction Engine (`audit_only`, `propose_corrections`, `apply_approved` modes with keyset pagination, atomic conditional updates, and zero secret logging).
- Test execution commands and contributor safety guardrails.

See [docs/DECISION_LOG.md](docs/DECISION_LOG.md) for *why* each safety rule exists (incident-rooted decision log) and where each validator sits from scrape to publication. When a PR adds or changes a safety rule, append its reason there in the same PR.


## B4 publication contract and Production rollout

- The Python Tier-A publication gate requires clean explicit RULE-parsed operational geometry, non-superseded status, and no review-required QA flags. Only `geometry_basis:*` is informational; every other non-empty QA flag requires review. The current SQL CHECK is narrower; parity guard was merged in PR #113; its migration was validated in Prototype but has not been applied to Production.
- Geometry-bearing warnings that fail Tier-A conditions belong in Tier B; Tier C is only for warnings with no valid operational geometry and requires a valid `unplotted_reason`.
- Preserve existing child geometry when a replacement parse yields no accepted geometry; route the warning to Tier B and retain the preservation QA flag until a healthy replacement is accepted.
- Preserve corridor and sweep metadata through the RPC and active spatial view. The review queue includes active and superseded Tier-B warnings.
- Production B4 migration and the 2026-11-13 read-only audit are recorded in [`docs/PRODUCTION_ROLLOUT.md`](docs/PRODUCTION_ROLLOUT.md) and [`docs/READ_ONLY_AUDIT_20261113.md`](docs/READ_ONLY_AUDIT_20261113.md). Do not rerun migrations blindly or bypass write guards.
- The NAVAREA XIX post-merge workflow currently has a failed run with zero jobs; inspect/fix its workflow definition and verify a successful rerun before declaring the ingestion fleet healthy.

## 2026-11-13 backend follow-up rules

- An atomic warning upsert must fail closed if `upsert_nav_warning` fails. Never fall back to a direct `nav_warnings` table write that can leave master and geometry rows inconsistent (PR #112).
- Treat the SQL QA-flag parity guard in PR #113 as **proposed**, not applied. Preserve existing Production Tier-A exceptions for individual evidence review; never bulk-demote or rewrite them. The initial 2026-11-13 snapshot counted 28; a later read-only refresh returned 25 distinct rows (12 active, 13 non-active). See `docs/READ_ONLY_AUDIT_20261113.md` for both snapshots.
- `spatial_ref_sys` direct privilege revocation (PRs #115/#127) is ineffective on Free-tier Production because `supabase_admin` owns the PostGIS table. Production uses the PostgREST pre-request guard recorded in `docs/PRODUCTION_ROLLOUT.md`; it is API-layer protection, not PostgreSQL ACL revocation.
- The additive legacy `sources_registry` compatibility migration was merged in PR #116; it has not been applied to Production. Retain legacy columns and records.
- The 2026-11-13 SQL snapshot is not a full parser audit. A complete `audit_only` workflow report and isolated PostGIS RPC round-trip remain outstanding.
- All follow-up PRs are review-only until the maintainer chooses to merge them. No PR is to be merged automatically.

- PR #118 proposes `security_invoker = true` on both public warning views while preserving current grants and policies; it is not applied to Production.