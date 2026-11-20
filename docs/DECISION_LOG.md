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

### Range boxes require explicit two-axis TO-range wording (AUSCOAST, Oct 2026)
**Why:** 'IN AN AREA BOUNDED BY <lat> TO <lat> AND <lon> TO <lon>' (live AMSA Part 3) produced
no geometry at all — the pair extractor refuses word-separated axis listings. The bbox helper
now accepts the 'BOUNDED BY' form, but ONLY gated on the explicit TO-joined two-axis ranges
plus exactly two distinct latitudes and longitudes; every other 'BOUNDED BY' wording (corner
enumerations reach the helper only when their pairs failed to extract) fails closed. Lives in
`shared/utils.py` (`_bbox_from_axis_tokens`, `RE_AXIS_*_RANGE`, `RE_BBOX_PHRASE`).

### Sweep sectors need radius + bearings + exactly one position (NAVAREA II 358/26)
**Why:** 'WITHIN 20 MILES OF: <pos> BETWEEN 270 AND 360 DEGREES' plotted a bare centre Point —
the actual danger area (a 20 NM sector from west through north) was invisible. The parser now
builds a sector fan Polygon when ALL THREE elements (radius phrase, bearing range, exactly one
extracted position) are present; marine 'MILES' are nautical miles by coordinator convention,
metres/kilometres convert, and anything ambiguous keeps the Point. The source-stated radius and
bearings ride the report -> Feature properties -> geometry payload so the `sweep_*` columns
can be populated. Lives in `shared/utils.py` (`_sector_from_sweep_wording`),
`scripts/navarea_universal_parser.py` (property propagation),
`shared/models.py` (`build_geometry_payloads`).

### Hazard keywords need context; completion only strips operations (PR #103 follow-up)
**Why:** substring keyword matching filed 'ORIGINAL' as rig, 'PROVIDED' as ROV ops, every
container vessel as drifting, every generic obstruction as a wreck, a distance of '2 CABLES' as a
seabed cable, and any 'ANCHOR' instruction as marine ops. The completion guard also deleted whole
active warnings ('DGPS STATION DISCONTINUED', 'LIGHT BUOY DISCONTINUED'), and one floodlight
mention suppressed an unlit buoy elsewhere in the bulletin. Matching is now contextual, the
completion guard strips only sentences whose subject is an operation, floodlights are handled
per sentence, and `categories` lists canonical categories first with legacy aliases after
(`categories[0]` is always canonical). Empty or unmatched text returns
`['general_chart', 'general']`; cancel/completion-only notices stay `['general']`;
`classify_hazard()` still returns the legacy alias. Lives in `shared/utils.py`; NAVAREA VIII
`category` now goes through `classify_hazard()` like every other parser.

### Complete 16-category legacy alias mapping and contextual UXO guard (PR #103 correction)
**Why:** `classify_hazard()` contracts to always return one of the 7 legacy categories (`electronic`,
`military`, `aton`, `subsea`, `drifting`, `offshore`, `general`). Previously, categories without an
explicit entry in `LEGACY_CATEGORY_ALIASES` (`sar`, `security`, `weather`, `ice`, `restricted`) leaked
their canonical token through `classify_hazard()`, breaking downstream consumers expecting the legacy
vocabulary. The table now explicitly covers all 16 canonical categories with a fail-closed `"general"`
fallback. Additionally, the UXO detector formerly matched bare `EXPLOSIVE` and `ORDNANCE` substrings,
falsely classifying dangerous goods cargo (Class 1 explosives), designated explosive anchorages/berths,
tidal/cartographic references (Ordnance Datum Newlyn, Ordnance Survey), and civil marine blasting as
unexploded ordnance. UXO now requires specific naval munitions / unexploded weapon context (`UNEXPLODED
ORDNANCE`, `SEA MINE`, `TORPEDO`, `WARHEAD`, `DEPTH CHARGE`, `EOD`, bomb disposal). Lives in `shared/utils.py`.

