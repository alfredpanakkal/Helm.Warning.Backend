# Helm.Warning.Backend — Decision Log & Validator Map

> **Why this file exists:** The README and [agent.md](../agent.md) document *what* every
> safety rule is. This file records *why* each rule exists — the incident, root cause, or
> reasoning behind it — so future maintainers (human or AI) do not "simplify" a rule that
> is actually load-bearing. When you add a rule, add its reason here in the same PR.
>
> Phase 6 WP8 (documentation). Evidence-based: every entry below traces to a verified
> incident, a live-source quirk, or a maintainer decision.

---

## 1. Validator placement — scrape to publication

Where each deterministic check sits. One warning passes through every stage; a check
belongs to the earliest stage that has the data it needs.

| # | Stage | File(s) | What is enforced |
|---|-------|---------|------------------|
| 1 | Fetch | `scripts/*_scraper.py` | Fail-closed harvest: fetch errors, empty pages, wrong-content guards abort **before** the raw text is archived or synced. Politeness: pauses, retry/backoff, stop-on-429, per-run request caps, circuit breaker. |
| 2 | Raw preservation | `shared/sync_engine.py` → `public.raw_messages` | Verbatim text + SHA-256 checksum stored before any transformation (Rule 125). Any past state can be re-parsed losslessly. |
| 3 | Boundary split | `shared/splitter.py` | Multi-message bulletins segmented; CANCEL cross-references must not split or phantom blocks. |
| 4 | Coordinate parse & repair | `shared/utils.py` (Rules 18/19/20/93), `shared/geometry_classifier.py` | Deterministic repair of typographical quirks only. **No hemisphere guessing, no clamping.** Rig lists always classify as points. |
| 5 | Bounds enforcement | `shared/utils.py` | Latitude [-90, 90], longitude [-180, 180]. Out-of-range stays out-of-range (NaN / INVALID) and the row is filtered from the map — never clamped to the edge. |
| 6 | Classification | `shared/navarea_universal_text.py` + per-region parsers | Categories, triage tier. ONE shared parse path for every region — no second parser. |
| 7 | Triage gate | `shared/triage.py` (H02) | Tier A auto-plot / B review queue / C quarantine, with `unplotted_reason`. |
| 8 | Differential sync | `shared/sync_engine.py` | Canonical-ID matching; evidence-based cancel guard (credible-snapshot thresholds); never deletes. |
| 9 | Atomic upsert | `public.upsert_nav_warning` RPC | Master + child geometries in one transaction; empty re-parse preserves previous geometry (`geometry_preserved_previous_run`). |
| 10 | Publication | PostGIS views | Active-only spatial views feed the portal; quarantined rows never reach the map. |
| 11 | Retrospective audit | `scripts/audit_supabase_parsing.py` (`audit_only`) | Deterministic re-validation of stored rows: bounds, hemisphere, GeoJSON validity (via `st_asgeojson` computed column — geometry-blind audits are a known failure mode), canonical-ID dedup, Tier A invariants, Rule 31 sentinel. Read-only, keyset-paginated, `scan_complete` honesty flag. |

**Future (Phase 5 WP6, deferred):** validators from stage 11 reused *at ingest time* on the
publish path — same functions, no duplication, deterministic only, failures route to
review, never auto-published.

---

## 2. Decision log — why each rule exists

### Never guess a hemisphere; never clamp coordinates
**Why:** a guessed or clamped position plots a *false* hazard at a wrong location, or hides
a real one. A wrong-but-confident marker is strictly more dangerous than no marker.
Ambiguous coordinates stay flagged for review; out-of-range values (e.g. 91°N) are kept
as-is in the data and filtered from the map, so evidence of the source error is never
destroyed.

