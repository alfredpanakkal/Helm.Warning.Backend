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
5. Incomplete or malformed zones in a multi-zone notice (e.g. Zone B having only 1 or 2 coordinates where a polygon is expected) are flagged with `has_incomplete_zone` in `qa_flags` and downgrade parent data quality to `AMBIGUOUS`, directing the warning to the Tier B human review queue without corrupting valid companion zones or altering the 4-tuple return contract. Zero database schema migrations or model payload alterations are introduced.

Lives in `shared/navarea_universal_text.py`, `shared/utils.py`, and `tests/test_multi_zone_backend.py`.

---

## 3. Adding a new decision to this log

When a PR introduces or changes a safety rule, lifecycle behaviour, or an operational
convention, append a short entry: **rule, why (incident or reasoning), where it lives
(file), and the PR number.** If you cannot state the why, the rule is not understood well
enough to merge.