### Advanced geometry, sector sweep generalization, corridor swaths, and relocations (Phase B2)
**Why:** Navigational warnings include directional sector arcs (e.g. firing exercises, danger sectors),
cable/pipe-laying safety corridors, and station relocations. Previously:
1. Sector sweeps only recognized a single phrasing variant, did not handle clockwise wraparound spanning North
($340^\circ \to 020^\circ$), and risked building world-spanning shapes on antimeridian crossings. We generalized
parsing to 5 standard IMO/WWNWS phrasing variations, enforce clockwise arc calculation $\Delta = (end - start) \bmod 360$,
fail closed to Point on zero-width sectors or antimeridian jumps, and handle full-circle ($000 \to 360$) rings.
2. Route clearances ("WIDE BERTH OF 2 NM", "SAFETY CLEARANCE OF 500 METRES") formerly deformed the underlying
route or were ignored. The corridor swath parser preserves raw route track coordinates unaltered, validates
distance units (rejecting bare ambiguous 'M'), and populates `buffer_nm` with `feature_type = 'CORRIDOR'`.
3. Relocation notices ("RELOCATED FROM ... TO ...", "ESTABLISHED IN NEW POSITION ... FORMER DISCONTINUED") formerly
risked averaging old and new positions into a meaningless centroid or connecting them. Coordinates are now
extracted strictly within explicit `FROM`/`FORMER` and `TO`/`NEW` clauses regardless of text order, emitting a GeoJSON
`FeatureCollection` with two distinct `POINT` features (`"New Established Position"` and `"Former Position (Relocated)"`
with `is_ghost: True`), while pinning master record coordinates strictly to the new station.
4. Feature properties (`feature_type`, `buffer_nm`, `sweep_*`) are preserved per-feature across universal/regional
parsers and `build_geometry_payloads()`, with strict validation against GeoJSON geometry types (`SWEEP_ARC`/`BOUNDING_BOX`
-> Polygon, `CORRIDOR` -> LineString, `POINT` -> Point).
Lives in `shared/utils.py`, `shared/models.py`, `scripts/navarea_universal_parser.py`.

### Phase B2 follow-up — geometry safety and metadata persistence (PR #105)
**Why:** Review of the Phase B2 implementation identified edge cases that could create incorrect geometry or lose source metadata.
1. Axis-range and two-corner bounding boxes crossing the antimeridian are split into a `MultiPolygon`; their longitude midpoint is the dateline, never the arithmetic midpoint near Greenwich. Ambiguous axis ordering remains fail-closed.
2. Explicit statute miles convert at 0.868976 NM per statute mile. Unqualified "miles" in maritime warning text retain the established nautical-mile convention; they are not silently reinterpreted.
3. Corridor line geometry keeps `buffer_nm = 0`. A source phrase such as "WIDE BERTH OF 2 NM" does not establish whether 2 NM is total width or each-side clearance, so the source value is retained as `corridor_clearance_nm` and flagged `corridor_width_semantics_ambiguous`. Only explicit "half-width"/"each side" wording populates `corridor_half_width_nm`. Point safety zones continue to use `buffer_nm`.
4. Relocation-intent text without exactly one former and one new position fails closed: no guessed point, centroid, line, or sector is generated; `AMBIGUOUS_RELOCATION` is recorded.
5. The additive migration `20261112_geometry_metadata_persistence.sql` extends the lifecycle-safe `20261023_lifecycle_safety.sql` RPC to persist existing `corridor_half_width_nm` and `sweep_*` columns. It does not add columns and preserves insert-before-delete geometry replacement and previous-geometry retention on failed parses.
6. PR validation relies on the central unit-test workflow introduced by PR #106; regional ingestion workflows remain outside routine PR validation.

Lives in `shared/utils.py`, `shared/models.py`, `scripts/navarea_universal_parser.py`, `migrations/20261112_geometry_metadata_persistence.sql`, and geometry regression tests.

