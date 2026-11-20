# B4 Production Rollout Record

**Repository:** `alfredpanakkal/Helm.Warning.Backend`  
**Rollout date:** 2026-11-12  
**Merged implementation:** PR #109, commit `0953c6fca00c67c84a6d10d8a2a0b56f444e6e1c`  
**Migration:** `migrations/20261112_triage_contract_alignment.sql`

## 1. Implementation and test evidence

- All implementation PRs, including PR #109, are merged to `main`.
- The merged Unit tests workflow completed successfully on the merge commit; its associated CI run recorded 960 passed and 3 skipped.
- The local complete test run recorded 960 tests and `OK`.
- B4 Prototype integration validation passed 19 assertions across scenarios A–H and removed its seven temporary master rows; geometry children were removed by the FK cascade.
- The Prototype integration script was a temporary local validation artifact and was not committed.
- Existing live E2E tests passed in the local run. Caution: the test named `test_03_anon_readable_and_realtime_published` used the service-role client, so it does not independently prove anonymous/RLS access or realtime publication.

## 2. Production database verification

The maintainer confirmed that the B4 migration was applied to Production. The following read-only checks were subsequently completed:

| Contract | Verified Production result |
|---|---|
| `nav_warning_geometries.corridor_clearance_nm` | Present as `double precision` |
| `chk_tier_a_qa_flags` | Correct CHECK definition; zero existing violating rows |
| Constraint validation | `convalidated = true` |
| `nav_warnings_active_spatial` | `geojson_blob`, `corridor_clearance_nm`, `sweep_radius_nm`, `sweep_start_azimuth`, `sweep_end_azimuth` present |
| `nav_warnings_review_queue` | Expected 14 columns, in expected order |
| `upsert_nav_warning(p_payload jsonb)` | Present; SECURITY DEFINER true; `search_path=public, pg_temp` |

The Tier-A violation query returned zero rows before the constraint was validated. No Production fixture warnings were inserted for this verification.

## 3. Post-merge GitHub Actions status

All listed runs below used the merged `main` commit `0953c6f`.

| Workflow | Result |
|---|---|
| Unit tests | Success |
| NAVAREA X ingestion | Success |
| NAVAREA IX ingestion | Success |
| NAVAREA XII ingestion | Success |
| NAVAREA III ingestion | Success |
| NAVAREA VII ingestion | Success |
| NAVAREA IV ingestion | Success |
| NAVAREA XIX Sync | **Failure — three attempts; zero jobs reported** |

