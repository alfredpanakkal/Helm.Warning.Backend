# NAVAREA II S-124 SECOM Ingestion Pipeline with Gemini Flash-Lite Backup

Implements France's PING nautical service integration for NAVAREA II, ingesting IHO S-124 (Ed. 2.0) datasets packaged in S-100 Exchange Sets via IEC 63173-2 (SECOM) REST API, featuring high-speed local XML geometry extraction with intelligent Gemini 2.5 Flash-Lite fallback, adapted into the existing Supabase `nav_warnings` database and orchestrated via GitHub Actions.

## User Review & Critical Decisions

> [!IMPORTANT]
> The following architectural decisions were confirmed during the requirements clarification phase:

- **Confirmed Decision 1 (Database Strategy)**: Adapt S-124 records solely into the existing `nav_warnings` table (with standard columns: `warning_id`, `source_id`, `navarea`, `title`, `issued_text`, `coordinates`, `latitude`, `longitude`, `spatial`, `category`, `status`, `raw_text`, and triage columns). The script will also provide resilient fallback/dual-support for `navarea_warnings` and `navarea_sync_logs` if configured.
- **Confirmed Decision 2 (Target Scope)**: Dedicated backend Python pipeline and GitHub Actions workflow only. No UI or frontend modifications are requested.
- **Confirmed Decision 3 (Hybrid Extraction Architecture)**:
  - **Primary Path**: Local zero-latency XML parser (`xml.etree.ElementTree`) extracting plain text, notice metadata, and converting GML `posList` / `pos` pairs (`lat lon`) into GeoJSON `[lon, lat]`.
  - **Backup Path**: `gemini-2.5-flash-lite` via Google AI Studio (`google-genai` SDK) triggered if local parsing yields no valid geometry or suffers irregular formatting.

---

## 1. Overview & Core Concept

- **What It Does**: Connects to France's SHOM / PING nautical SECOM service (`/secom/navarea_ii_en/v1/object`), retrieves Base64-encoded S-100 Exchange Set zip archives, decompresses them in-memory to access S-124 GML XML files, extracts warning text and vector boundaries (Point, LineString, Polygon), normalizes attributes, and upserts active warnings into Supabase.
- **Target Audience / Persona**: Hydrographic data engineers, maritime operators, and automated backend cron workers monitoring Atlantic and English Channel navigational hazards (NAVAREA II).
- **Key Value**: Replaces brittle HTML scraping with authoritative, standardized IHO S-124 hydrographic data exchange, while maintaining 100% extraction reliability via the local + Gemini hybrid pipeline.

---

## 2. Operator Experience & Workflow

- **Scheduled Ingestion**: GitHub Actions cron runs every 30 minutes (`*/30 * * * *`), automatically polling active notices, decompressing Exchange Sets, and syncing differentials into Supabase.
- **Manual Triggering (`workflow_dispatch`)**: Operators can trigger immediate on-demand synchronization directly from GitHub Actions or CLI (`python scrapers/navarea_ii.py`).
- **Structured CLI & Log Output**: Clear visual feedback detailing exchange set count, dataset IDs processed, fallback invocations (if any), database upsert confirmations, and server audit warnings (`responseText`).

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1: Primary Local XML Extractor + Gemini 2.5 Flash-Lite Backup**
  - *Chosen Approach*: Execute local GML tag parsing first. Only invoke `gemini-2.5-flash-lite` when local extraction produces empty geometries, unparseable GML topologies, or malformed notice clauses.
  - *Why*: Delivers near-instantaneous execution and zero API cost for standard notices, while ensuring zero data loss when dealing with complex, nested, or edge-case S-124 structures.
  - *Alternatives Considered*: Pure Gemini LLM parsing on every notice (unnecessary latency and quota usage) or pure regex/XML parsing (fails on non-standard nested GML topologies).

- **Decision 2: Adaptation to Existing `nav_warnings` Schema**
  - *Chosen Approach*: Map S-124 fields directly into existing `nav_warnings` table rows (`source_id: "shom-navarea-2"`, `navarea: "NAVAREA II"`), computing standard triage fields (`triage_tier: "A"`, `data_quality: "EXPLICIT"` when geometry exists), with `spatial` GeoJSON representation and coordinate tokens.
  - *Why*: Keeps the entire system unified under the existing multi-area architecture and query models without requiring migration overhead.

---

## 4. Technical Architecture & Data Strategy

```
┌────────────────────────────────────────────────────────┐
│               GitHub Actions (Cron Trigger)            │
│         .github/workflows/navarea_ii.yml               │
└──────────────────────────┬─────────────────────────────┘
                           │ (1) Polling Request
                           ▼
┌────────────────────────────────────────────────────────┐
│              PING SECOM REST API Endpoint              │
│       GET /secom/navarea_ii_en/v1/object               │
└──────────────────────────┬─────────────────────────────┘
                           │ (2) 200 OK + JSON Payload
                           ▼
┌────────────────────────────────────────────────────────┐
│            Ingestion & In-Memory Unpacking             │
│  - Decode Base64 'data' to io.BytesIO ZIP              │
│  - Extract S-100 Exchange Set (124FR*.gml)             │
│  - Audit server responseText for missing notice IDs    │
└──────────────────────────┬─────────────────────────────┘
                           │ (3) Raw GML XML String
                           ▼
          ┌───────────────────────────────────┐
          │     1. Local S-124 XML Parser     │
          │  - Invert (lat, lon) -> [lon, lat]│
          │  - Extract Point/Line/Polygon     │
          └────────────────┬──────────────────┘
                           │
                 Valid geometry found?
                  /             \
               YES               NO / Missing
                │                 │
                │                 ▼
                │   ┌───────────────────────────────────┐
                │   │  2. Backup: Gemini 2.5 Flash-Lite │
                │   │  - Structured Output via Pydantic │
                │   │  - Extracts geometry & boundaries │
                │   └─────────────┬─────────────────────┘
                │                 │
                └────────┬────────┘
                         │ (4) Normalized Notice Object
                         ▼
┌────────────────────────────────────────────────────────┐
│             Supabase Database (PostgreSQL)             │
│  - UPSERT on public.nav_warnings (warning_id, source_id)
│  - Optional audit entry in public.navarea_sync_logs   │
└────────────────────────────────────────────────────────┘
```

### Module Structure
- `scrapers/navarea_ii.py`: Core ingestion engine containing:
  - `local_s124_extractor`: Fast XML element parser for S-124 nodes (`posList`, `Point`, `Curve`, `Surface`, `Polygon`, `textDescription`).
  - `gemini_flash_lite_backup`: Intelligent fallback using `gemini-2.5-flash-lite` with Pydantic structured output.
  - `adapt_to_nav_warnings`: Formats S-124 payloads into unified `nav_warnings` database rows.
  - `run_navarea_ii_pipeline`: SECOM fetch, decompression, diffing, and Supabase upsert logic.
- `.github/workflows/navarea_ii.yml`: Automated 30-minute cron and manual dispatch workflow.
- `requirements.txt`: Updates dependencies (`requests`, `google-genai>=1.0.0`, `supabase>=2.4.0`, `pydantic>=2.6.0`).
- `tests/test_navarea_ii.py`: Pytest suite verifying GML unpacking, coordinate inversion, fallback execution, and database schema transformation.
