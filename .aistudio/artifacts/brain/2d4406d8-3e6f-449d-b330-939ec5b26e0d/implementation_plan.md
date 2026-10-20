# Implementation Plan: End-to-End Scraper-to-Supabase & Realtime Propagation (v24)

## 1. Executive Summary & Context

This implementation plan delivers a production-grade, schema-aligned data ingestion and real-time visualization pipeline across all 4 maritime regions (**NAVAREA I**, **NAVAREA II**, **NAVAREA XI**, and the **Baltic Sea**).

### Ground Truth Architecture
- **Master Envelope (`public.nav_warnings`)**: Master records keyed uniquely on `canonical_id` (e.g., `NAVAREA I 042/26`, `NAVAREA II 0123/26`, `BALTIC 0014/26`), carrying multi-hazard `categories TEXT[]`, `triage_tier` (`'A'`, `'B'`, `'C'`), `data_quality`, `valid_from/valid_to`, and triage provenance.
- **Child Geometries (`public.nav_warning_geometries`)**: Normalized geometries storing PostGIS `geography(Geometry, 4326)` referencing `nav_warnings(id)`, with `feature_type`, `buffer_nm`, and `zone_label`.
- **Spatial View (`public.nav_warnings_active_spatial`)**: High-performance `INNER JOIN` of `nav_warnings` and `nav_warning_geometries` filtering on `status = 'active' AND triage_tier = 'A'`.
- **Atomic Persistence**: Executed via the `public.upsert_nav_warning(p_payload jsonb)` RPC (`SECURITY DEFINER SET search_path = public, pg_temp`) to guarantee transactional integrity between master records and child geometry layers.
- **Supabase Realtime & RLS**: Explicit Row-Level Security enabled on base tables with public `SELECT` policies for `anon` and `authenticated` roles, published to `supabase_realtime` and listened to by dual-table hooks in the frontend.
- **Frontend Active-Spatial Binding**: Directly queries `nav_warnings_active_spatial` to render authoritative `geojson_blob` PostGIS geometries and multi-category badges on Leaflet maps and data views.

---

## 2. Target File Modifications & Creations

| Phase | File Path | Status | Purpose |
| :--- | :--- | :--- | :--- |
| **Phase 1** | `migrations/20261020_realtime_and_audit.sql` | **New** | Forward migration: Realtime publication, RLS policies, `raw_messages` table, triage column fix (`duplicate_of_id UUID`), review queue view update, and atomic `upsert_nav_warning` RPC with safe date casting. |
| **Phase 2** | `shared/models.py` | **Modify** | Updates `TriageRecord.to_db_row()` to derive regional `canonical_id = f"{navarea} {base.get('warning_id', '')}".strip()`, assigns `triage_tier = 'A'` for plotted geometry, and formats `categories TEXT[]`. |
| **Phase 2** | `shared/sync_engine.py` | **New** | Unified ingestion engine: pre-maps `warning_id` to `canonical_id` before differential matching, safe ISO date normalization, atomic RPC upsert, audit logging, and exit code `2` for missing credentials. |
| **Phase 3** | `scripts/navarea_1_sync.py` | **Modify** | Replaces old flat-schema column filtering with `shared.sync_engine.sync_region()`. |
| **Phase 3** | `scripts/navarea_xi_sync.py` | **Modify** | Replaces old flat-schema column filtering with `shared.sync_engine.sync_region()`. |
| **Phase 3** | `scripts/baltic_sync.py` | **Modify** | Replaces old flat-schema column filtering with `shared.sync_engine.sync_region()`. |
| **Phase 4** | `scrapers/navarea_ii.py` | **Modify** | Removes obsolete `navarea_sync_logs` write and fake `severity` column; calls atomic `upsert_nav_warning` RPC; eliminates silent error suppression. |
| **Phase 4** | `scripts/run_all_async.py` | **Modify** | Adds NAVAREA II to concurrent task pool, aggregates regional metrics, and exits with code 2/3 on failures. |
| **Phase 5** | `src/core/supabaseClient.ts` | **Modify** | Refactors `fetchLiveNavWarnings` to query `nav_warnings_active_spatial`, maps `geojson_blob` into `spatial`, and adds `subscribeToNavWarningsRealtime`. |
| **Phase 5** | `src/components/MaritimeMap.tsx` | **Modify** | Renders `geojson_blob` / GeoJSON shapes directly alongside point centroids and multi-hazard badges. |
| **Phase 5** | `src/App.tsx` | **Modify** | Wires dual Realtime subscription with spatial view re-fetch and VSAT 60s fallback polling. |
| **Phase 6** | `tests/test_e2e_sync.py` | **New** | Full automated regression suite testing payload structures, canonical IDs, triage tiers, credential-missing exit codes, and RPC active spatial view output. |