### Multi-zone warning splitting and coordinate isolation (Phase B3)
**Why:** Single navigational bulletins frequently bundle multiple distinct operational areas (e.g. NAVAREA VIII 1139/26 with inline (A)..(D) pipeline areas, or NAVAREA XI with lettered training areas A./B./C.). Previously:
1. `parse_block_geometries()` only segmented line-initial `RE_LETTERED_CLAUSE` (`A. <coord>`), ignoring inline sub-area markers. Notices with `(A) ... (B) ...` or `AREA 1 ... AREA 2 ...` were treated as a single block; their combined coordinates self-intersected into a tangled shape and degraded to a single open LineString.
2. Marker detection in `subarea_marks()` required whitespace immediately after marker labels, failing on punctuation variants like `(A):` or `AREA A:`. Punctuation tolerance (`[\.:]?`) was added to `RE_PAREN_SUBAREA` and `RE_AREA_LABEL` while strictly preserving coordinate lookaheads and monotonic sequence gates ($\ge 2$ labels of same family). Unverified candidate marker families (`ZONE`, `STAGE`, `PART`, `SUB-AREA`) were deliberately excluded without bulletin evidence to prevent false splits.
3. `parse_block_geometries()` did not pass the preamble into `parse_coordinates_detailed()`, causing valid sub-area polygons under "IN AREAS BOUNDED BY:" to lose their governing context and fall back to ambiguous classification. Preamble context propagation restores explicit polygon classification across all constituent zones.
4. If candidate segmentations conflict, the parser fails closed to a single block. Coordinates across discrete zones are strictly isolated with zero cross-contamination.
5. Incomplete or malformed zones in a multi-zone notice (e.g. Zone B having only 1 or 2 coordinates where a bounded polygon is expected) are excluded from the returned operational geometry list; their extracted coordinate text remains available for audit. The parent receives `has_incomplete_zone` in `qa_flags` and data quality degrades to `AMBIGUOUS`; when valid companion geometry exists, the warning remains in the Tier B human review queue. If every zone is incomplete, no operational geometry is emitted and `build_master_payload()` assigns Tier C with `no_valid_geometry`, even when coordinate provenance is retained for audit. Valid `Polygon` and `MultiPolygon` zones are retained. The existing 4-tuple return contract remains unchanged; no database schema migrations or model payload alterations are introduced.
6. Inline marker detection accepts exactly one valid marker family per segmentation. If both parenthesized-letter and `AREA` families independently match, segmentation fails closed rather than combining potentially unrelated labels.

Lives in `shared/navarea_universal_text.py`, `shared/utils.py`, and `tests/test_multi_zone_backend.py`.

---

### Phase B4 — Triage and geometry publication contract alignment

**Why:** Review after Phase B3 found that the record-level triage gate and master payload gate did not enforce identical publication rules. A superseded record could reach Tier A through the legacy triage path; QA markers such as `has_incomplete_zone` were not part of the master payload Tier-A gate; and unsupported quarantine reasons could be emitted despite the database CHECK vocabulary. The active spatial view and parsing audit also omitted persisted sweep metadata, while corridor clearance was present in Python payloads but had no child-table column or RPC persistence path.

1. Both Python triage paths now use the same database-aligned reason vocabulary. Tier C is reserved for records with no valid operational geometry; geometry-bearing inferred, repaired, AI-parsed, incomplete-zone, superseded, partially invalid, or otherwise flagged records route to Tier B. Only clean explicit rule-parsed geometry can reach Tier A. Informational `geometry_basis:*` flags do not by themselves block Tier A.
2. Tier C reasons map deterministically: `MISSING_HEM` -> `missing_hemisphere`, `VALIDATION_FAILED` -> `validation_failed`, otherwise `no_valid_geometry` when no operational geometry survives. Unknown legacy reason values normalize to a database-allowed value.
3. The additive migration adds `corridor_clearance_nm`, adds a NOT VALID database guard against Tier-A `has_incomplete_zone` / `has_repairs` flags for new writes, and appends corridor/sweep metadata to `nav_warnings_active_spatial`. The lifecycle-safe upsert retains insert-before-delete and previous-geometry preservation while persisting corridor clearance.
4. The parsing audit fetches the complete persisted geometry metadata set alongside the PostgREST `geom_geojson` computed column. No live database was modified as part of this implementation.

