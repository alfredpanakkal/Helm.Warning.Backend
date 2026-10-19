# Helm.Warning.Backend - End-to-End Production Hardening & Improvement Plan

Production hardening, reliability instrumentation, and asynchronous scaling architecture for the `Helm.Warning.Backend` maritime navigation warning ingestion, parsing, triage, and synchronization engine.

## User Review & Critical Decisions

> [!IMPORTANT]
> **Confirmed Choices from Phase 1 Planning:**
> - **Execution Scope**: All three phases sequentially (Phase 1: Critical Hardening → Phase 2: Enhanced Reliability → Phase 3: Advanced Features) as a complete end-to-end overhaul.
> - **Surface Area**: Backend Python scripts, modules, and CLI execution pipelines only; keeping the React web dashboard intact as-is.
> - **Ingestion Error & Retry Policy**: Configurable per-feed mode with automatic triage escalation (invalid or anomalous records trigger automated quarantine to Tier B/C with explicit provenance and audit logs, preventing whole-feed aborts while preserving data integrity).

---

## 1. Overview & Core Concept

- **What It Does**: Hardens the Python backend responsible for scraping, splitting, parsing, repairing, and synchronizing worldwide Navigational Warnings (NAVAREA I, NAVAREA XI, and Baltic Sea) into Supabase. It establishes strict schema validation, structured audit logging, centralized configuration with startup self-checks, Prometheus observability, property-based testing, circuit breaking, and high-throughput async processing.
- **Target Audience / Persona**: Maritime data engineers, backend operators, and automated CI/CD cron workers executing daily or hourly navigational warning synchronizations.
- **Key Value**: Guarantees zero unhandled crashes during corrupt feed ingestion, eliminates silent coordinate parsing failures, provides complete decision traceability for safety audits, and scales throughput via non-blocking asynchronous pipeline orchestration.

---

## 2. User Experience & Operator Interface (CLI & Backend)

Although the React web frontend remains untouched, the backend operator experience and CLI output are upgraded to deliver predictable, human-readable terminal output alongside machine-ingestible JSON logs:

- **CLI Operator Workflow**:
  - `python -m scripts.run_all` or regional commands (`run_baltic`, `run_navarea_1`, `run_navarea_xi`) run configuration pre-flight validation.
  - Startup self-checks print a clean status card indicating database connectivity, Gemini API readiness, feed configurations, and log destinations.
  - Interactive CLI displays clear step progression (Scraping → Splitting → Parsing & Provenance → Triage Gate → Guarded Sync) with per-stage item counters and anomaly warnings.
  - Structured JSON logs are streamed simultaneously to configured log sinks (`stdout` or rotating log files) without interleaving or corrupting terminal formatting.
- **Per-Feed Ingestion Modes**:
  - `STRICT_ABORT`: Aborts regional pipeline on systemic anomalies.
  - `ESCALATE_AND_CONTINUE` (Default): Catches parsing or schema defects on individual records, auto-quarantines them into Tier C (or Tier B for recoverable repairs) with exact QA flags, and proceeds with valid navigational notices.
- **Graceful Termination & Error Reporting**:
  - Clean exit codes (`0` for success or handled quarantines, `1` for configuration/fatal network errors).
  - Clear remediation guidance printed upon configuration failure (e.g., missing environment variables, invalid Supabase keys, or network timeouts).

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1: Phased Sequential Overhaul vs Monolithic Refactor**
  - *Chosen Approach*: Execute Phase 1 (Hardening & Config), Phase 2 (Observability, Caching & Testing), and Phase 3 (Circuit Breakers & Async Pipeline) in discrete, test-verified layers.
  - *Why*: Ensures that basic data models, input validation, and logging foundations are fully stabilized before adding async concurrency and distributed caching layers.
  - *Alternatives Considered*: Direct async conversion without hardening risks masking ingestion edge-cases and silent data corruptions.