---

## 3. Step-by-Step Implementation Sequence

### Phase 1: Forward Migration (Realtime, RLS, Audit & Atomic RPC)
Create `migrations/20261020_realtime_and_audit.sql` (preserving existing migration immutability):
1. **Enable Realtime Publication**:
   ```sql
   ALTER PUBLICATION supabase_realtime ADD TABLE public.nav_warnings;
   ALTER PUBLICATION supabase_realtime ADD TABLE public.nav_warning_geometries;
   ```
2. **Audit Logging Table**:
   ```sql
   CREATE TABLE IF NOT EXISTS public.raw_messages (
       id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
       warning_id text NOT NULL,
       source_id text NOT NULL,
       subject_header text,
       full_raw_text text NOT NULL,
       received_timestamp timestamptz DEFAULT now(),
       checksum_sha256 text NOT NULL,
       UNIQUE (warning_id, source_id, checksum_sha256)
   );
   CREATE INDEX IF NOT EXISTS idx_raw_messages_checksum
       ON public.raw_messages (source_id, checksum_sha256);
   ```
3. **Row-Level Security (RLS) Configuration**:
   ```sql
   ALTER TABLE public.nav_warnings ENABLE ROW LEVEL SECURITY;
   ALTER TABLE public.nav_warning_geometries ENABLE ROW LEVEL SECURITY;
   ALTER TABLE public.raw_messages ENABLE ROW LEVEL SECURITY;

   DO $$ BEGIN
     IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'public read nav_warnings') THEN
       CREATE POLICY "public read nav_warnings" ON public.nav_warnings FOR SELECT TO anon, authenticated USING (true);
     END IF;
     IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'public read geometries') THEN
       CREATE POLICY "public read geometries" ON public.nav_warning_geometries FOR SELECT TO anon, authenticated USING (true);
     END IF;
     IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'public read raw_messages') THEN
       CREATE POLICY "public read raw_messages" ON public.raw_messages FOR SELECT TO anon, authenticated USING (true);
     END IF;
   END $$;
   ```
4. **Fix Triage Columns & Review Queue View**:
   ```sql
   -- Forward reconciliation for duplicate_of_id
   DO $$ BEGIN
     IF EXISTS (
       SELECT 1 FROM information_schema.columns 
       WHERE table_schema = 'public' AND table_name = 'nav_warnings' AND column_name = 'duplicate_of_id' AND data_type = 'text'
     ) THEN
       ALTER TABLE public.nav_warnings DROP COLUMN duplicate_of_id CASCADE;
       ALTER TABLE public.nav_warnings ADD COLUMN duplicate_of_id uuid REFERENCES public.nav_warnings(id);
     END IF;
   END $$;

   CREATE OR REPLACE VIEW public.nav_warnings_review_queue AS
     SELECT 
       id, canonical_id, navarea, title, area_text, categories,
       status, triage_tier, data_quality, parsing_method,
       qa_flags, unplotted_reason, duplicate_of_id, raw_text,
       valid_from, valid_to, created_at, updated_at
     FROM public.nav_warnings
     WHERE triage_tier = 'B' AND status <> 'cancelled';
   ```