Lives in `shared/triage.py`, `shared/models.py`, `scripts/audit_supabase_parsing.py`, `migrations/20261112_triage_contract_alignment.sql`, and triage/audit regression tests (Phase B4).

## 3. Adding a new decision to this log

When a PR introduces or changes a safety rule, lifecycle behaviour, or an operational
convention, append a short entry: **rule, why (incident or reasoning), where it lives
(file), and the PR number.** If you cannot state the why, the rule is not understood well
enough to merge.


## B4 Production rollout verification (2026-11-12)

**Rule/contract:** Tier A is limited to clean explicit RULE-parsed operational geometry, non-superseded records, and no blocking `has_incomplete_zone` / `has_repairs` QA flags. Geometry-bearing warnings that fail Tier A remain Tier B; Tier C is reserved for no valid operational geometry. Failed geometry replacement preserves existing geometry and routes the warning to Tier B until a healthy replacement is accepted.

**Why:** Prevent partial-zone parsing, repairs, or transient parse failures from silently publishing uncertain geometry as Tier A or erasing previously accepted operational geometry.

**Where:** `shared/triage.py`, `shared/models.py`, `migrations/20261112_triage_contract_alignment.sql`, `public.upsert_nav_warning`, `public.nav_warnings_active_spatial`, and `public.nav_warnings_review_queue`.

**Production evidence:** the maintainer confirmed the B4 migration was applied. Read-only checks confirmed `nav_warning_geometries.corridor_clearance_nm`, the five expected active-spatial metadata columns, the 14-column review queue, and the SECURITY DEFINER RPC with `search_path=public, pg_temp`. Existing Tier-A rows had zero violations of the new QA guard; the constraint was then validated (`convalidated = true`). No Production fixture writes were used.

**Operational follow-up:** post-merge Unit tests and the triggered NAVAREA X, IX, XII, III, VII and IV workflows succeeded on commit `0953c6f`. NAVAREA XIX Sync failed three times with zero jobs. Static inspection suggests the artifact upload step's `path`, `retention-days` and `if-no-files-found` keys are incorrectly indented outside `with:`; this is a likely cause, not a diagnosis confirmed by logs. Track correction and successful rerun in [`PRODUCTION_ROLLOUT.md`](PRODUCTION_ROLLOUT.md).

---

## 2026-11-13 follow-up decisions and audit findings

### Atomic persistence failure must fail closed (PR #112)

**Rule:** If `upsert_nav_warning(p_payload)` fails, return failure and do not fall back to a direct master-table upsert. Raw-message archival may already have occurred, but the warning master and child geometry must remain atomic.

**Why:** A direct fallback can update `nav_warnings` while leaving `nav_warning_geometries` stale or absent. This violates the master-child persistence contract.

**Where:** `shared/sync_engine.py::upsert_warning_atomic`, `tests/test_e2e_sync.py`. PR #112 adds a regression asserting the table fallback is never called.

### Database QA flags must match the Python publication gate (PR #113)

**Rule:** Only `geometry_basis:*` flags are informational. Any other non-empty QA flag requires review and must not be newly assigned to Tier A.

**Why:** The Production SQL CHECK only blocks `has_incomplete_zone` and `has_repairs`, while Python blocks every non-informational flag. The 2026-11-13 read-only snapshot found 28 Tier-A rows that pass the narrow SQL CHECK but fail the Python policy.

**Where:** `shared.models.qa_flags_require_review`, proposed `migrations/20261113_tier_a_qa_flag_parity.sql`, and `tests/test_tier_a_invariants.py`. The proposed trigger preserves unchanged historical exceptions during unrelated updates. It has not been applied to Production; no automatic historical demotion is authorized.

### PostGIS CRS catalogue is read-only to client roles (PR #115)

**Rule:** `anon` and `authenticated` need SELECT on `public.spatial_ref_sys`, not direct write privileges. Preserve owner and service-role grants.

**Why:** The read-only Production audit found direct client INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER and MAINTAIN privileges on a PostGIS system catalogue.

