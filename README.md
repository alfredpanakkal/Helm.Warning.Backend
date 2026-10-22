# Helm Navigational Warning System

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests: 100 Passed](https://img.shields.io/badge/Tests-100%20Passed-brightgreen.svg)](#-test-suites--verification)
[![React: 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![TypeScript: 5.7](https://img.shields.io/badge/TypeScript-5.7-3178c6.svg)](https://www.typescriptlang.org/)
[![PostGIS: 3.x](https://img.shields.io/badge/PostGIS-3.x-0064a5.svg)](https://postgis.net/)
[![TailwindCSS: v4](https://img.shields.io/badge/TailwindCSS-v4-38bdf8.svg)](https://tailwindcss.com/)

An enterprise-grade, consolidated Navigational Warning Operations Console, Scraper, Deterministic Parser, Differential Synchronization Engine, and Hardened PostGIS Backend Architecture. Built to aggregate Maritime Safety Information (MSI) across four international NAVAREA zones.

---

## 🌊 1. Operational Overview

The **Helm Navigational Warning System** harvests, parses, triages, normalizes, and visualizes official Navigational Warnings (NAVWARNs) across four primary international hydrographic authorities:

1. **NAVAREA Baltic Subarea**: Swedish Maritime Administration (*Sjöfartsverket*) — Navigational warning feeds, firing zones, light outages, and buoy drift notices.
2. **NAVAREA I**: United Kingdom Hydrographic Office (*UKHO Admiralty*) — North Atlantic, North Sea, and English Channel navigational hazards.
3. **NAVAREA II**: French Hydrographic and Oceanographic Service (*SHOM / services.ping-info-nautique.fr*) — S-124 SECOM Exchange Sets, GML spatial geometries, and Biscay/West Africa warnings.
4. **NAVAREA XI**: Japan Coast Guard (*JCG Kaiho*) — Western Pacific, East China Sea, and Sea of Japan warnings with complex multipart coordinate clauses.

### Dual-Surface Operating Model
- **Public Mariner Portal (`/`)**: High-contrast, low-bandwidth nautical chart and MSI bulletin repository tailored for mariners at sea over constrained VSAT or satellite links.
- **Operations & Admin Console (`/admin`)**: Mission control dashboard for maritime watchstanders, featuring live pipeline runners, a 4-step bulletin import wizard, bulletin parser studio, review queue for ambiguous notices, and in-browser test runners.

---

## 📐 2. Architecture & Data Flow

```text
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                              UPSTREAM MSI DATA SOURCES                                 │
 │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
 │  │ Baltic (Sweden)  │  │ NAVAREA I (UKHO) │  │  NAVAREA II S124 │  │ NAVAREA XI JCG │  │
 │  │ HTML / Text Feed │  │ Admiralty Portal │  │ SECOM XML / GML  │  │ Kaiho Website  │  │
 │  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  └───────┬────────┘  │
 └───────────┼─────────────────────┼─────────────────────┼─────────────────────┼──────────┘
             ▼                     ▼                     ▼                     ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                          INGESTION & PARSING ENGINE (Python)                           │
 │  • scripts/baltic_parser.py       • scripts/navarea_1_parser.py                        │
 │  • scrapers/navarea_ii.py (S-124) • scripts/navarea_xi_parser.py                       │
 │  • shared/splitter.py             • shared/ai_escalation.py (Gemini 3.1 Flash-Lite)    │
 │  • Coordinate Parser (DMS, DDM, DD, Rules 18/19/20/93, Centroids & Polygons)           │
 └──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                          H02 TRIAGE PRECEDENCE GATE & SAFETY                           │
 │  • Tier A (Auto-Plot): Verified geometry, zero repairs, clean bounds                   │
 │  • Tier B (Review Queue): Repaired coordinates, vessel-filtered, or AI-grounded        │
 │  • Tier C (Quarantine): Missing hemisphere, bounds failure, truncated clause           │
 │  • Canonical ID Generation: '{NAVAREA} {warning_id}' (e.g., 'NAVAREA I 042/26')        │
 └──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                      DIFFERENTIAL SYNC ENGINE (shared/sync_engine.py)                  │
 │  • Computes differential sets: NEW, UPDATE, CANCEL, UNCHANGED                          │
 │  • Circuit breaker state machine (CLOSED -> OPEN -> HALF_OPEN) & Jitter retry          │
 │  • Calls atomic stored procedure: public.upsert_nav_warning(p_payload jsonb)           │
 └──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                      PERSISTENCE & REALTIME LAYER (PostgreSQL / PostGIS)               │
 │  • public.nav_warnings             (Master envelopes, categories TEXT[], triage tiers) │
 │  • public.nav_warning_geometries   (Child geometries, PostGIS geography(Geometry,4326))│
 │  • public.nav_warnings_active_spatial (Inner join view serializing geojson_blob)       │
 │  • public.raw_messages             (Immutable SHA-256 audit ledger)                    │
 │  • Supabase Realtime Publication   (Real-time push: helm-warnings-realtime)            │
 └───────────────────────┬────────────────────────────────────────┬───────────────────────┘
                         │ Realtime WebSockets                    │ Active Spatial Query
                         ▼                                        ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                        REACT 19 / TYPESCRIPT NAUTICAL CONSOLE                          │
 │  ┌─────────────────────────────────────────┐  ┌─────────────────────────────────────┐  │
 │  │           PUBLIC MARINER PORTAL         │  │         OPERATIONS & ADMIN CONSOLE  │  │
 │  │ • Fullscreen Leaflet Chart with PostGIS │  │ • Overview: Health & Ingest Rates   │  │
 │  │   GeoJSON (Polygons, Lines, Points)     │  │ • Pipeline: Synchronizer Terminal   │  │
 │  │ • Marker Clustering & Layer Controls    │  │ • Import: 4-Step Raw Bulletin Wizard│  │
 │  │ • Filterable MSI Bulletin Ledger        │  │ • Verify: Operator Review Queue (B) │  │
 │  │ • Multi-Hazard Badges & GeoJSON Export  │  │ • System: Connectivity & AI Tests   │  │
 │  └─────────────────────────────────────────┘  └─────────────────────────────────────┘  │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 3. Repository Topology

```text
.
├── src/                               # Frontend: React 19, TypeScript, Leaflet, Tailwind CSS v4
│   ├── components/                    # UI Components
│   │   ├── MaritimeMap.tsx            # Leaflet nautical chart with PostGIS GeoJSON & clustering
│   │   ├── WarningList.tsx            # Filterable warnings with export (JSON/GeoJSON) & multi-hazard tags
│   │   ├── WarningDetailModal.tsx     # Full bulletin auditor with SHA-256 and geometry inspector
│   │   ├── PipelineRunnerModal.tsx    # Live pipeline terminal runner simulation
│   │   ├── BulletinParserStudio.tsx   # Interactive raw bulletin AST sandbox
│   │   ├── TestSuiteRunnerModal.tsx   # In-browser test runner modal
│   │   ├── Header.tsx / Navbar.tsx    # Global telemetry, mode toggles, and status badges
│   │   ├── admin/                     # Admin console (Overview, Pipeline, Import, Verify, System)
│   │   └── public/                    # Streamlined public portal for mariners at sea
│   ├── core/                          # Frontend Domain Logic
│   │   ├── classification.ts          # Multi-hazard classifier (firing, aids, wrecks, cables, etc.)
│   │   ├── coordinates.ts             # Coordinate extraction, DMS normalization & GeoJSON generation
│   │   ├── syncEngine.ts              # Frontend differential sync simulation logic
│   │   ├── supabaseClient.ts          # Active-spatial view binding & Realtime subscription
│   │   └── parsers/                   # Regional parsers (baltic, navarea1, navareaXi, sanitizer)
│   ├── data/                          # Offline seed fallback dataset
│   └── types/maritime.ts              # TypeScript domain models and contracts
│
├── shared/                            # Python Backend Core & Hardening Framework
│   ├── sync_engine.py                 # Core differential sync engine & atomic RPC caller
│   ├── models.py                      # TriageTier, DataQuality, CoordinateProvenance & payload builders
│   ├── triage.py                      # H02 Triage Precedence gate & audit logger
│   ├── utils.py                       # Rules 18/19/20/93 coordinate repair & differential calculation
│   ├── splitter.py                    # Multi-bulletin corpus boundary splitter
│   ├── config.py                      # Centralized typed configuration & pre-flight validation
│   ├── exceptions.py                  # Standardized exception hierarchy with error context
│   ├── logging.py                     # Structured JSON logging & audit trail
│   ├── validation.py                  # Coordinate, bounds, token, and schema validation
│   ├── retry.py                       # Exponential backoff retry decorator with jitter
│   ├── circuit_breaker.py             # Circuit breaker state machine (CLOSED/OPEN/HALF_OPEN)
│   ├── cache.py                       # Thread-safe TTL cache with Redis delegation
│   ├── metrics.py                     # Thread-safe Counters, Gauges & Histograms
│   ├── prometheus.py                  # Lightweight Prometheus HTTP server (/metrics)
│   ├── profiling.py                   # cProfile performance tracing decorator
│   └── ai_escalation.py               # Gemini API coordinate grounding and escalation
│
├── scripts/ & scrapers/               # Regional Scrapers, Parsers, and Sync Runners
│   ├── run_all.py                     # Master synchronous pipeline runner with pre-flight checks
│   ├── run_all_async.py               # Concurrent asynchronous pipeline runner across all 4 regions
│   ├── ai_parser.py                   # Hardened Gemini & deterministic fallback warning parser
│   ├── async_scraper.py               # AsyncScraper with semaphore rate-limiting
│   ├── baltic_scraper.py / _parser.py / _sync.py   # Baltic regional ingestion (SMA)
│   ├── navarea_1_scraper.py / _parser.py / _sync.py # NAVAREA I ingestion (UKHO Admiralty)
│   ├── navarea_xi_scraper.py / _parser.py / _sync.py# NAVAREA XI ingestion (JCG Kaiho)
│   └── scrapers/navarea_ii.py         # NAVAREA II S-124 SECOM XML / Exchange Set ingestion (SHOM)
│
├── migrations/                        # PostGIS / PostgreSQL Schema Migrations
│   ├── 20260101_add_triage_columns.sql
│   ├── 20261019_add_categories_column_and_update_view.sql
│   ├── 20261019_global_navarea_pipeline_adapted.sql   # Master-child table normalization
│   ├── 20261020_realtime_and_audit.sql                # Realtime publication, RLS & raw_messages
│   ├── 20261021_restore_anon_read_grants.sql          # Anonymous read permissions
│   └── 20261022_fix_upsert_rpc_feature_type.sql      # Case-safe feature_type mapping in RPC
│
├── tests/                             # Python Test Suites (100 unit, integration & fuzz tests)
│   ├── test_e2e_sync.py               # Differential sync, canonical IDs & atomic payloads
│   ├── test_validation.py             # Input bounds, warning ID, and token validation
│   ├── test_error_handling.py         # Exception hierarchy, context, and retry tests
│   ├── test_circuit_breaker.py        # State transitions and rejection verification
│   ├── test_metrics_and_cache.py      # Metric calculations, Prometheus text, and cache TTL
│   ├── test_property_based.py         # Property-based fuzz tests on 1,000+ randomized coordinates
│   ├── test_baltic.py                 # Baltic parser & polygon centroid assertions
│   ├── test_navarea_1.py              # NAVAREA I parser tests
│   ├── test_navarea_ii.py             # NAVAREA II S-124 parser tests
│   ├── test_navarea_xi.py             # NAVAREA XI parser tests
│   ├── test_repairs_and_triage.py     # Rules 18/19/20/93 and H02 triage precedence
│   ├── test_golden_corpus.py          # Regression tests on golden sample corpus
│   ├── test_ai_escalation.py          # Gemini coordinate grounding and safety assertions
│   └── test_ai_parser.py              # DMS parsing, triage tiers, and AI fallback tests
│
└── .github/workflows/                 # Production CI/CD Scheduled Ingestion Workflows
    ├── all-sync.yml                   # Master scheduled sync
    ├── baltic-sync.yml                # Baltic 15-minute ingestion schedule
    ├── navarea-1-sync.yml             # NAVAREA I schedule
    ├── navarea-xi-sync.yml            # NAVAREA XI schedule
    └── navarea_ii.yml                 # NAVAREA II S-124 schedule
```

---

## 🗄️ 4. PostGIS Database Architecture

The persistence model enforces strict normalization separating the **warning envelope** from its **spatial geometries**:

### Master Table: `public.nav_warnings`
```sql
CREATE TABLE public.nav_warnings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_id text NOT NULL UNIQUE,       -- e.g., 'NAVAREA I 042/26'
    navarea text NOT NULL,                  -- 'NAVAREA I', 'NAVAREA II', 'BALTIC', 'NAVAREA XI'
    title text NOT NULL,
    area_text text,
    categories text[] NOT NULL DEFAULT '{}',-- Multi-hazard categorization
    status text NOT NULL DEFAULT 'active',  -- 'active', 'cancelled', 'draft'
    triage_tier char(1) NOT NULL DEFAULT 'C',-- 'A', 'B', 'C'
    data_quality text NOT NULL DEFAULT 'EXPLICIT',
    parsing_method text NOT NULL DEFAULT 'RULE',
    qa_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
    unplotted_reason text,
    duplicate_of_id uuid REFERENCES public.nav_warnings(id),
    valid_from timestamptz,
    valid_to timestamptz,
    raw_text text NOT NULL,
    source_id text NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
```

### Child Geometry Table: `public.nav_warning_geometries`
```sql
CREATE TABLE public.nav_warning_geometries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    warning_id uuid NOT NULL REFERENCES public.nav_warnings(id) ON DELETE CASCADE,
    zone_label text,
    feature_type text NOT NULL CHECK (
        feature_type IN ('POINT','LINE','POLYGON','CORRIDOR','SWEEP_ARC','BOUNDING_BOX')
    ),
    buffer_nm numeric NOT NULL DEFAULT 0,
    geom_postgis geography(Geometry, 4326) NOT NULL,
    created_at timestamptz DEFAULT now()
);
```

### Active Spatial View: `public.nav_warnings_active_spatial`
High-performance view queried by the client application. Joins master envelopes with geometries, formatting PostGIS features into GeoJSON:
```sql
CREATE OR REPLACE VIEW public.nav_warnings_active_spatial AS
SELECT 
    w.id,
    w.canonical_id,
    w.navarea,
    w.title,
    w.area_text,
    w.categories,
    w.status,
    w.triage_tier,
    w.data_quality,
    w.valid_from,
    w.valid_to,
    w.raw_text,
    g.id AS geometry_id,
    g.zone_label,
    g.feature_type,
    g.buffer_nm,
    ST_AsGeoJSON(g.geom_postgis)::jsonb AS geojson_blob
FROM public.nav_warnings w
INNER JOIN public.nav_warning_geometries g ON w.id = g.warning_id
WHERE w.status = 'active' AND w.triage_tier = 'A';
```

### Atomic Upsert Stored Procedure: `public.upsert_nav_warning`
- Replaces master metadata and replaces child geometries in a **single transaction**.
- Runs with `SECURITY DEFINER SET search_path = public, pg_temp` for privilege safety.
- Normalizes incoming geometry `feature_type` to uppercase values compliant with the database CHECK constraint.
- Ensures the Tier-A invariant: if geometry insertion fails, the warning is safely demoted to Tier C (`unplotted_reason = 'no_valid_geometry'`), preventing phantom records.

---

## 🚦 5. Triage Precedence (H02 Gate)

The ingestion engine evaluates every scraped notice through the deterministic **H02 Triage Precedence Gate** before exposing it to navigation displays:

| Tier | Name | Criteria | Chart Plotting | Operator Action |
| :---: | :--- | :--- | :---: | :--- |
| **A** | **Auto-Plot** | Explicit rule-parsed geometry, zero coordinate repairs, clean bounds, zero QA flags. | ✅ Rendered on Map | Displayed immediately to mariners. |
| **B** | **Review Queue** | Repaired coordinates (Rules 18/19/20/93), vessel-filtered notices, or AI-grounded proposals. | ⚠️ Rendered with Warning Badge | Queued in Admin Console for human sign-off. |
| **C** | **Quarantine** | Missing hemisphere, invalid degrees/minutes, out-of-range bounds, truncated text. | ❌ Suppressed from Map | Retained in audit log with `unplotted_reason`. |

### Coordinate Normalization & Repair Rules
- **Rule 18**: Missing leading zeros in minutes (e.g., `58-5.0N` $\rightarrow$ `58-05.0N`).
- **Rule 19**: Degree-minute concatenation without punctuation (e.g., `5815.0N` $\rightarrow$ `58-15.0N`).
- **Rule 20**: Transposed hemisphere indicators (e.g., `N58-15.0` $\rightarrow$ `58-15.0N`).
- **Rule 93**: Implicit hemisphere inheritance across paired polygon vertex lists.

---

## ⚙️ 6. Configuration & Environment Variables

All services use typed configuration via `shared/config.py` with automatic startup pre-flight validation.

| Variable | Default | Type | Description |
| :--- | :--- | :--- | :--- |
| `SUPABASE_URL` | `""` | `str` | Supabase / PostgreSQL endpoint URL (must start with `http://` or `https://`) |
| `SUPABASE_KEY` | `""` | `str` | Supabase Service Role or API Key (min 20 characters) |
| `ALLOW_DRY_RUN` | `""` | `bool` | Set to `1` or `true` to run ingestion safely without live database credentials |
| `SUPABASE_TIMEOUT` | `30` | `int` | Database operation timeout in seconds |
| `NAVWARN_FEED_MODE` | `escalate_and_continue` | `str` | Ingestion mode: `escalate_and_continue` (quarantine invalid) or `strict_abort` |
| `MIN_FEED_SIZE_FOR_CANCEL` | `5` | `int` | Safety threshold required before allowing mass cancellation |
| `MAX_WARNING_AGE_DAYS` | `30` | `int` | Historical age limit for pruning active warnings |
| `GEMINI_API_KEY` | `""` | `str` | Google Gemini API Key for ambiguous coordinate escalation |
| `GEMINI_MODEL_NAME` | `gemini-3.1-flash-lite` | `str` | Gemini model alias used for coordinate grounding |
| `NAVWARN_AI_ENABLED` | `false` | `bool` | Enable AI-assisted coordinate proposal escalation |
| `GEMINI_TIMEOUT_SECONDS` | `10.0` | `float` | Network timeout for Gemini API calls |
| `LOG_LEVEL` | `INFO` | `str` | Application log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FILE` | `None` | `str` | Path to rotating log file (optional; defaults to stdout) |
| `REDIS_HOST` | `None` | `str` | Optional Redis host for distributed caching (falls back to memory) |
| `REDIS_PORT` | `6379` | `int` | Redis connection port |
| `PROMETHEUS_PORT` | `8000` | `int` | HTTP port exposing Prometheus `/metrics` and `/health` |

---

## 🚀 7. Execution & Development Guide

### 1. Frontend Development

```bash
# Install NPM dependencies
npm install

# Start Vite development server (port 3000)
npm run dev

# Compile TypeScript and build production bundle
npm run build

# Run TypeScript linter
npm run lint
```

### 2. Backend Ingestion Pipelines

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run all 4 regional pipelines synchronously with pre-flight checks:
python3 scripts/run_all.py

# Run all 4 regional pipelines concurrently via asyncio:
python3 scripts/run_all_async.py

# Run individual regional pipelines:
python3 scripts/run_baltic.py       # Baltic Sea (SMA)
python3 scripts/run_navarea_1.py    # NAVAREA I (UKHO)
python3 scrapers/navarea_ii.py      # NAVAREA II (SHOM S-124 SECOM)
python3 scripts/run_navarea_xi.py   # NAVAREA XI (JCG Kaiho)

# Run AI and fallback parser standalone:
python3 -m scripts.ai_parser
```

#### Pipeline Process Exit Codes
- **`0`**: 100% sync success across all target regions.
- **`2`**: Missing `SUPABASE_URL` or `SUPABASE_KEY` without `ALLOW_DRY_RUN=1`.
- **`3`**: Ingestion or synchronization failure in one or more regions.

### 3. Test Suites & Verification

The test harness provides **100 automated tests** covering parsing, repair rules, triage gates, error handling, circuit breakers, caching, empty harvest resilience, AI coordinate extraction, and property-based fuzz testing:

```bash
# Run all unit, integration, and fuzz tests:
python3 -m unittest discover tests

# Run specific test modules:
python3 -m unittest tests/test_e2e_sync.py           # Differential sync & RPC payload tests
python3 -m unittest tests/test_validation.py         # Bounds & regex validation
python3 -m unittest tests/test_circuit_breaker.py    # State machine & tripping thresholds
python3 -m unittest tests/test_property_based.py     # 1,000+ randomized coordinate fuzz tests
python3 -m unittest tests/test_repairs_and_triage.py # Repair rules & H02 precedence
python3 -m unittest tests/test_navarea_ii.py        # S-124 SECOM XML parser assertions
```

---

## ⏱️ 8. CI/CD Ingestion Workflows

Automated GitHub Actions workflows keep the database updated on dedicated schedules:

| Workflow File | NAVAREA Region | Frequency | Source Authority |
| :--- | :--- | :--- | :--- |
| `.github/workflows/baltic-sync.yml` | Baltic Subarea | Every 15 minutes | Swedish Maritime Administration |
| `.github/workflows/navarea-1-sync.yml` | NAVAREA I | Every 30 minutes | UK Hydrographic Office (UKHO) |
| `.github/workflows/navarea_ii.yml` | NAVAREA II | Every 30 minutes | France SHOM S-124 SECOM |
| `.github/workflows/navarea-xi-sync.yml` | NAVAREA XI | Every 30 minutes | Japan Coast Guard (Kaiho) |
| `.github/workflows/all-sync.yml` | All 4 Regions | Hourly / Manual | Concurrent Async Orchestrator |

---

## 🛡️ 9. Reliability & Fault-Tolerance Framework

1. **Circuit Breakers (`shared/circuit_breaker.py`)**:
   - Protects network requests and AI escalation services from cascading failures.
   - States: `CLOSED` $\rightarrow$ `OPEN` (tripped after $N$ consecutive failures) $\rightarrow$ `HALF_OPEN` (allows probe requests to verify recovery).
2. **Exponential Jitter Retry (`shared/retry.py`)**:
   - Wraps transient network operations with randomized exponential backoff ($2^n \pm \text{jitter}$), avoiding thundering-herd scenarios.
3. **Structured JSON Audit Logs (`shared/logging.py`)**:
   - Emits standardized JSON lines with UTC ISO-8601 timestamps, module paths, function names, and line numbers.
4. **Lightweight Prometheus Server (`shared/prometheus.py`)**:
   - Exposes real-time metrics on port 8000:
     - `warnings_scraped_total`, `warnings_parsed_total`, `sync_operations_total`
     - `circuit_breaker_failures_total`, `cache_hits_total`, `http_request_duration_seconds`
5. **Multi-Layer Caching (`shared/cache.py`)**:
   - In-memory thread-safe TTL cache with automatic fallback to Redis when configured.

---

## 📜 10. Standards & Compliance

- **IHO S-124 / S-100**: Implements spatial schema interoperability for electronic navigational warnings.
- **SOLAS Chapter V**: Conforms to International Maritime Organization (IMO) requirements for the transmission of Maritime Safety Information.
- **WGS-84 Coordinate Standard**: Standardized EPSG:4326 PostGIS geography representation across all visual and analytical outputs.

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