5. **Atomic Upsert RPC with Tolerant Date Parsing & CVE-Safe Path**:
   ```sql
   CREATE OR REPLACE FUNCTION public.upsert_nav_warning(p_payload jsonb)
   RETURNS uuid
   LANGUAGE plpgsql
   SECURITY DEFINER
   SET search_path = public, pg_temp
   AS $$
   DECLARE
       v_master      jsonb := p_payload->'master';
       v_geoms       jsonb := p_payload->'geometries';
       v_id          uuid;
       v_valid_from  timestamptz;
       v_valid_to    timestamptz;
       g             jsonb;
   BEGIN
       -- Tolerant date parsing: guard against unparseable free text
       BEGIN
           v_valid_from := NULLIF(v_master->>'valid_from', '')::timestamptz;
       EXCEPTION WHEN OTHERS THEN
           v_valid_from := NULL;
       END;

       BEGIN
           v_valid_to := NULLIF(v_master->>'valid_to', '')::timestamptz;
       EXCEPTION WHEN OTHERS THEN
           v_valid_to := NULL;
       END;

       INSERT INTO public.nav_warnings (
           canonical_id, navarea, title, area_text, categories, status,
           triage_tier, data_quality, parsing_method, qa_flags,
           unplotted_reason, valid_from, valid_to, raw_text, source_id
       ) VALUES (
           v_master->>'canonical_id',
           v_master->>'navarea',
           v_master->>'title',
           v_master->>'area_text',
           COALESCE(ARRAY(SELECT jsonb_array_elements_text(v_master->'categories')), '{}'),
           COALESCE(v_master->>'status', 'active'),
           COALESCE(v_master->>'triage_tier', 'C'),
           COALESCE(v_master->>'data_quality', 'EXPLICIT'),
           COALESCE(v_master->>'parsing_method', 'RULE'),
           COALESCE(v_master->'qa_flags', '[]'::jsonb),
           v_master->>'unplotted_reason',
           v_valid_from,
           v_valid_to,
           v_master->>'raw_text',
           v_master->>'source_id'
       )
       ON CONFLICT (canonical_id) DO UPDATE SET
           title = EXCLUDED.title,
           area_text = EXCLUDED.area_text,
           categories = EXCLUDED.categories,
           status = EXCLUDED.status,
           triage_tier = EXCLUDED.triage_tier,
           data_quality = EXCLUDED.data_quality,
           qa_flags = EXCLUDED.qa_flags,
           valid_from = EXCLUDED.valid_from,
           valid_to = EXCLUDED.valid_to,
           raw_text = EXCLUDED.raw_text,
           updated_at = now()
       RETURNING id INTO v_id;

       -- Replace child geometries atomically
       DELETE FROM public.nav_warning_geometries WHERE warning_id = v_id;

       IF v_geoms IS NOT NULL AND jsonb_array_length(v_geoms) > 0 THEN
           FOR g IN SELECT * FROM jsonb_array_elements(v_geoms)
           LOOP
               INSERT INTO public.nav_warning_geometries (
                   warning_id, zone_label, feature_type,
                   buffer_nm, geom_postgis
               ) VALUES (
                   v_id,
                   g->>'zone_label',
                   COALESCE(g->>'feature_type', 'point'),
                   COALESCE((g->>'buffer_nm')::numeric, 0),
                   ST_GeomFromGeoJSON(g->'geojson')::geography
               );
           END LOOP;
       END IF;

       RETURN v_id;
   END;
   $$;
   ```

---

