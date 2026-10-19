# Helm Navigational Warning System

Consolidated NAVAREA Navigational Warning Operations Console, Scraper, Deterministic Parser, Differential Synchronization Engine, and Hardened Backend Architecture.

---

## 🌊 Overview

The **Helm Navigational Warning System** integrates maritime safety information (MSI) across multiple international NAVAREA regions:
- **NAVAREA Baltic Subarea**: Swedish Maritime Administration (*Sjöfartsverket*)
- **NAVAREA I**: UK Hydrographic Office (*UKHO Admiralty*)
- **NAVAREA XI**: Japan Coast Guard (*JCG Kaiho*)

The system provides dual-surface operation:
1. **Interactive Nautical Operations Console (React + TypeScript + Leaflet)**: Live hydrographic chart, bulletin detail inspector, visual triage tiering, interactive parser studio, and test runner.
2. **Hardened Ingestion & Sync Engine (Python Backend)**: Scrapers, parsers, coordinate normalization, H02 triage precedence gate, automated quarantine, circuit breakers, structured JSON audit logs, Prometheus metrics, and concurrent asynchronous execution.

---

## 🏗️ System Architecture

```text
.
├── src/                               # React / TypeScript Maritime Console
│   ├── components/                    # UI Components
│   │   ├── MaritimeMap.tsx            # Interactive nautical chart with Leaflet & clustering
│   │   ├── WarningList.tsx            # Filterable warnings with export (JSON/GeoJSON)
│   │   ├── WarningDetailModal.tsx     # Full bulletin auditor with SHA-256 and geometry
│   │   ├── PipelineRunnerModal.tsx    # Live pipeline terminal runner
│   │   ├── BulletinParserStudio.tsx   # Interactive parsing sandbox
│   │   ├── TestSuiteRunnerModal.tsx   # In-browser test runner modal
│   │   └── admin/                     # Admin console and authentication gates
│   ├── core/                          # Frontend Core Logic
│   │   ├── classification.ts          # Maritime hazard classifier
│   │   ├── coordinates.ts             # Coordinate extraction & GeoJSON generation
│   │   ├── syncEngine.ts              # Frontend differential sync logic
│   │   └── parsers/                   # Regional parsers (Baltic, NAVAREA I, NAVAREA XI)
│   └── types/maritime.ts              # TypeScript domain contracts
│
├── shared/                            # Python Backend Core & Hardening Framework
│   ├── config.py                      # Centralized configuration & pre-flight validation
│   ├── exceptions.py                  # Standardized exception hierarchy with error context
│   ├── logging.py                     # Structured JSON logging & audit trail
│   ├── validation.py                  # Pydantic & parameter validation schemas
│   ├── retry.py                       # Exponential backoff retry decorator with jitter
│   ├── circuit_breaker.py             # Circuit breaker state machine (CLOSED/OPEN/HALF_OPEN)
│   ├── cache.py                       # Thread-safe TTL cache with Redis delegation
│   ├── metrics.py                     # Thread-safe Counters, Gauges & Histograms
│   ├── prometheus.py                  # Lightweight Prometheus HTTP server (/metrics)
│   ├── sync_modes.py                  # Differential sync safety, batching & guarded cancellation
│   ├── triage.py                      # H02 Triage Precedence gate & audit logger
│   ├── models.py                      # TriageTier, DataQuality, CoordinateProvenance models
│   ├── splitter.py                    # Multi-bulletin corpus boundary splitter
│   ├── utils.py                       # Coordinate parsers, repair rules, and centroid calculation
│   ├── profiling.py                   # cProfile performance tracing decorator
│   └── ai_escalation.py               # Gemini API coordinate grounding and escalation
│
├── scripts/                           # Scrapers, Parsers, and Ingestion Runners
│   ├── run_all.py                     # Master synchronous pipeline runner with pre-flight checks
│   ├── run_all_async.py               # Concurrent asynchronous pipeline runner
│   ├── async_scraper.py               # AsyncScraper with semaphore rate-limiting
│   ├── baltic_scraper.py / _parser.py # Baltic regional ingestion
│   ├── navarea_1_scraper.py / _parser.py # NAVAREA I ingestion
│   └── navarea_xi_scraper.py / _parser.py# NAVAREA XI ingestion
│
└── tests/                             # Python Test Suites (55 unit & property-based tests)
    ├── test_validation.py             # Input bounds, warning ID, and token validation
    ├── test_error_handling.py         # Exception hierarchy, context, and retry tests
    ├── test_circuit_breaker.py        # State transitions and rejection verification
    ├── test_metrics_and_cache.py      # Metric calculations, Prometheus text, and cache TTL
    ├── test_property_based.py         # Property-based fuzz tests on 1,000+ randomized coordinates
    ├── test_baltic.py                 # Baltic parser & polygon centroid assertions
    ├── test_navarea_1.py              # NAVAREA I parser tests
    ├── test_navarea_xi.py             # NAVAREA XI parser tests
    ├── test_repairs_and_triage.py     # Rules 18/19/20/93 and H02 triage precedence
    ├── test_golden_corpus.py          # Regression tests on golden sample corpus
    └── test_ai_escalation.py          # Gemini coordinate grounding and safety assertions
```

