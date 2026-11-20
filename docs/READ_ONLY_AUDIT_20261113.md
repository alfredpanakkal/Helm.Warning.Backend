# Production read-only audit — 2026-11-13

**Project:** `helm.apps`  
**Method:** direct read-only SQL against Production metadata and data tables.  
**Writes performed:** none. No migrations, RPC writes, tier changes, flag edits, geometry repairs, or source-registry updates were performed.

This is a bounded SQL snapshot, not a replacement for the repository's complete `scripts.audit_supabase_parsing --mode audit_only` run. The manual GitHub workflow was inspected but not dispatched from this connection.

## 1. Warning and triage inventory

| Measure | Result |
|---|---:|
| `nav_warnings` rows | 900 |
| Active Tier A | 491 |
| Active Tier B | 4 |
| Active Tier C | 59 |
| Active Tier A with no geometry | 0 |
| Active Tier C with geometry | 0 |

The status/tier distribution was:

| Status | Tier A | Tier B | Tier C |
|---|---:|---:|---:|
| active | 491 | 4 | 59 |
| cancelled | 197 | 1 | 43 |
| expired | 95 | 0 | 7 |
| superseded | 0 | 2 | 1 |

The four active Tier-B rows have operational geometry. The active Tier-C rows have no geometry, consistent with the quarantine contract.

## 2. Geometry integrity and metadata

| Measure | Result |
|---|---:|
| Geometry rows | 1,925 |
| Point geometries with non-zero `buffer_nm` | 478 |
| Null geometry values | 0 |
| Invalid PostGIS geometries | 2 |
| Invalid geometries attached to active warnings | 0 |
| Wrong SRID | 0 |
| Invalid feature types | 0 |
| Negative buffers | 0 |
| Non-null `corridor_half_width_nm` | 0 |
| Non-null `corridor_clearance_nm` | 0 |
| Non-null `sweep_radius_nm` | 0 |
| Non-null sweep azimuths | 0 |

The two invalid polygons are both on cancelled NAVAREA VIII warnings:

- `NAVAREA VIII 1079/26` — self-intersection near 71.3227E, 19.5742N.
- `NAVAREA VIII 961/26` — self-intersection near 71.3887E, 19.4804N.

They are historical records. No geometry was repaired or deleted. There are currently no active Tier-A invalid geometries in this snapshot.

The corridor/sweep columns exist, but no current geometry rows populate them. This is a data-coverage observation, not proof that the persistence code is broken; source coverage and future real examples still need verification.

## 3. Tier-A QA-flag parity discrepancy

Production contains 783 Tier-A rows. Of these, **28 carry one or more non-informational QA flags** under the Python `qa_flags_require_review()` rule. Only `geometry_basis:*` is informational in that rule.

Observed combinations:

| QA flag combination | Rows |
|---|---:|
| `geometry_preserved_previous_run` | 12 |
| `COORD_COUNT_MISMATCH` + `geometry_basis:*` | 7 |
| `ai_correction_applied` + `edited_by_admin` | 3 |
| `verified_by_admin` | 2 |
| `RIG_AREA_CONFLICT` + `geometry_basis:*` | 2 |
| `geometry_basis:*` + `verified_by_admin` | 1 |
| `geometry_preserved_previous_run` + `verified_by_admin` | 1 |

The PR #113 description lists the `COORD_COUNT_MISMATCH` + `geometry_basis:*` family in three separate entries (4 + 2 + 1) because the underlying informational geometry-basis values differ. This report groups those entries by the review-policy family, giving 7 rows. Both breakdowns total 28; there is no count discrepancy.

The existing SQL CHECK only blocks `has_incomplete_zone` and `has_repairs`, so it reports zero violations while Python classifies these 28 rows as requiring review.