**Where:** Proposed `migrations/20261113_spatial_ref_sys_client_read_only.sql`. Not applied to Production.

### Source registry schema evolution is additive (PR #116)

**Rule:** Evolve the existing legacy `sources_registry` table by adding the current frontend and backend contract fields; retain legacy columns and data.

**Why:** Production has a six-column table with zero rows. `CREATE TABLE IF NOT EXISTS` does not add fields to an existing table, and the frontend upsert does not send the legacy NOT NULL `region` column.

**Where:** Proposed `migrations/20261113_sources_registry_legacy_compatibility.sql` and `tests/test_sources_registry_compatibility.py`. No source rows are backfilled or changed.

### Read-only historical audit scope (2026-11-13)

**Rule:** Direct SQL snapshots are supplemental only. The complete parser-vs-source audit must use `scripts.audit_supabase_parsing --mode audit_only`, whose contract is zero database writes.

**Why:** The SQL snapshot can identify geometry, provenance, and schema anomalies but cannot reproduce the parser audit's deterministic validation and report coverage checks.

**Where:** [`docs/READ_ONLY_AUDIT_20261113.md`](READ_ONLY_AUDIT_20261113.md). The manual workflow was not dispatched in this session.


### Public warning views should respect caller RLS (PR #118)

**Rule:** Set `security_invoker = true` on `nav_warnings_active_spatial` and `nav_warnings_review_queue`. Preserve current public SELECT grants and base-table policies.

**Why:** The views are owned by `postgres` and currently have no security-invoker option. Invoker mode prevents future RLS tightening from being bypassed by view-owner privileges. PostgreSQL 17.6 supports this option, and the public frontend retains SELECT on the underlying warning/geometry tables.

**Where:** Proposed `migrations/20261113_views_security_invoker.sql` and `tests/test_view_security_migration.py`. Not applied to Production.

### Explicit bounded polygons crossing the antimeridian
**Why:** NAVAREA XI 0504/26 (JCG, 2026-11-09) explicitly defines a 25-vertex North Pacific area crossing the Date Line twice. The planar longitude/latitude ring check treated the ±180° transitions as long segments and rejected the area, causing the parser to emit an open LineString. Explicit bounded-area rings with exactly two crossings of one antimeridian are now unwrapped, clipped at that meridian, and emitted as a two-part MultiPolygon while preserving every source vertex. Unsupported crossing topology fails closed as ambiguous rather than becoming a misleading line. The splitter assumes shortest-longitude transitions and is restricted to compact unwrapped spans under 180 degrees; it does not claim to support global or long-way-around boundaries. Regression coverage checks source-vertex preservation, planar area preservation after unwrapping, eastern and western Date Line crossings, reversed winding, ordinary non-crossing rings, unsupported repeated crossings, and global-span rejection. Axis-aligned range-box handling remains unchanged. Lives in `shared/geometry_classifier.py` and `shared/utils.py`; regression fixture in `tests/test_advanced_geometry_backend.py`.

### Public read-only access to PostGIS SRID metadata (PR #127)

**Rule/contract:** `anon` and `authenticated` may read `public.spatial_ref_sys` but must not insert, update, delete, truncate, add references, or create triggers on it. Keep RLS disabled for this extension metadata table and preserve the SELECT path required by PostGIS.

**Why:** Production privilege inspection found both public roles had all table privileges on the 8,500-row PostGIS SRID metadata table. Public map clients need spatial lookups, not mutation rights. The migration verifies the privilege matrix and runs `ST_Transform(4326 → 3857)` under each public role before commit.

**Where:** `migrations/20261115_spatial_ref_sys_read_only.sql`.

**Production safety:** This PR only adds a migration. It does not apply it, alter Production permissions, change warning records, enable RLS, modify default privileges, or change PostGIS ownership.


### Dotted-line route geometry and operator-review hold (PR #128)