### Phase 2: Schema-Aware Data Models & Shared Sync Engine
1. **Update `shared/models.py`**:
   - Enhance `TriageRecord.to_db_row()`:
     ```python
     navarea = (base.get("navarea") or "UNKNOWN").upper().strip()
     canonical_id = base.get("canonical_id") or f"{navarea} {base.get('warning_id', '')}".strip()
     ```
   - Automatically assign `triage_tier = 'A'` if plotted geometries exist; otherwise fallback to `'C'` (or `'B'` if review flagged).
   - Ensure `categories` is always exported as a list of strings.
2. **Implement `shared/sync_engine.py`**:
   - **Consistent Keying on `canonical_id`**: Pre-map all scraped warnings and messages before running `compute_differential`:
     ```python
     for w in scraped_warnings:
         cid = w.get("canonical_id") or f"{(w.get('navarea') or navarea_code).upper().strip()} {w.get('warning_id', '')}".strip()
         w["warning_id"] = cid  # Pre-map so compute_differential matches seamlessly on canonical_id
         w["canonical_id"] = cid
     for m in scraped_messages:
         cid = m.get("canonical_id") or f"{(m.get('navarea') or navarea_code).upper().strip()} {m.get('warning_id', '')}".strip()
         m["warning_id"] = cid
         m["canonical_id"] = cid
     ```
   - **Safe ISO Date Normalization**:
     ```python
     def parse_iso_or_none(val: Optional[str]) -> Optional[str]:
         if not val:
             return None
         val_str = str(val).strip()
         # Check standard ISO 8601 patterns
         try:
             dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
             return dt.isoformat()
         except (ValueError, TypeError):
             return None  # Preserves raw text in area_text/raw_text without throwing
     ```
   - **Differential Flow**:
     - Query `nav_warnings` by `source_id` selecting `canonical_id, status, raw_text`.
     - Key `existing_warnings` by `row["canonical_id"]`.
     - Pass pre-mapped warnings and `existing_warnings` to `compute_differential`.
     - For `new` and `update`: build master payload + child geometry list; call `supabase.rpc("upsert_nav_warning", {"p_payload": payload})`.
     - For `cancel`: mark `status = 'cancelled'` on matching `canonical_id`.
     - Upsert audit records into `raw_messages` table.
   - **Loud Exit Codes**: Check `SUPABASE_URL` and `SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY`. If missing, log clearly and immediately `sys.exit(2)`. On unrecoverable error during sync, return `False` (leading to `sys.exit(1)` in runner).

---

### Phase 3: Regional Ingestion Pipeline Refactoring
1. **Refactor `scripts/navarea_1_sync.py`**:
   - Remove obsolete `VALID_NAV_COLUMNS` and legacy flat upserts.
   - Delegate sync to `shared.sync_engine.sync_region(supabase, "ukho-navarea-1", parsed_json, raw_json)`.
2. **Refactor `scripts/navarea_xi_sync.py`**:
   - Delegate sync to `shared.sync_engine.sync_region(supabase, "kaiho-navarea-xi", parsed_json, raw_json)`.
3. **Refactor `scripts/baltic_sync.py`**:
   - Delegate sync to `shared.sync_engine.sync_region(supabase, "sma-baltic-subarea", parsed_json, raw_json)`.

---

### Phase 4: S-124 Pipeline Hardening & Runner Aggregation
1. **Refactor `scrapers/navarea_ii.py`**:
   - Remove non-existent `supabase.table("navarea_sync_logs").insert(...)` write at line ~475.
   - Remove fictional `severity` column from database upserts.
   - Adopt atomic `upsert_nav_warning` RPC for S-124 Exchange Sets.
   - Eliminate silent exception swallowing in SECOM parser and fetch loops; raise or propagate error counts in the summary dictionary.
2. **Update `scripts/run_all_async.py`**:
   - Add `scrapers/navarea_ii.py` to the regional concurrent execution pool alongside NAVAREA I, XI, and Baltic.
   - Aggregate statistics across all 4 regions.
   - Enforce distinct exit codes: exit `0` on 100% success; exit `2` if environment variables/credentials are missing; exit `3` if any regional sync failed.