- **Decision 2: Automated Quarantine Triage Escalation over Immediate Pipeline Abort**
  - *Chosen Approach*: Implement `ConfigurableFeedPolicy` with automated fallback to `TriageTier.C` / `DataQuality.INVALID` for unparseable records, recording `unplotted_reason="validation_failed"`.
  - *Why*: In maritime safety, dropping an entire feed because of one corrupt notice from a hydrographic office endangers mariners who need the remaining 99 valid hazard alerts.
  - *Alternatives Considered*: Strict failure halts the entire feed, delaying critical notices.

- **Decision 3: Layered Caching with Graceful Local In-Memory Fallback**
  - *Chosen Approach*: Implement an abstract Cache interface supporting an in-memory TTL store with thread locks by default, seamlessly delegating to Redis when `REDIS_HOST` is configured.
  - *Why*: Allows zero-dependency operation in local testing and CI/CD while supporting distributed caching in multi-worker production deployments.

- **Decision 4: Gemini AI Escalation Guarded by Circuit Breakers & Fallback Rules**
  - *Chosen Approach*: Wrap `shared/ai_escalation.py` with the circuit breaker pattern, ensuring that rate limits, timeouts, or transient API outages immediately degrade to deterministic regex rules without hanging the pipeline.

---

## 4. Technical Architecture & Data Strategy

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AppConfig & Validation                          │
│        (Centralized env parsing, startup checks, feed policies)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Validated Config
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Structured Logger & Audit Trail                      │
│        (JSONFormatter, UTC timestamps, contextual extra fields)         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
┌──────────────┐             ┌──────────────┐             ┌──────────────┐
│ Baltic Feed  │             │  NAVAREA I   │             │  NAVAREA XI  │
└──────┬───────┘             └──────┬───────┘             └──────┬───────┘
       │                            │                            │
       └────────────────────────────┼────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Feed Ingestion & Circuit Breakers                    │