---

## ⚙️ Configuration & Environment Variables

All backend components use centralized configuration via `shared/config.py` with automatic startup pre-flight validation.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SUPABASE_URL` | `""` | Supabase project URL (must start with `https://` or `http://`) |
| `SUPABASE_KEY` | `""` | Supabase Service Role or API Key (min 20 characters) |
| `SUPABASE_TIMEOUT` | `30` | Timeout in seconds for Supabase database operations |
| `NAVWARN_FEED_MODE` | `escalate_and_continue` | Ingestion policy: `escalate_and_continue` (quarantine invalid records) or `strict_abort` |
| `MIN_FEED_SIZE_FOR_CANCEL` | `5` | Minimum feed item threshold required before allowing mass cancellation |
| `MAX_WARNING_AGE_DAYS` | `30` | Historical age limit for active warning pruning |
| `GEMINI_API_KEY` | `""` | Google Gemini API Key for coordinate escalation |
| `GEMINI_MODEL_NAME` | `gemini-3.1-flash-lite` | Model name for AI coordinate grounding |
| `NAVWARN_AI_ENABLED` | `false` | Enable AI-assisted coordinate proposal escalation |
| `GEMINI_TIMEOUT_SECONDS` | `10.0` | Timeout in seconds for Gemini API calls |
| `LOG_LEVEL` | `INFO` | Application log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FILE` | `None` | Path to rotating log file (optional; defaults to stdout) |
| `REDIS_HOST` | `None` | Optional Redis host for distributed caching (falls back to memory) |
| `REDIS_PORT` | `6379` | Redis port |
| `PROMETHEUS_PORT` | `8000` | Port for Prometheus HTTP `/metrics` server |

---

## 🛡️ Hardening & Reliability Features

### 1. Robust Input & Schema Validation (`shared/validation.py`)
- Strict coordinate validation: Latitude $\in [-90.0, 90.0]$, Longitude $\in [-180.0, 180.0]$, Minutes $\in [0, 60.0)$. Out-of-bounds coordinates return `NaN`, never clamped.
- Normalized token cleaning and warning ID regex filtering.
- Public function validation decorator (`@validate_public_inputs`) preventing null parameter propagation.

### 2. Standardized Error Handling & Retries (`shared/exceptions.py`, `shared/retry.py`)
- Custom `NavWarnError` base exception capturing contextual metadata dictionaries for immediate debugging.
- Specialized subclasses: `ValidationError`, `ParseError`, `SyncError`, `ConfigurationError`, `CircuitBreakerError`, `CircuitBreakerOpenError`.
- Exponential backoff retry decorator (`@retry`) with configurable jitter and attempt thresholds.

### 3. Structured JSON Logging & Triage Audit Trail (`shared/logging.py`, `shared/triage.py`)
- Machine-ingestible JSON log lines formatted with UTC ISO timestamps, log level, module, function name, and line numbers.
- Automated audit log on every triage decision recording:
  - `warning_id`
  - `original_tier` $\rightarrow$ `new_tier` (A / B / C)
  - `original_quality` $\rightarrow$ `new_quality` (EXPLICIT / INFERRED / AMBIGUOUS / INVALID)
  - `coordinate_count`
  - `qa_flags` and `unplotted_reason`

### 4. Metrics & Prometheus Observability (`shared/metrics.py`, `shared/prometheus.py`)
- Real-time thread-safe counters, gauges, and histograms.
- Integrated background HTTP server exposing `/metrics` (Prometheus exposition format) and `/health`.
- Key metrics tracked: `warnings_scraped_total`, `warnings_parsed_total`, `sync_operations_total`, `cache_hits_total`, `circuit_breaker_failures_total`, and `http_request_duration_seconds`.

### 5. Multi-Layer Caching (`shared/cache.py`)
- Thread-safe in-memory cache with TTL expiration, capacity limits, and LRU eviction.
- Zero-downtime Redis backend support when `REDIS_HOST` is supplied.
- `@cached` function decorator for expensive scraping and parsing calls.

### 6. Circuit Breakers (`shared/circuit_breaker.py`)
- State machine protection (`CLOSED` $\rightarrow$ `OPEN` $\rightarrow$ `HALF_OPEN`) wrapping external network requests and Gemini API calls.
- Configurable failure threshold (default: 5 failures) and reset timeout (default: 30 seconds).

---

## 🚀 Execution & Usage

### 1. Frontend Development

```bash
# Install dependencies
npm install

