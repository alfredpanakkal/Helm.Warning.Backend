# Helm Navigational Warning System

Consolidated NAVAREA Navigational Warning Operations Console, Scraper, Deterministic Parser, and Differential Synchronization System written in React, TypeScript, and Vite.

## Overview

The **Helm Navigational Warning System** integrates maritime safety information (MSI) across multiple international NAVAREA regions:
- **NAVAREA Baltic Subarea**: Swedish Maritime Administration (*Sjöfartsverket*)
- **NAVAREA I**: UK Hydrographic Office (*UKHO Admiralty*)
- **NAVAREA XI**: Japan Coast Guard (*JCG Kaiho*)

The application provides end-to-end ingestion, deterministic coordinate normalization, IMO/IHO hazard classification, GeoJSON geometry extraction, interactive GIS mapping, and differential synchronization with Supabase.

## Architecture

```text
src/
├── core/
│   ├── classification.ts    # 7-tier maritime hazard priority classifier
│   ├── coordinates.ts       # Coordinate extractor (DD-MM.MM, DD-MM-SS) & GeoJSON generator
│   ├── syncEngine.ts        # Differential sync engine (Skip, Add, Update, Cancel)
│   ├── utils.ts             # Fast SHA-256 integrity hash & text normalizer
│   └── parsers/
│       ├── balticParser.ts   # Sjofartsverket Baltic parser
│       ├── navarea1Parser.ts # UK Hydrographic Office parser
│       └── navareaXiParser.ts# Japan Coast Guard parser
├── components/
│   ├── Navbar.tsx           # Station status bar with live UTC & local clocks
│   ├── MaritimeMap.tsx      # Leaflet interactive nautical chart (Polygons, Lines, Points)
│   ├── WarningList.tsx      # Filterable bulletins list with search and GeoJSON/JSON export
│   ├── WarningDetailModal.tsx # Full bulletin auditor with SHA-256 and GeoJSON geometry
│   ├── PipelineRunnerModal.tsx# Ingestion & differential sync runner with live terminal
│   ├── BulletinParserStudio.tsx# Real-time parser and coordinate extraction sandbox
│   ├── TestSuiteRunnerModal.tsx# Automated test suites runner (25+ test cases)
│   └── SupabaseSyncConfigModal.tsx # Supabase tables and connection inspector
├── data/
│   └── seedWarnings.ts      # Active bulletin dataset across Baltic, NAVAREA I & XI
└── types/
    └── maritime.ts          # Core TypeScript data models
```

## Key Features

1. **Deterministic Parsing & Geometry Engine**:
   - Parses varied coordinates: degrees and decimal minutes (`DD-MM.MM[N/S] DDD-MM.MM[E/W]`), degrees minutes seconds, and non-decimal representations.
   - Generates standards-compliant GeoJSON: `Point` for single coordinates, `LineString` for subsea operations, and closed `Polygon` geometries for military hazard zones.

2. **IMO/IHO Maritime Hazard Classification**:
   - Priority hierarchy:
     1. `electronic`: GNSS, DGPS, AIS, radar interference, jamming, spoofing
     2. `military`: Detonations, naval firing, gunnery, missiles, weapons exercises
     3. `aton`: Aids to navigation outages (unlit buoys, racons, extinguished beacons)
     4. `subsea`: Cables, pipelines, seismic survey, ROV, dredging operations
     5. `drifting`: Adrift containers, mines, derelict vessels, space debris
     6. `offshore`: Oil & gas drilling rigs, jack-ups, platforms
     7. `general`: General navigational warnings and safety notices

3. **Differential Sync Engine (Supabase / Local Audit Store)**:
   - Evaluates incoming bulletins against existing database records:
     - **Skip**: Identical warning with matching SHA-256 checksum
     - **New**: First-time scraped bulletins inserted into `nav_warnings` and `raw_messages`
     - **Update**: Revisions with updated payload and new SHA-256 hash
     - **Cancel**: Bulletins dropped from authority feed marked as cancelled

4. **Interactive Nautical Operations Console**:
   - Visualizes hazards on a dark hydrographic chart with category colors.
   - One-click zoom and pan to active warning locations.
   - Built-in live terminal simulator to run scraping pipelines on demand.
   - In-app Automated Unit Test Suite verifying all coordinate transformations and parser assertions.

## Getting Started

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

## License

MIT License