---

### Phase 5: Frontend Active-Spatial Binding & Realtime Propagation
1. **Refactor `src/core/supabaseClient.ts`**:
   - Update `fetchLiveNavWarnings`:
     - Query `nav_warnings_active_spatial` directly:
       ```typescript
       const { data, error } = await client
         .from('nav_warnings_active_spatial')
         .select('*')
         .order('canonical_id', { ascending: false });
       ```
     - Map view rows to `NavWarning` model:
       - Set `warning_id: row.canonical_id || row.warning_id`
       - Set `categories: Array.isArray(row.categories) && row.categories.length > 0 ? row.categories : ['general']`
       - Map `spatial`: parse `geojson_blob` into GeoJSON feature object, extracting centroid for point coordinates.
   - Add `subscribeToNavWarningsRealtime(onUpdate: () => void)`:
     - Subscribes to channel `'helm-warnings-realtime'` with listeners on `nav_warnings` (`*`) and `nav_warning_geometries` (`INSERT`, `UPDATE`, `DELETE`).
     - Triggers debounced `onUpdate` callback.
2. **Update `src/components/MaritimeMap.tsx`**:
   - Enhance spatial renderer to directly ingest and render `geojson_blob` (Feature / Polygon / LineString / Point / MultiPolygon) with Leaflet `L.geoJSON()`.
   - Ensure multi-category badge labels display correctly in popup cards.
3. **Update `src/App.tsx`**:
   - Connect `subscribeToNavWarningsRealtime` on component mount to re-fetch `fetchLiveNavWarnings` automatically.
   - Maintain a 60-second background polling cycle for VSAT / offline recovery.
   - Clean up Realtime channel on unmount.

---

### Phase 6: Automated Verification & Regression Suite
1. **Create `tests/test_e2e_sync.py`**:
   - **Test 1**: Verify `canonical_id` formation across NAVAREA I, II, XI, and Baltic (`NAVAREA I 042/26`).
   - **Test 2**: Verify Tier A vs Tier C assignment (Tier A when coordinates/geometries are present; Tier C when unplotted).
   - **Test 3**: Verify `parse_iso_or_none` handles ISO strings cleanly and returns `None` for free-text dates (`"2026 HOURS 19 OCT"`) without throwing exceptions.
   - **Test 4**: Verify `compute_differential` cancel keying with pre-mapped canonical IDs.
   - **Test 5 (RPC & View Join)**: Test atomic RPC payload construction against mock/scratch Supabase asserting rows in `nav_warnings`, `nav_warning_geometries`, and active view retrieval.
   - **Test 6 (Loud Credential Failure)**: Regression test verifying that invoking sync without `SUPABASE_URL` or `SUPABASE_KEY` exits with code `2`.
2. **Frontend Compilation & Linting**:
   - Run `compile_applet` and `lint_applet` to confirm zero TypeScript compilation errors.

---

## 4. Verification & Acceptance Criteria
- [ ] `migrations/20261020_realtime_and_audit.sql` runs cleanly and idempotently.
- [ ] RLS policies allow anonymous and authenticated read on `nav_warnings`, `nav_warning_geometries`, and `raw_messages`.
- [ ] `upsert_nav_warning` executes transactionally with `SECURITY DEFINER SET search_path = public, pg_temp` and tolerant date casting.
- [ ] Sync scripts derive `canonical_id`, assign Tier A/C, and upsert via RPC.
- [ ] `scrapers/navarea_ii.py` runs without referencing `navarea_sync_logs` or `severity`.
- [ ] `scripts/run_all_async.py` runs all 4 regions and exits with code `2` if credentials are missing.
- [ ] Frontend displays active warnings fetched from `nav_warnings_active_spatial` and updates via Realtime.
- [ ] `pytest tests/test_e2e_sync.py` passes 100%.
- [ ] `compile_applet` reports successful build.