**No historical rows were demoted.** PR [#113](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/113) proposes a database guard for new/changed publication decisions while allowing unrelated updates to unchanged legacy rows. The 28 exceptions require individual evidence review before any cleanup.

## 4. Raw-message provenance

| Measure | Result |
|---|---:|
| `raw_messages` rows | 3,863 |
| Missing SHA-256 checksum | 7 |
| Warnings with no matching raw-message row under canonical-ID or numeric-ID matching | 11 |

All seven missing checksums belong to manual sources:

- `manual-navarea-x`: 4
- `manual-navarea-xix`: 3

All eleven warnings without a matching raw-message row under the matching rule are cancelled records created on 2026-10-20 or 2026-10-21 (NAVAREA I, NAVAREA XI, and Baltic). There are no active warnings in this unmatched set.

Do not fabricate checksums or raw-message rows. The manual ingestion path and the historical provenance gap need separate review.

## 5. Source registry schema drift

Production `public.sources_registry` currently has six columns:

`source_id, region, publisher, url, status, warning_count`

The table has zero rows. `region` is NOT NULL. The backend migration `20261112_rpc_write_security_and_sources_registry.sql` uses `CREATE TABLE IF NOT EXISTS`, which does not add its declared columns when a legacy table already exists.

The current frontend's `syncSourcesToSupabase()` payload also uses a richer `SourceRegistryItem` contract (`publisher_id`, `publisher_name`, `navareas`, `scope`, `discovery_url`, `format`, `publication_semantics`, `enabled`, `verification`, `health`, etc.). PR [#116](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/116) proposes additive compatibility columns and makes the legacy `region` field optional without deleting legacy fields or rows.

No source rows were inserted or updated.

## 6. Client privilege and view review

- `anon` and `authenticated` currently have direct INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, and MAINTAIN privileges on `public.spatial_ref_sys`.
- PUBLIC has SELECT only on that table.
- PR [#115](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/115) proposes revoking client privileges and restoring SELECT only, leaving `service_role` unchanged.
- PR [#118](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/118) proposes `security_invoker = true` for both public views. It preserves current public SELECT grants and policies, but ensures future RLS changes are respected.
- `nav_warnings_active_spatial` and `nav_warnings_review_queue` have public SELECT grants and no `security_invoker` reloption. The underlying warning and geometry tables also intentionally have public SELECT policies/grants for the public map/data bank. Therefore this observation is a view/RLS design review item, not by itself evidence of additional data exposure. Do not revoke access until the frontend's public/admin contract is confirmed.

## 7. Migration ledger

Production `supabase_migrations.schema_migrations` contains eight entries, ending at `20261005113949`. The live schema includes later changes that the maintainer separately confirmed were applied, so the ledger is not a complete record of the current schema state.

Do not infer that every migration after 2026-10-05 is unapplied. Do not rerun migrations or manually edit the ledger. Reconcile each migration against actual schema, function, policy, and grant state before proposing any repair.

## 8. Remaining verification gates

1. Run the full `audit_only` GitHub workflow and retain its complete report artifact. This was not dispatched here; the connected GitHub actions exposed read-only workflow inspection but no workflow-dispatch action. The SQL snapshot above is not a parser-vs-source comparison.
2. Run a true geometry RPC round-trip test against an isolated PostGIS test database. PR [#114](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/114) adds payload and SQL mapping regression tests, not a live database round-trip.
3. Validate and eventually run the corrected NAVAREA XIX workflow. PR [#111](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/111) has passing Unit tests, but dispatching it against Production would run ingestion and was not attempted.
4. Individually review the 28 Tier-A QA-flag exceptions and two cancelled invalid polygons; no automatic edits.
5. Reconcile source-registry schema and the incomplete migration ledger only after reviewing the relevant PRs and the actual deployment target.

## 9. Open backend PRs — none merged

| PR | Scope | Unit tests |
|---|---|---|
| [#111](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/111) | NAVAREA XIX artifact upload input indentation | Passed |
| [#112](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/112) | Fail closed on atomic RPC failure; remove non-atomic fallback | Passed |
| [#113](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/113) | Python/database QA-flag policy parity | Passed |
| [#114](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/114) | Geometry metadata payload/mapping tests | Passed |
| [#115](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/115) | Revoke client writes to `spatial_ref_sys` | Passed |
| [#116](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/116) | Additive source-registry schema compatibility | Passed |
| [#118](https://github.com/alfredpanakkal/Helm.Warning.Backend/pull/118) | Make warning views security-invoker | Passed after correcting a test assertion that had matched an explanatory comment |

All eight PRs were draft/open at the time of this report, and all eight Unit tests workflows passed. PR #118 had one initial test-only failure; the assertion was corrected and its subsequent run passed. No PR was merged and no database migration was applied.

## 10. Read-only Tier-A QA-flag inventory refresh — 2026-11-13

A later read-only Production query using the Python review-policy predicate (`NULL` or any non-empty flag other than `geometry_basis:*`) returned **25 distinct Tier-A warnings**, comprising **12 active** and **13 non-active** warnings. This is a refreshed result; the earlier 28-row figure in sections 3 and 8 is the count from the initial snapshot, not a claim about the later query. The refresh does not identify which records account for the difference, so retain the original snapshot as historical evidence and use the latest row-level query for any subsequent manual review.

The flag-level aggregation returned 29 flag occurrences across those warnings because some warnings carry more than one review-required flag. Do not interpret the occurrence total as a warning count. No warning rows, tiers, flags, or geometry were changed.



---

## Backend follow-up status — 2026-11-20

The 2026-11-13 audit snapshot above remains historical and has not been refreshed. The related implementation PRs subsequently merged to `main`: #111 (NAVAREA XIX artifact-upload configuration), #112 (fail-closed atomic persistence), #113 (Python/SQL QA-flag parity), #114 (geometry metadata regression tests), #115 (client privilege reduction on `spatial_ref_sys`), and #116 (legacy `sources_registry` compatibility).

Merge status is not deployment status: PR #113's migration was validated in Prototype only; PRs #115 and #116 have not been applied to Production. No Production data or schema changes are recorded by this documentation update. PR #118 remains open for caller-RLS warning-view security.

The full `audit_only` report and isolated PostGIS RPC round-trip remain outstanding. The NAVAREA XIX workflow fix merged in #111 still requires a safely controlled successful execution before the ingestion fleet is declared healthy.