**Rule/contract:** The explicit source phrases "FOLLOWING THE DOTTED LINE" and "ALONG THE DOTTED LINE" identify open route geometry. Where a bulletin labels multiple routes on standalone lines (A, B, etc.) beneath that heading, each route is parsed independently and retains its source label. A QA flag keeps these newly classified routes in Tier B pending operator review; they are not automatically published to Tier A. No coordinates are inferred, joined across labels, or reordered.

**Why:** NAVAREA III 0169/26 explicitly defines two dotted routes (A and B), while 0171/26 defines one dotted route. The previous classifier did not recognise dotted-line wording, and the universal parser did not split standalone route labels, allowing separate route segments to be represented as one fallback shape. NAVAREA IX 440/26 remains ambiguous because its four cable-operation positions do not establish a route or a boundary.

**Where:** `shared/geometry_classifier.py`, `scripts/navarea_universal_parser.py`, and `tests/test_geometry_correctness_gaps.py`.

**Safety:** Parser-only change. It does not update existing Production rows, promote Tier-B warnings, alter raw bulletin text, change lifecycle status, or modify geometry already stored in Supabase.


### Unlabelled single dotted-line routes (follow-up)

**Rule/contract:** When an explicit `ALONG THE DOTTED LINE` / `FOLLOWING THE DOTTED LINE` heading is followed by one route and no source-supplied standalone route label, retain the LineString but leave `sub_area` null. Do not invent the generic `Area` label. Existing labelled multi-route splitting remains unchanged; dotted-line geometry remains Tier B for operator review.

**Why:** The active raw text for NAVAREA III 0171/26 contains the dotted-line heading followed directly by 21 coordinates, with no route label. The parser correctly built the LineString but incorrectly assigned the fallback `Area` label, causing the live dry-run validator to fail. The source label is absent and must remain absent in parsed metadata.

**Where:** `scripts/navarea_universal_parser.py` (`_segment_clauses`) and `tests/test_geometry_correctness_gaps.py`.

**Safety:** Parser and regression-test change only. No Supabase writes, Tier-B promotion, lifecycle/status changes, or geometry edits.

### Read-only live raw-text dry run for dotted-line geometry (PR #129)

**Rule/contract:** Before any production geometry update, run `scripts.dry_run_dotted_line_geometry` through the manual `Dotted-line Geometry Dry Run` workflow. It SELECTs only the three target canonical IDs, reparses stored `raw_text` using the deterministic universal parser, and writes a local JSON artifact only. It never writes to Supabase, creates proposals, calls AI, changes status, or promotes publication tier.

**Expected results:** NAVAREA III 0169/26 produces separate A/B LineStrings with 7/22 coordinates; NAVAREA III 0171/26 produces one 21-coordinate LineString; NAVAREA IX 440/26 remains ambiguous and is rejected if parsed as a line or polygon. The two dotted-line routes must retain `DOTTED_LINE_ROUTE_REVIEW` and Tier B.

**Why:** Unit fixtures establish the parser rule, but the production rows must be checked against their exact stored raw text before considering a data correction. The existing full-dataset parsing audit validates stored rows; it does not re-run this universal parser to generate proposed geometry.

**Safety:** Read-only Supabase SELECT only. No production geometry writes are authorized by this workflow. Any subsequent update requires a separate reviewed and explicitly approved operation.


---

## Backend follow-up status — 2026-11-20

The 2026-11-13 audit snapshot above remains historical and has not been refreshed. The related implementation PRs subsequently merged to `main`: #111 (NAVAREA XIX artifact-upload configuration), #112 (fail-closed atomic persistence), #113 (Python/SQL QA-flag parity), #114 (geometry metadata regression tests), #115 (client privilege reduction on `spatial_ref_sys`), and #116 (legacy `sources_registry` compatibility).

Merge status is not deployment status: PR #113's migration was validated in Prototype only; PRs #115 and #116 have not been applied to Production. No Production data or schema changes are recorded by this documentation update. PR #118 remains open for caller-RLS warning-view security.

The full `audit_only` report and isolated PostGIS RPC round-trip remain outstanding. The NAVAREA XIX workflow fix merged in #111 still requires a safely controlled successful execution before the ingestion fleet is declared healthy.
