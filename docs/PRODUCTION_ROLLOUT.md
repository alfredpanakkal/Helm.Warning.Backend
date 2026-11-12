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
