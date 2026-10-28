# AGENT DIRECTIVES & GUIDELINES

See [agent.md](agent.md) for the complete, authoritative knowledge base covering:
- Architectural philosophy and core invariants (Rule 0, Rule 125 immutable provenance, Rule 31 bathymetry sentinel, coordinate repair rules 18/19/20/93).
- Strict bounds enforcement (no coordinate clamping, no guessing hemispheres).
- H02 Triage Precedence Gate (Tiers A, B, C).
- PostGIS Master-Child schema, atomic RPC contracts, and plain `REFERENCES` foreign key standards.
- Supabase Parsing Audit & AI Correction Engine (`audit_only`, `propose_corrections`, `apply_approved` modes with keyset pagination, atomic conditional updates, and zero secret logging).
- Test execution commands and contributor safety guardrails.

See [docs/DECISION_LOG.md](docs/DECISION_LOG.md) for *why* each safety rule exists (incident-rooted decision log) and where each validator sits from scrape to publication. When a PR adds or changes a safety rule, append its reason there in the same PR.
