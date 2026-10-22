# Helm.Warning.Backend — NAVAREA Maritime Safety Information Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Database: PostGIS 3.x](https://img.shields.io/badge/Database-PostGIS_3.x-336791.svg?logo=postgresql&logoColor=white)](https://postgis.net/)
[![Architecture: Master--Child RPC](https://img.shields.io/badge/Architecture-Master--Child_RPC-orange.svg)](#-data-safety-and-synchronization)
[![CI Workflows: 8 Active](https://img.shields.io/badge/Workflows-8_Scheduled-brightgreen.svg)](#-supported-navarea-sources)

> **Official Maritime Safety Notice**: Automated extraction, parsing, and classification provided by this system are designed to assist watchstanders and operations personnel. They **do not replace official navigational safety broadcasts, statutory nautical publications, or the professional judgment of a certified Officer of the Watch (OOW)**. Always consult official Navigational Area (NAVAREA) coordinators and national hydrographic offices for navigational decisions.

---

## 📑 Table of Contents

- [🌊 What Is This Project?](#-what-is-this-project)
  - [What Are NAVAREA Warnings and NAVWARNs?](#what-are-navarea-warnings-and-navwarns)
  - [What This System Does](#what-this-system-does)
  - [What This System Does Not Do](#what-this-system-does-not-do)
  - [Target Audience](#target-audience)
  - [Relationship to the Helm.Warning Ecosystem](#relationship-to-the-helmwarning-ecosystem)
- [⏳ Project Timeline](#-helmwarningbackend--project-timeline)
- [🔄 How the Pipeline Works](#-how-the-pipeline-works)
  - [Pipeline Flowchart](#pipeline-flowchart)
  - [Stage-by-Stage Explanation](#stage-by-stage-explanation)
- [🌐 Supported NAVAREA Sources](#-supported-navarea-sources)
- [📂 Repository Structure](#-repository-structure)
  - [Directory Tree](#directory-tree)
  - [Shared Modules Overview](#shared-modules-overview)
- [⚡ Quick Start Guide](#-quick-start-guide)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Running Tests](#running-tests)
  - [Executing a Safe Dry-Run Scrape](#executing-a-safe-dry-run-scrape)
- [⚙️ Configuration Reference](#️-configuration-reference)
  - [Environment Variables Table](#environment-variables-table)
  - [Creating Your Local `.env` File](#creating-your-local-env-file)
- [🛡️ Data Safety and Synchronization](#️-data-safety-and-synchronization)
  - [1. Deterministic Warning Identity (`canonical_id`)](#1-deterministic-warning-identity-canonical_id)
  - [2. Evidence-Based Lifecycle Transitions (Guarded Expiry & Cancellation)](#2-evidence-based-lifecycle-transitions-guarded-expiry--cancellation)
  - [3. Geometry-Preserving Atomic Upserts (`upsert_nav_warning` RPC)](#3-geometry-preserving-atomic-upserts-upsert_nav_warning-rpc)
  - [4. The H02 Triage Precedence Gate (Tiers A, B, C)](#4-the-h02-triage-precedence-gate-tiers-a-b-c)
  - [5. Verbatim Source Preservation & Immutable Audit Trail](#5-verbatim-source-preservation--immutable-audit-trail)
- [🔍 Monitoring and Troubleshooting](#-monitoring-and-troubleshooting)
  - [Operational Health & Run Ledgers](#operational-health--run-ledgers)
  - [Investigating Common Operational Scenarios](#investigating-common-operational-scenarios)
  - [Troubleshooting Reference Matrix](#troubleshooting-reference-matrix)
- [💻 Development Guide](#-development-guide)
  - [Branching & Contributing Workflow](#branching--contributing-workflow)
  - [Code Conventions for Human & AI Contributors](#code-conventions-for-human--ai-contributors)
- [➕ Adding a New Warning Source](#-adding-a-new-warning-source)
- [🔐 Security, Recovery, and Disaster Management](#-security-recovery-and-disaster-management)
- [📜 Contribution Guidelines and License](#-contribution-guidelines-and-license)
- [✅ Documentation Verification](#-documentation-verification)

---

## 🌊 What Is This Project?

### What Are NAVAREA Warnings and NAVWARNs?
Under the International Maritime Organization (IMO) and the International Hydrographic Organization (IHO) World-Wide Navigational Warning Service (WWNWS), the world’s oceans are divided into 21 geographic areas called **NAVAREAs**. Each NAVAREA is coordinated by an official national hydrographic authority responsible for broadcasting urgent **Navigational Warnings (NAVWARNs)**. These notices alert mariners to critical hazards, such as unexploded ordnance, drifting derelicts, broken navigational aids, live-fire naval exercises, submarine cable operations, and newly charted shoals.

### What This System Does
**Helm.Warning.Backend** is an automated data engineering pipeline that:
- **Collects** official navigational safety messages from supported hydrographic authorities via polite web scraping, PDF extraction, and modern S-124 SECOM XML endpoints.
- **Normalizes and Parses** diverse text and spatial formats (including degrees-minutes-seconds, decimal minutes, and GML polygons).
- **Applies Maritime Safety Gates** to validate coordinate bounds and verify geometric consistency.
- **Categorizes Hazards** into standardized maritime categories (e.g., *military exercises*, *aids to navigation*, *drifting hazards*, *underwater operations*).
- **Synchronizes State Safely** into a relational PostGIS database using non-destructive differential updates, cryptographic audit logs, and evidence-based lifecycle rules.

### What This System Does Not Do
- ❌ **It does NOT replace statutory navigation tools**: It is not an ECDIS (Electronic Chart Display and Information System) type-approved navigation device.
- ❌ **It does NOT delete historical records**: Records are never purged during routine synchronization; they transition between `active`, `cancelled`, and `expired` statuses.
- ❌ **It does NOT guess or clamp invalid coordinates**: If a coordinate has an invalid hemisphere or exceeds latitude $[-90, 90]$ or longitude $[-180, 180]$, it is quarantined for operator review rather than guessed.

### Target Audience
1. **Operators & Watchstanders**: Personnel monitoring scraper health, verifying bulletin counts, and reviewing flagged warnings.
2. **Software Engineers**: Developers maintaining source scrapers, refining parsing regexes, optimizing database queries, and extending automation.
3. **AI Coding Agents**: Automated tools maintaining the repository; this guide outlines project contracts, invariant safety rules, and restrictions against unnecessary rewrites.

### Relationship to the Helm.Warning Ecosystem
This repository serves as the authoritative data collection and processing engine. Downstream consumers—such as the **Helm Navigational Warning Operations Console** and the **Public Mariner Portal**—connect directly to the PostGIS spatial views and Supabase Realtime channels populated by this backend.

---

## ⏳ Helm.Warning.Backend — Project Timeline

### Phase 0 · Origins (Jan – Jun 2026)
Your maritime app journey began with vessel trackers, culminating in the first NAVAREA idea — an empty plotter repo (Jun 29).

### Phase 1 · First Scraper (Sep 2026)
**Sep 18** — First scraper ever built: **NAVAREA VIII** (NHO India) in `hydrobharat-navarea-scraper` (Liferay API + PDF parsing).

### Phase 2 · Standalone Repos (Oct 7–15)
**Oct 9** — Two dedicated repos, built in rapid bursts:
- `NAVAREA-BALTIC` → **NAVAREA I (UKHO)** scraper born here (Oct 9, 06:52)
- `NAVAREA-XI-JAPAN` → **NAVAREA XI** scraper (Japan Coast Guard)

### Phase 3 · Unified Backend (Oct 16–20)
**Oct 16** — All scrapers consolidated into `Helm.Warning.Backend` (shared infra, sync engine, CI, tests).
**Oct 19** — **NAVAREA II** added (S-124/SECOM); `scrapers/` package created.
**Oct 20** — Schema v24; NAVAREA II stabilized (XML ExchangeSet → Scrapling fetcher).

### Phase 4 · Expansion & Maturity (Oct 21–22)
**Oct 21** — **NAVAREA XII** & **NAVAREA IV** built from scratch; geometry validation hardened.
**Oct 22** — **NAVAREA VIII** full pipeline (full circle — first attempted, last completed); lifecycle-safety layer merged (PR #21).

---

**In one sentence:** One idea (Jun) → one scraper (Sep 18) → standalone repos (Oct 9) → unified backend (Oct 16) → 6 regions + safety layer (Oct 22).

---

## 🔄 How the Pipeline Works

The pipeline follows a multi-stage workflow designed to prevent corrupted data from ever reaching navigational displays.

### Pipeline Flowchart

```mermaid
flowchart TD
    subgraph Sources ["1. Official Upstream Authorities"]
        S_Baltic["Baltic Subarea (SMA Sweden)"]
        S_Nav1["NAVAREA I (UKHO Admiralty)"]
        S_Nav2["NAVAREA II (SHOM France S-124)"]
        S_Nav4["NAVAREA IV (NGA US East Coast)"]
        S_Nav8["NAVAREA VIII (NHO India)"]
        S_Nav11["NAVAREA XI (JCG Japan)"]
        S_Nav12["NAVAREA XII (NGA US West Coast)"]
    end

    subgraph Harvesters ["2. Polite Scrapers & Ingestion"]
        H_Web["HTTP / curl_cffi Impersonation"]
        H_Play["Playwright / PDF Parser"]
        H_S124["S-124 SECOM XML Client"]
    end

    Sources --> Harvesters

    subgraph AuditLog ["3. Verbatim Preservation"]
        RawDB[("public.raw_messages<br/>(Immutable SHA-256 Ledger)")]
    end

    Harvesters -->|Raw Text & Checksums| AuditLog

    subgraph Processing ["4. Parsing, Normalization & Safety Gates"]
        Split["Corpus Boundary Splitter<br/>(shared/splitter.py)"]
        CoordParse["Coordinate Extraction & Repair<br/>(Rules 18, 19, 20, 93)"]
        Classify["Multi-Hazard Classification<br/>(categories TEXT[])"]
        TriageGate{"H02 Triage Precedence Gate<br/>(shared/triage.py)"}
    end

    Harvesters --> Split --> CoordParse --> Classify --> TriageGate

    TriageGate -->|Clean Coordinates & Geometry| TierA["Tier A: Auto-Plot<br/>(Active Spatial View)"]
    TriageGate -->|Repaired or Filtered| TierB["Tier B: Review Queue<br/>(Operator Review)"]
    TriageGate -->|Invalid or Missing Data| TierC["Tier C: Quarantined<br/>(Suppressed from Map)"]

    subgraph DiffEngine ["5. Differential Synchronization Engine"]
        DiffCalc["Canonical Matching & Diff Calculation<br/>(shared/sync_engine.py)"]
        CancelGuard{"Cancel & Expiry Guard<br/>(Credible Snapshot?)"}
        GenLedger[("public.ingestion_generations<br/>(Run Ledger)")]
    end

    TierA & TierB & TierC --> DiffCalc --> CancelGuard
    CancelGuard --> GenLedger

    subgraph Storage ["6. PostGIS Relational Database"]
        RPC["Atomic Stored Procedure<br/>public.upsert_nav_warning()"]
        MasterTab[("public.nav_warnings<br/>(Master Envelopes)")]
        GeomTab[("public.nav_warning_geometries<br/>(PostGIS 4326)")]
        SpatialView["public.nav_warnings_active_spatial<br/>(High-Speed Map View)"]
        ArchiveView["public.nav_warnings_archive<br/>(Data Bank / Historical)"]
    end

    CancelGuard -->|Atomic Batch Payload| RPC
    RPC --> MasterTab
    RPC --> GeomTab
    MasterTab & GeomTab --> SpatialView
    MasterTab --> ArchiveView

    subgraph Downstream ["7. Presentation & Downstream Apps"]
        Realtime["Supabase Realtime WebSockets"]
        Console["Helm Operations Console & Leaflet Map"]
    end

    SpatialView --> Realtime --> Console
```

### Stage-by-Stage Explanation

1. **Harvesting**: Dedicated scrapers politely query official portals. Depending on the authority, this uses HTTP GET with browser TLS fingerprinting (`curl_cffi`), headless browser pagination (`playwright`), or S-124 SECOM XML clients.
2. **Raw Preservation**: Before any transformations occur, the raw bulletin text is hashed with SHA-256 and stored in `public.raw_messages` to ensure an immutable legal audit trail.
3. **Boundary Splitting & Normalization**: Multi-message bulletins (such as daily digests) are segmented into individual warning blocks via `shared/splitter.py`.
4. **Coordinate Extraction & Repair**: Raw coordinate strings (DMS, DDM, DD) are parsed. Deterministic repair rules (such as Rule 18 for missing leading zeros or Rule 93 for polygon hemisphere inheritance) resolve typographical quirks without guessing.
5. **Multi-Hazard Classification**: Warnings are assigned standardized tag arrays (e.g., `["military", "drifting_hazard"]`) based on maritime terminology analysis.
6. **H02 Triage Precedence Gate**: Strict safety rules classify the warning into **Tier A** (rendered on live charts), **Tier B** (held for human review), or **Tier C** (quarantined/suppressed).
7. **Differential Synchronization**: The sync engine matches records against the database using a unique `canonical_id`. It determines which records are brand new, updated, unchanged, expired, or unobserved.
8. **Guarded Lifecycle & Run Ledger**: Missing warnings are protected by safety thresholds. A run record is logged in `public.ingestion_generations`.
9. **Atomic PostGIS Upsert**: The `public.upsert_nav_warning` stored procedure updates the master record and replaces child geometries within a single transaction, preserving historical geometries if an incoming parse produces an empty geometry set.
10. **Downstream Propagation**: Updated active warnings are exposed via `public.nav_warnings_active_spatial` and broadcast over Supabase Realtime WebSockets to operators and mariners.

---

## 🌐 Supported NAVAREA Sources

The following seven international maritime warning feeds are implemented, tested, and actively scheduled:

| NAVAREA / Region | Publishing Authority | Official Source / Feed | Implementation Files | Automation Workflow | Operational Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **Baltic Subarea** | Swedish Maritime Administration (*Sjöfartsverket*) | [Sjöfartsverket Warnings](https://www.sjofartsverket.se) | [`scripts/baltic_scraper.py`](scripts/baltic_scraper.py)<br/>[`scripts/baltic_parser.py`](scripts/baltic_parser.py)<br/>[`scripts/run_baltic.py`](scripts/run_baltic.py) | [`.github/workflows/baltic-sync.yml`](.github/workflows/baltic-sync.yml) *(Every 15 mins)* | ✅ **Active & Verified** |
| **NAVAREA I** | UK Hydrographic Office (*UKHO Admiralty*) | [UKHO Admiralty MSI Portal](https://www.admiralty.co.uk) | [`scripts/navarea_1_scraper.py`](scripts/navarea_1_scraper.py)<br/>[`scripts/navarea_1_parser.py`](scripts/navarea_1_parser.py)<br/>[`scripts/run_navarea_1.py`](scripts/run_navarea_1.py) | [`.github/workflows/navarea-1-sync.yml`](.github/workflows/navarea-1-sync.yml) *(Every 30 mins)* | ✅ **Active & Verified** |
| **NAVAREA II** | French Hydrographic Service (*SHOM*) | [SHOM SECOM S-124 Service](https://services.ping-info-nautique.fr) | [`scrapers/navarea_ii.py`](scrapers/navarea_ii.py) | [`.github/workflows/navarea_ii.yml`](.github/workflows/navarea_ii.yml) *(Every 30 mins)* | ✅ **Active & Verified** |
| **NAVAREA IV** | US National Geospatial-Intelligence Agency (*NGA*) | [NGA MSI Daily Memo IV](https://msi.nga.mil/apology_objects/DailyMemIV.txt) | [`scripts/navarea_iv_scraper.py`](scripts/navarea_iv_scraper.py)<br/>[`scripts/navarea_iv_parser.py`](scripts/navarea_iv_parser.py)<br/>[`scripts/run_navarea_iv.py`](scripts/run_navarea_iv.py) | [`.github/workflows/navarea-iv-sync.yml`](.github/workflows/navarea-iv-sync.yml) *(Every 6 hours)* | ✅ **Active & Verified** |
| **NAVAREA VIII** | Indian National Hydrographic Office (*NHO India*) | [NHO India In-Force Portal](https://hydrobharat.gov.in) *(Mirror: SeaLagom)* | [`scripts/navarea_8_scraper.py`](scripts/navarea_8_scraper.py)<br/>[`scripts/navarea_8_parser.py`](scripts/navarea_8_parser.py)<br/>[`scripts/run_navarea_8.py`](scripts/run_navarea_8.py) | [`.github/workflows/navarea-8-sync.yml`](.github/workflows/navarea-8-sync.yml) *(Every 4 hours)* | ✅ **Active & Verified** |
| **NAVAREA XI** | Japan Coast Guard (*JCG Kaiho*) | [JCG Kaiho Warning Service](https://www1.kaiho.mlit.go.jp) | [`scripts/navarea_xi_scraper.py`](scripts/navarea_xi_scraper.py)<br/>[`scripts/navarea_xi_parser.py`](scripts/navarea_xi_parser.py)<br/>[`scripts/run_navarea_xi.py`](scripts/run_navarea_xi.py) | [`.github/workflows/navarea-xi-sync.yml`](.github/workflows/navarea-xi-sync.yml) *(Every 30 mins)* | ✅ **Active & Verified** |
| **NAVAREA XII** | US National Geospatial-Intelligence Agency (*NGA*) | [NGA MSI Daily Memo XII](https://msi.nga.mil/apology_objects/DailyMemXII.txt) | [`scripts/navarea_xii_scraper.py`](scripts/navarea_xii_scraper.py)<br/>[`scripts/navarea_xii_parser.py`](scripts/navarea_xii_parser.py)<br/>[`scripts/run_navarea_xii.py`](scripts/run_navarea_xii.py) | [`.github/workflows/navarea-xii-sync.yml`](.github/workflows/navarea-xii-sync.yml) *(Every 6 hours)* | ✅ **Active & Verified** |
| **All Regions** | Master Orchestrator | *All above coordinators* | [`scripts/run_all.py`](scripts/run_all.py)<br/>[`scripts/run_all_async.py`](scripts/run_all_async.py) | [`.github/workflows/all-sync.yml`](.github/workflows/all-sync.yml) *(Every 6 hours)* | ✅ **Active & Verified** |

---

## 📂 Repository Structure

### Directory Tree

```text
.
├── .github/workflows/       # Production CI/CD automated sync schedules
├── migrations/              # Versioned PostgreSQL & PostGIS database migrations
├── scrapers/                # Specialized regional scrapers (e.g., S-124 SECOM XML, table scrapers)
│   ├── navarea_8.py         # NAVAREA VIII PDF fast-path scraper
│   ├── navarea_8_table.py   # NAVAREA VIII Playwright table scraper
│   └── navarea_ii.py        # NAVAREA II S-124 SECOM XML client
├── scripts/                 # Scraper wrappers, parsers, and regional sync runners
│   ├── run_all.py           # Master synchronous runner across all 7 regions
│   ├── run_all_async.py     # Concurrent asyncio master pipeline runner
│   ├── async_scraper.py     # Base async HTTP client with rate-limiting semaphores
│   ├── ai_parser.py         # Gemini 3.1 Flash-Lite AI coordinate fallback extractor
│   └── navarea_*_sync.py    # Region-specific ingestion orchestration
├── shared/                  # Core processing modules (REUSE THESE; DO NOT REINVENT)
│   ├── sync_engine.py       # Differential matching, cancel guards, generation logging & RPC caller
│   ├── models.py            # Dataclasses (TriageRecord, CoordinateProvenance) & payload builders
│   ├── triage.py            # H02 Triage Precedence gate & audit logger
│   ├── utils.py             # Coordinate normalization, centroid math & repair rules (18/19/20/93)
│   ├── splitter.py          # Boundary splitter for multi-bulletin raw feeds
│   ├── config.py            # Centralized typed configuration & pre-flight validation
│   ├── circuit_breaker.py   # CLOSED -> OPEN -> HALF_OPEN fault-tolerance state machine
│   ├── retry.py             # Exponential backoff decorator with randomized jitter
│   ├── exceptions.py        # Contextual exception hierarchy (NavWarnError, ValidationError, etc.)
│   ├── logging.py           # Machine-ingestible JSON structured audit logger
│   ├── metrics.py           # Thread-safe Counters, Gauges, and Histograms
│   └── prometheus.py        # Embedded Prometheus HTTP exposition server (/metrics)
├── src/                     # React 19 / TypeScript Maritime Operations Console & Leaflet Portal
├── tests/                   # Python regression, property-based fuzzing, and unit test suites
├── requirements.txt         # Pinned Python backend dependencies
└── package.json             # Frontend dependencies and scripts
```

### Shared Modules Overview
To maintain consistency and data integrity, all regional scrapers rely on the shared modules in [`shared/`](shared/):
- **[`shared/sync_engine.py`](shared/sync_engine.py)**: The single point of entry for database synchronization. It handles differential calculations, canonical ID mapping, evidence-based cancellation guards, and calls the `upsert_nav_warning` RPC.
- **[`shared/utils.py`](shared/utils.py)**: Contains all coordinate extraction logic, DMS/DDM/DD parsers, and repair rules. Never write custom coordinate regexes in individual scrapers.
- **[`shared/triage.py`](shared/triage.py)**: Enforces the H02 safety gate. Ensures consistent assignment of Tiers A, B, and C across all regions.
- **[`shared/models.py`](shared/models.py)**: Defines shared data structures, canonical ID formatting, and builds JSON payloads for the database.
- **[`shared/circuit_breaker.py`](shared/circuit_breaker.py)**: Protects remote upstream authority servers from aggressive retry storms during outages.

---

## ⚡ Quick Start Guide

Follow these steps to set up and run the backend locally in a safe, non-destructive environment.

### Prerequisites
- **Python**: Version 3.11 or higher.
- **Node.js**: Version 20 or higher (optional, only needed for the frontend console).
- **Git**: Installed and configured.

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/alfredpanakkal/Helm.Warning.Backend.git
   cd Helm.Warning.Backend
   ```

2. **Create and activate a Python virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   # On Windows: .venv\Scripts\activate
   ```

3. **Install Python dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Install Playwright browser binaries** (required for NAVAREA VIII table scraping):
   ```bash
   playwright install chromium --with-deps
   ```

### Running Tests
Execute the automated test suite to ensure your environment is functioning correctly:
```bash
# Run the complete test suite (220+ tests)
python3 -m unittest discover tests

# Or run specific test modules
python3 -m unittest tests/test_validation.py
python3 -m unittest tests/test_circuit_breaker.py
python3 -m unittest tests/test_property_based.py
python3 -m unittest tests/test_repairs_and_triage.py
```

### Executing a Safe Dry-Run Scrape
The backend includes a **dry-run mode** (`ALLOW_DRY_RUN=1`). This allows you to scrape, parse, triage, and inspect warning outputs locally without modifying or requiring access to a remote Supabase/PostGIS database:

```bash
# Safely run the Baltic pipeline in dry-run mode
ALLOW_DRY_RUN=1 PYTHONPATH=. python3 scripts/run_baltic.py

# Safely run NAVAREA I in dry-run mode
ALLOW_DRY_RUN=1 PYTHONPATH=. python3 scripts/run_navarea_1.py

# Safely run the master pipeline across all 7 regions
ALLOW_DRY_RUN=1 PYTHONPATH=. python3 scripts/run_all.py
```

Inspect the parsed results in the generated local files:
- Raw harvested bulletins: `navareas/navarea_baltic_warnings.txt`
- Parsed JSON output: `navareas/parsed_baltic_warnings.json`

---

## ⚙️ Configuration Reference

All settings are managed centrally via [`shared/config.py`](shared/config.py) and validated upon process startup.

### Environment Variables Table

| Variable Name | Required? | Default | Scope | Description |
| :--- | :---: | :---: | :---: | :--- |
| `SUPABASE_URL` | Yes (in Prod) | `""` | Prod / CI | Supabase project URL (must begin with `https://` or `http://`). |
| `SUPABASE_KEY` | Yes (in Prod) | `""` | Prod / CI | Supabase Service Role or API Key (minimum 20 characters). |
| `ALLOW_DRY_RUN` | No | `""` | Local / CI | Set to `1` or `true` to allow pipelines to harvest and parse without live database credentials. |
| `SYNC_CANCEL_MIN_FEED_COUNT` | No | `10` | All | Minimum number of scraped warnings required before absence can be treated as cancellation. |
| `SYNC_CANCEL_MIN_FEED_FRACTION` | No | `0.5` | All | Minimum fraction (e.g. 50%) of active DB records that a scrape must cover to be considered a credible snapshot. |
| `NAVWARN_FEED_MODE` | No | `escalate_and_continue` | All | Operational policy: `escalate_and_continue` (quarantines malformed notices) or `strict_abort`. |
| `MIN_FEED_SIZE_FOR_CANCEL` | No | `5` | All | Global safety floor for feed size before mass cancellation is evaluated. |
| `MAX_WARNING_AGE_DAYS` | No | `30` | All | Maximum age (in days) before historical active records are pruned or expired. |
| `GEMINI_API_KEY` | No | `""` | All | Google Gemini API key used exclusively for ambiguous coordinate escalation. |
| `GEMINI_MODEL_NAME` | No | `gemini-3.1-flash-lite`| All | Model alias for AI coordinate proposals. |
| `NAVWARN_AI_ENABLED` | No | `false` | All | Flag to enable AI coordinate grounding proposals. |
| `GEMINI_TIMEOUT_SECONDS` | No | `10.0` | All | Network timeout in seconds for AI escalation calls. |
| `LOG_LEVEL` | No | `INFO` | All | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FILE` | No | `None` | All | File path for rotating log files. If omitted, logs stream as structured JSON to `stdout`. |
| `REDIS_HOST` | No | `None` | Optional | Hostname for Redis distributed caching (falls back to thread-safe memory cache if unset). |
| `REDIS_PORT` | No | `6379` | Optional | Port for Redis connection. |
| `PROMETHEUS_PORT` | No | `8000` | Optional | HTTP port for the Prometheus metrics exporter (`/metrics` and `/health`). |

### Creating Your Local `.env` File
To configure your local environment, copy the template below into a `.env` file in the repository root:

```bash
# --- Database Connection (Leave empty or use ALLOW_DRY_RUN=1 for local testing) ---
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key-here
ALLOW_DRY_RUN=1

# --- Lifecycle Safety Thresholds ---
SYNC_CANCEL_MIN_FEED_COUNT=10
SYNC_CANCEL_MIN_FEED_FRACTION=0.5

# --- Optional AI Escalation ---
NAVWARN_AI_ENABLED=false
GEMINI_API_KEY=
GEMINI_MODEL_NAME=gemini-3.1-flash-lite

# --- Logging & Monitoring ---
LOG_LEVEL=INFO
PROMETHEUS_PORT=8000
```

---

## 🛡️ Data Safety and Synchronization

Because this repository processes critical maritime safety information, data synchronization adheres to strict safety principles:

### 1. Deterministic Warning Identity (`canonical_id`)
To prevent duplicate records and cross-region collisions, warnings are keyed on an immutable `canonical_id`:
$$\text{canonical\_id} = \text{NAVAREA} + \text{" "} + \text{warning\_id}$$
*(e.g., `NAVAREA I 042/26`, `NAVAREA IV 0123/26`, `BALTIC 0014/26`)*.

Before any differential matching occurs, both scraped items and existing database records are mapped to this canonical key.

### 2. Evidence-Based Lifecycle Transitions (Guarded Expiry & Cancellation)
> ⚠️ **CRITICAL SAFETY INVARIANT**: A warning that is missing from a single scrape is **NEVER** automatically assumed to be cancelled or deleted. Upstream web servers experience transient glitches, network partitions, and incomplete harvests.

The synchronization engine in [`shared/sync_engine.py`](shared/sync_engine.py) applies evidence-based lifecycle logic:
- **`expired`**: Triggered only when the warning's own `valid_to` date has elapsed (`status_basis = 'expired_by_validity'`).
- **`cancelled`**: Triggered only when the scrape represents a **credible complete snapshot**. To be considered credible, the harvest must satisfy two safety thresholds:
  1. $\text{Scraped Items} \ge \text{SYNC\_CANCEL\_MIN\_FEED\_COUNT}$ *(default: 10)*
  2. $\text{Scraped Items} \ge \text{SYNC\_CANCEL\_MIN\_FEED\_FRACTION} \times \text{Active DB Records}$ *(default: 50%)*
- **`unobserved` (Retained Active)**: If a scrape is partial (e.g., only 2 items retrieved while the database has 20 active), missing records are marked as `unobserved` and **remain active on the map**.

Every transition updates `status_changed_at` and `status_basis` to maintain full auditability.

### 3. Geometry-Preserving Atomic Upserts (`upsert_nav_warning` RPC)
The PostgreSQL stored procedure [`migrations/20261023_lifecycle_safety.sql`](migrations/20261023_lifecycle_safety.sql) executes with `SECURITY DEFINER`:
- Master metadata and child geometries are updated inside an atomic transaction.
- **Geometry Preservation**: If a subsequent re-parse yields no valid geometry, but the warning previously had valid geometry in the database, the **previous geometry is preserved** and Tier A status is retained. A `geometry_preserved_previous_run` flag is added to `qa_flags` for operator review, preventing transient parsing failures from erasing active hazard boundaries.

### 4. The H02 Triage Precedence Gate (Tiers A, B, C)
All extracted warnings pass through the H02 safety gate in [`shared/triage.py`](shared/triage.py):
- **Tier A (Auto-Plot)**: Explicit rule-parsed geometry, zero repairs, clean coordinates within bounds, no QA flags. Rendered directly on navigational charts.
- **Tier B (Review Queue)**: Coordinates repaired via Rules 18/19/20/93, vessel-specific filtering notices, or AI-grounded proposals. Displayed with a warning badge and queued for operator sign-off.
- **Tier C (Quarantine)**: Missing hemispheres, out-of-bounds coordinates, or truncated text. Suppressed from navigation displays and recorded with an `unplotted_reason`.

### 5. Verbatim Source Preservation & Immutable Audit Trail
- **Raw Messages**: Scraped text is stored verbatim in `public.raw_messages` along with its source ID, timestamp, and SHA-256 checksum.
- **Ingestion Generations**: Every execution writes a ledger entry to `public.ingestion_generations`, recording harvested counts, diff stats, evidence hashes, and whether the cancel guard was activated.

---

## 🔍 Monitoring and Troubleshooting

### Operational Health & Run Ledgers
Operators can monitor pipeline performance and data integrity through several interfaces:
1. **GitHub Actions Workflow History**: Navigate to the **Actions** tab in the repository to view automated runs for each regional workflow.
2. **Prometheus Metrics**: The engine serves real-time counters and histograms at `http://localhost:8000/metrics`.
3. **Run Ledger Table**: Query the `public.ingestion_generations` table to see the exact counts and status of recent synchronization runs:
   ```sql
   SELECT source_id, started_at, status, parsed_count, active_count, details
   FROM public.ingestion_generations
   ORDER BY started_at DESC
   LIMIT 10;
   ```

### Investigating Common Operational Scenarios

#### Scenario A: A regional scraper workflow failed in GitHub Actions
1. Open the failed run under the **Actions** tab.
2. Expand the **Run Ingestion Pipeline** step.
3. Check the exit code:
   - **Exit Code 2**: Missing or invalid credentials (`SUPABASE_URL` or `SUPABASE_KEY`). Check GitHub Actions Secrets.
   - **Exit Code 3**: Regional sync failure or upstream authority outage. Check the error log lines.

#### Scenario B: An active warning disappeared from the map
1. Check the historical status in `public.nav_warnings`:
   ```sql
   SELECT canonical_id, status, status_basis, status_changed_at, unplotted_reason
   FROM public.nav_warnings
   WHERE canonical_id = 'NAVAREA I 042/26';
   ```
2. If `status = 'expired'`, check if the `valid_to` date passed.
3. If `status = 'cancelled'`, verify the `status_basis` and check `ingestion_generations` to see the snapshot details for that run.
4. If `triage_tier = 'C'`, check the `unplotted_reason` (e.g., `no_valid_geometry`).

### Troubleshooting Reference Matrix

| Symptom / Error | Likely Root Cause | Safe Remediation Step |
| :--- | :--- | :--- |
| `❌ FATAL: SUPABASE_URL or SUPABASE_KEY is missing` | Environment variables are not set in the shell or CI. | Set credentials in `.env` or run with `ALLOW_DRY_RUN=1` for local testing. |
| `⏸ Cancel guard active: feed not credible` | Upstream authority returned a partial or truncated harvest. | **No action needed**: The system safely kept existing warnings active to prevent data loss. |
| `CircuitBreaker '...' tripped to OPEN` | Upstream authority server is timing out or throwing 5xx errors. | Wait for the reset timeout (30s default). The circuit breaker will automatically enter `HALF_OPEN` and retry. |
| `OutOfRangeCoordinateError` | Upstream bulletin contains typographical errors (e.g. `Lat: 95°`). | System automatically demotes warning to **Tier C** (Quarantined). Check raw text in `public.raw_messages`. |
| `playwright._impl._errors.Error: Executable doesn't exist` | Chromium browser binary is not installed for Playwright. | Run `playwright install chromium --with-deps` in your virtual environment. |

---

## 💻 Development Guide

### Branching & Contributing Workflow
1. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/enhance-navarea-parser
   ```
2. **Reuse Shared Modules**: Never write custom coordinate extractors or database upsert queries. Always use `shared/utils.py` and `shared/sync_engine.py`.
3. **Run Regression Tests Locally**:
   ```bash
   python3 -m unittest discover tests
   ```
4. **Inspect the Git Diff**: Verify that only the intended scraper or parser files were modified:
   ```bash
   git diff
   ```
5. **Open a Pull Request**: Provide a clear description referencing the hydrographic authority, sample bulletin inputs, and verified test results.

### Code Conventions for Human & AI Contributors
- **Strict Prohibition Against Rewrites**: Do not rebuild working modules. Extend existing classes or functions.
- **Type Hints**: Use standard Python type annotations (`typing.Optional`, `typing.List`, `typing.Dict`).
- **No Hardcoded Credentials**: Never commit API keys, connection strings, or service tokens.
- **Deterministic Coordinate Parsing**: Always return `float("nan")` for out-of-range coordinates; never clamp values (e.g., do not clamp $91^\circ$ to $90^\circ$).

---

## ➕ Adding a New Warning Source

Follow these ten steps to onboard a new NAVAREA coordinator or national hydrographic source:

1. **Inspect the Authoritative Source**: Determine whether the authority publishes plain text, HTML tables, paginated portals, or S-124 SECOM XML.
2. **Preserve Raw Feeds**: Choose an output path in `navareas/` (e.g., `navareas/navarea_X/raw_warnings.txt`).
3. **Implement the Scraper**: Create `scripts/navarea_X_scraper.py` using polite HTTP conventions (set clear User-Agents, handle retries with jitter).
4. **Implement the Parser**: Create `scripts/navarea_X_parser.py`. Import coordinate parsers from `shared/utils.py` and boundary splitters from `shared/splitter.py`.
5. **Apply Triage**: Pass extracted records through `shared/triage.py` to assign Tiers A, B, and C.
6. **Implement the Sync Wrapper**: Create `scripts/navarea_X_sync.py` and delegate database operations to `shared.sync_engine.run_differential_sync`.
7. **Create a Test Module**: Add `tests/test_navarea_X.py` with golden bulletin fixtures covering points, polygons, light outages, and cancellation clauses.
8. **Add CLI Runner**: Create `scripts/run_navarea_X.py` with standard pre-flight checks.
9. **Register in Master Pipelines**: Add the new runner to `scripts/run_all.py` and `scripts/run_all_async.py`.
10. **Configure GitHub Actions**: Create `.github/workflows/navarea-X-sync.yml` with the appropriate cron schedule.

---

## 🔐 Security, Recovery, and Disaster Management

### Credential Safety
- All production credentials (`SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`) are stored in **GitHub Actions Secrets**.
- GitHub workflows run with minimum required permissions (`contents: write` for artifact uploads).
- Database connections use PostGIS Row-Level Security (RLS) policies allowing public reads on active spatial views while restricting writes to the service role.

### Disaster Recovery & Rollback
- **Database Backups**: Supabase manages point-in-time PostgreSQL backups independently of the Git repository.
- **Reverting Erroneous Code**: If a parser bug is introduced, revert the commit cleanly:
  ```bash
  git revert <commit-hash>
  git push origin main
  ```
- **Historical Recovery**: Because every sync writes raw text to `public.raw_messages`, any past state can be re-parsed and re-triaged without losing source fidelity.

---

## 📜 Contribution Guidelines and License

Contributions are welcome! Please adhere to the following conventions:
- **Commit Messages**: Use Conventional Commits (e.g., `feat(navarea-iv): add boundary regex for firing zone`, `fix(sync): adjust cancel guard fraction`).
- **Tests**: Every new scraper or parser must include unit test coverage under `tests/`.
- **License**: This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for complete terms.

---

## ✅ Documentation Verification

- **Last Inspected & Verified**: October 22, 2026
- **Verified Working Scrapers**: 7 Regions (Baltic, NAVAREA I, NAVAREA II S-124, NAVAREA IV, NAVAREA VIII, NAVAREA XI, NAVAREA XII)
- **Active Automation Workflows**: 8 GitHub Actions schedules in `.github/workflows/`
- **Database Model**: Master-Child PostGIS with `public.upsert_nav_warning` RPC and `ingestion_generations` run ledger