Run links:
- [NAVAREA XIX Sync run 43269819036](https://github.com/alfredpanakkal/Helm.Warning.Backend/actions/runs/43269819036)
- [NAVAREA XIX Sync run 43269131991](https://github.com/alfredpanakkal/Helm.Warning.Backend/actions/runs/43269131991)
- [NAVAREA XIX Sync run 43266879867](https://github.com/alfredpanakkal/Helm.Warning.Backend/actions/runs/43266879867)

### NAVAREA XIX suspected workflow-definition defect

The run API reports a failed workflow with zero jobs, so there are no job logs to establish a runtime failure. Static inspection of `.github/workflows/navarea-xix-sync.yml` shows that the artifact upload step currently has this structure:

- `name: navarea-xix-warnings-data` is nested under `with:`.
- `path:`, `retention-days:` and `if-no-files-found:` appear aligned outside `with:`.

Those three values are action inputs and should be nested under the same `with:` mapping. This is a likely workflow-definition/input indentation defect consistent with a workflow failing before any job is created, but it has not yet been confirmed by GitHub's validation error because no job logs are available.

## 4. Remaining work

- [ ] Correct the indentation of `path`, `retention-days` and `if-no-files-found` under the artifact upload step's `with:` block in `.github/workflows/navarea-xix-sync.yml`.
- [ ] Validate the workflow YAML and inspect the diff before merging the correction.
- [ ] Merge the correction to `main`.
- [ ] Confirm NAVAREA XIX Sync creates a job and completes successfully on the corrected `main` commit.
- [ ] Confirm the next normal scheduled NAVAREA XIX ingestion succeeds.
- [ ] Review the next normal ingestion cycle for Supabase RPC errors, geometry persistence errors, and unexpected triage/publication behavior.

Do not declare the entire ingestion fleet operationally green until the NAVAREA XIX workflow has been corrected and a successful run is confirmed.

## 5. Safety notes

- Do not reapply the B4 migration; Production schema verification is already complete.
- Do not create artificial Production test rows to prove the RPC.
- Do not disable triggers, bypass RLS/write guards, or use SQL Editor workarounds to force data writes.
- Never paste or log Supabase service-role credentials.
- Any further Production data write requires explicit authorization and a scoped, reviewed plan.


---

## 6. Read-only Production follow-up — 2026-11-13

A further read-only SQL snapshot was completed. No Production writes or migrations were performed. Full results and query scope are in [`READ_ONLY_AUDIT_20261113.md`](READ_ONLY_AUDIT_20261113.md).

Key findings:

- 900 warning rows; 491 active Tier A, 4 active Tier B, 59 active Tier C.
- 1,925 geometry rows; two invalid self-intersecting polygons belong to cancelled NAVAREA VIII warnings. No active Tier-A invalid geometry was found.
- 478 point geometries have non-zero `buffer_nm`; corridor/sweep metadata columns currently contain no non-null values.
- Seven raw messages lack checksums (four manual NAVAREA X, three manual NAVAREA XIX); eleven older cancelled warnings have no matching raw-message row under canonical/numeric-ID matching.
- 28 Tier-A warnings carry QA flags that Python considers review-required; the current SQL CHECK does not cover those flags. PR #113 proposes a guard without bulk-changing historical rows.
- Production `sources_registry` has six legacy columns and zero rows; PR #116 proposes additive compatibility.
- `anon` and `authenticated` have direct write privileges on `spatial_ref_sys`; PR #115 proposes read-only client access.
- The migration ledger has eight entries through 2026-10-05; later schema changes were separately applied, so the ledger alone is not authoritative.

### Current open PR verification

PRs #111–#118 all have passing Unit tests workflows. PR #118 had an initial test-only assertion failure, which was corrected; the subsequent run passed. All PRs remain draft/open and unmerged.

### Remaining gates

- Run the full `audit_only` workflow and review its artifact; this connection did not expose a workflow-dispatch action.
- Run a true geometry RPC round-trip against an isolated PostGIS database. PR #114 covers payload and SQL mapping, not live database integration.
- Confirm NAVAREA XIX workflow execution only when it can be safely run after merge; PR #111's Unit tests do not validate a Production ingestion run.
- Individually review historical QA/geometry/provenance exceptions. No bulk corrections are authorized.
- Do not rerun migrations or edit the migration ledger to make it appear current.

- PR #118 separately proposes `security_invoker = true` for both public warning views while preserving current grants and RLS policies; no view option has been changed in Production.


---

## Backend follow-up status — 2026-11-20

The 2026-11-13 audit snapshot above remains historical and has not been refreshed. The related implementation PRs subsequently merged to `main`: #111 (NAVAREA XIX artifact-upload configuration), #112 (fail-closed atomic persistence), #113 (Python/SQL QA-flag parity), #114 (geometry metadata regression tests), #115 (client privilege reduction on `spatial_ref_sys`), and #116 (legacy `sources_registry` compatibility).

Merge status is not deployment status: PR #113's migration was validated in Prototype only; PRs #115 and #116 have not been applied to Production. No Production data or schema changes are recorded by this documentation update. PR #118 remains open for caller-RLS warning-view security.

The full `audit_only` report and isolated PostGIS RPC round-trip remain outstanding. The NAVAREA XIX workflow fix merged in #111 still requires a safely controlled successful execution before the ingestion fleet is declared healthy.