### Rule-parsed is not "verified"
**Why:** the parser originally stamped `confidence_level: 'VERIFIED'` on rule-parsed points
— but the safeguard says only a human verifies. Renamed to `RULE_PARSED` (PR #42) so the
label cannot imply human sign-off that never happened.

### Rig lists always plot as points (maintainer rule, 2026-10-28)
**Why:** "FOLLOWING RIGS STATIONED IN AREA BOUNDED BY …" previously produced a fabricated
Polygon (rigs are not an area) and "RIG UNDER TOW ALONG TRACKLINE" a LineString. A rig list
is a set of discrete positions. Implemented as a first-precedence rule in the shared
classifier so **all** regions inherit it with no per-scraper edits.

### Never delete history; evidence-based cancellation only
**Why:** upstream portals fail, truncate, and rate-limit. If absence-from-one-scrape meant
"cancelled", a single partial harvest would deactivate real live hazards. Cancellation
requires a credible snapshot (minimum count + fraction thresholds); otherwise missing rows
are `unobserved` and stay active. Expiry is only ever driven by the warning's own
`valid_to`.

### Geometry preservation on empty re-parse
**Why:** a transient parsing failure must not erase an active hazard boundary. If a re-parse
yields no valid geometry but the DB had one, the previous geometry is kept, a flag is added,
and the row stays operator-visible instead of silently losing its shape.

### Verbatim raw text + SHA-256 (Rule 125)
**Why:** the source of record for every dispute. Audits, corrections, and re-parsing always
compare against immutable evidence, not against a derived intermediate.

### One shared parse path (no second parser)
**Why:** the rig-list fix, prosign-header tolerance, and every future wording fix must apply
to every region on its next run. Per-region parsing forks would mean the same bug fixed N
times — and one of them always getting missed.

### Prosign-header tolerance (NAVAREA IX, warning 376/23)
**Why:** some 2023-era NHO files use the legacy WWNWS `(.)` separator. The scraper + parser
rejected the header of a *correct, advertised* document and failed the whole run. Fix was
additive optional matching — plain-form headers unaffected.

### Loud skips, request caps, stop-on-429 (NAVAREA IX)
**Why:** the source's WAF rate-limits aggressively. One unreachable document must not abort
an otherwise-good harvest (loud skip), unbounded fetching must not hammer the source (cap,
pause, stop-on-first-429), and a failed run must never leave the DB deactivated
(upsert-only, no cancel pass on partial runs).

### Fail-closed AI (Gemini) — everywhere
**Why (model):** a deprecated/renamed model must never be silently substituted. The model ID
is verified against the API before any DB access; verification failure aborts the run.
**Why (allowlist):** AI may propose only non-lifecycle fields (`categories`,
`triage_tier`, `data_quality`, `unplotted_reason`). `title`, `status`, dates, and
geometry are lifecycle-authoritative and owned by the sync engine and human admins.
**Why (gates):** high confidence alone never authorizes a write; proposals need explicit
human approval (`status='approved'`) plus workflow `confirm_apply` plus the
`production-corrections` environment. Apply goes only through the atomic
`admin_save_nav_warning` RPC with optimistic locking and audit row in one transaction —
direct `UPDATE nav_warnings` is forbidden.

### `audit_only` makes zero DB writes — including no ledger row
**Why:** the audit must be usable as a *verification* tool with absolutely no side effects;
a run that writes anything invites "the audit changed the thing it was auditing".

### Green ≠ complete
**Why:** the audit script exits 0 on partial scans by design (partial results are still
useful). The scheduled-run alert step (Phase 5 PR #58) exists precisely because a green
Actions check does not mean the scan finished; `scan_complete=false` must fail scheduled
runs so the failure email fires.

### Fixtures are asserted byte-exact, and every confirmed failure adds one
**Why:** the 15 universal-format fixtures were once deleted from main while their tests
remained — CI stayed red and nobody knew why. Restored byte-exact from git history. Rule:
when CI reports missing files, check git history first. Growing rule: no parser PR merges
without a fixture reproducing any confirmed failure (Phase 5 WP5).

### Never re-run migrations blindly
**Why:** live DB state has drifted ahead of the repo before (guards applied live, migration
file written later). Always check migration history / current schema first, and treat repo
migrations as records of intent, not commands to re-execute.

### Scheduling around the quiet window; concurrency group
**Why:** IX runs 04:30, III 06:30, VII 08:30 (weekdays), and all-sync every 6h — DB counts
shift constantly. Read-comparison tools (audits) belong in the ~09:00–11:30 UTC weekday
window, and the concurrency group stops a scheduled run overlapping a manual one.

---

## 3. Adding a new decision to this log

When a PR introduces or changes a safety rule, lifecycle behaviour, or an operational
convention, append a short entry: **rule, why (incident or reasoning), where it lives
(file), and the PR number.** If you cannot state the why, the rule is not understood well
enough to merge.