│   - AsyncScraper / HTTP Retry with exponential backoff                 │
│   - CircuitBreaker (CLOSED -> OPEN -> HALF_OPEN) for external APIs     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Raw Bulletin Corpora
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Pydantic Schema & Input Validation                   │
│   - Coordinate token sanitization & bounding range checks              │
│   - Splitter safety limits & encoding guards                           │
│   - Custom exception hierarchy (ValidationError, ParseError, SyncError)│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Validated Raw Notices
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Parsing & Coordinate Provenance                     │
│   - Deterministic regex & repair rules (Rule 18, etc.)                 │
│   - AI Escalation with Gemini client & caching (In-Memory / Redis)     │
│   - Full provenance tracking (quality, repairs, qa_flags)              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Parsed TriageRecord
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  H02 Triage Precedence & Audit Gate                    │
│   - Quality roll-up (worst wins)                                       │
│   - Hard blockers -> Tier C (quarantine with unplotted_reason)         │
│   - Inferred / Repaired / AI / Vessel-Filtered -> Tier B               │
│   - Pristine, rule-parsed with verified geometry -> Tier A             │
│   - Structured Audit Log of triage decisions                           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Batch Synchronization & Metrics                      │
│   - Batched differential sync (compute_differential_batched)           │
│   - Guarded cancellation with min_feed_size check                      │
│   - Metrics collection & Prometheus export (port 8000)                 │
│   - Async Supabase bulk insert / upsert / cancel execution             │
└────────────────────────────────────────────────────────────────────────┘
```

### Component & File Mapping

#### Phase 1: Critical Hardening
1. **`shared/config.py`**:
   - `AppConfig`, `SupabaseConfig`, `AIConfig`, `FeedPolicyConfig`.
   - Startup validation methods, strict type enforcement, sensible defaults.
2. **`shared/exceptions.py`**:
   - `NavWarnError` base exception with contextual dictionary metadata.
   - Subclasses: `ValidationError`, `ParseError`, `SyncError`, `AIValidationError`, `ConfigurationError`, `CircuitBreakerError`.
3. **`shared/logging.py`**:
   - `JSONFormatter` formatting UTC timestamps, log level, module, function name, and dynamic `extra_data`.
   - `setup_logging` utility supporting console and file outputs.
4. **`shared/validation.py`**:
   - Pydantic models for incoming raw warning chunks, coordinate tokens, and database write rows (`NavWarningWriteModel`).
   - Range validators for latitude `[-90, 90]`, longitude `[-180, 180]`, depth, and speeds.
5. **`shared/retry.py`**:
   - Generic `@retry` decorator with configurable exponential backoff and jitter for network/database calls.
6. **Hardening existing modules**:
   - `shared/utils.py`: Add input validation guards to coordinate parsers and repair rules.
   - `shared/triage.py`: Integrate structured audit logging for all tier assignments and unplotted reasons.
   - `scripts/run_all.py`, `scripts/run_*.py`: Enforce pre-flight config checks and startup logs.

#### Phase 2: Enhanced Reliability
1. **`shared/metrics.py` & `shared/prometheus.py`**:
   - Thread-safe `Counter`, `Histogram`, and `Gauge` implementations.
   - Prometheus exporter on configurable port (default 8000) tracking scraped, parsed, repaired, triaged (Tier A/B/C), and synced counts.
2. **`shared/cache.py`**:
   - Base `Cache` interface with in-memory TTL implementation and `@cached` decorator.
   - Key generators for coordinate parsing, AI grounding, and scraping responses.
3. **`shared/sync_modes.py` & `scripts/*_sync.py`**:
   - `BatchSyncResult` and `compute_differential_batched` to process and execute database upserts in batches (reducing Supabase round-trips).
4. **Test Suite Expansion**:
   - `tests/test_validation.py`: Exhaustive validation tests for all public helper functions and Pydantic models.
   - `tests/test_error_handling.py`: Verify exception hierarchies, context capturing, and retry backoff.
   - `tests/test_property_based.py`: Property-based testing using `hypothesis` or generative fuzzers for coordinate parsers and repair functions.
   - `tests/test_metrics_and_cache.py`: Verify cache hit/miss and metrics increments.

#### Phase 3: Advanced Features
1. **`shared/circuit_breaker.py`**:
   - State-machine circuit breaker (`CLOSED`, `OPEN`, `HALF_OPEN`) with thread safety and configurable failure thresholds.
   - Decorator applied to Gemini API calls, Supabase operations, and external scraping HTTP requests.
2. **`shared/cache.py` (Redis Extension)**:
   - Redis backend integration enabled conditionally when `REDIS_HOST` is supplied, falling back to local thread-safe memory cache.
3. **`scripts/async_scraper.py` & `shared/async_supabase.py`**:
   - Async scraping engine using `aiohttp` / non-blocking clients.
   - Async database batch operations and pipeline runner (`scripts/run_all_async.py`) orchestrating concurrent ingestion across all regions.

---

## 5. Verification Plan

### Test & Compilation Milestones
1. **Phase 1 Validation Tests**:
   - Run unit tests covering new validation decorators, Pydantic schemas, and config loaders.
   - Simulate missing/malformed environment variables to ensure clear fatal exits.
   - Verify JSON log formatting output on sample feeds.
2. **Phase 2 Reliability Tests**:
   - Execute batch sync tests ensuring identical differential output compared to single-record syncs.
   - Run property-based coordinate fuzz tests verifying zero unhandled crashes on 10,000 randomized tokens.
   - Verify Prometheus metrics endpoint exposure and metric updates.
3. **Phase 3 Scalability & Resilience Tests**:
   - Simulate Gemini API and scraper network timeouts to verify circuit breaker trip (`CLOSED` -> `OPEN`) and recovery (`HALF_OPEN` -> `CLOSED`).
   - Run `run_all_async.py` pipeline across regional test fixtures and benchmark throughput against synchronous baseline.