# Start Vite dev server on port 3000
npm run dev

# Compile and verify TypeScript
npm run build
npm run lint
```

### 2. Backend Pipelines

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run all NAVAREA pipelines synchronously with pre-flight checks:
PYTHONPATH=. python -m scripts.run_all
# or directly:
python scripts/run_all.py

# Run all NAVAREA pipelines concurrently with asynchronous orchestration:
PYTHONPATH=. python -m scripts.run_all_async

# Run individual regional pipelines (supports both module execution and direct script execution):
PYTHONPATH=. python -m scripts.run_baltic
# or:
python scripts/run_baltic.py

PYTHONPATH=. python -m scripts.run_navarea_1
PYTHONPATH=. python -m scripts.run_navarea_xi
```

#### Operational Safeguards & Repo Layout
- **`scripts/`**: Executable scrapers, deterministic parsers, and regional sync runners.
- **`shared/`**: Common utilities, validation schemas, circuit breakers, and metrics.
- **`navareas/`**: Generated raw bulletin text (`navarea_baltic_warnings.txt`) and parsed JSON (`parsed_baltic_warnings.json`).
- **`tests/`**: Unit, integration, and fuzz testing suites.

> **Environment Variables**: For live database synchronization, ensure `SUPABASE_URL` and `SUPABASE_KEY` are provided. When credentials are omitted, pipelines run in safe dry-run mode without failing.

### 3. Running Test Suites

The backend includes a comprehensive 66-test suite covering parsing, repair rules, triage gates, error handling, circuit breakers, caching, empty harvest resilience, and property-based fuzz testing:

```bash
# Run all unit and property-based tests:
python3 -m unittest discover tests

# Run specific test modules:
python3 -m unittest tests/test_validation.py
python3 -m unittest tests/test_circuit_breaker.py
python3 -m unittest tests/test_property_based.py
python3 -m unittest tests/test_repairs_and_triage.py
```

---

## 🚦 Triage Precedence (H02 Gate)

The ingestion engine enforces strict safety gates before marking any warning active on the map:

| Tier | Name | Criteria | Map Rendering |
| :---: | :--- | :--- | :---: |
| **A** | **Auto-Plot** | Explicit rule-parsed geometry, zero repairs, clean coordinates, no QA flags. | ✅ Rendered |
| **B** | **Review Queue** | Repaired coordinates (Rule 18/19/20/93), vessel-filtered notices, or AI-grounded proposals. | ⚠️ Flagged for Operator Review |
| **C** | **Quarantine / Blocked** | Missing hemisphere, validation failed, out-of-range bounds, truncated clauses. | ❌ Suppressed (Persisted with `unplotted_reason`) |

---

## 📄 License

MIT License. Designed for maritime safety information interoperability and navigational safety.
