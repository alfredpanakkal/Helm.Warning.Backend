# Helm.Warning.Backend

**Consolidated NAVAREA Navigational Warning Scraper Backend**

This private repository consolidates the scraping, parsing, and synchronization logic for multiple NAVAREA regions into a single maintainable codebase.

## Overview

This backend system scrapes navigational warnings from multiple maritime authorities, normalizes the data, and synchronizes it with a Supabase database. Each NAVAREA region maintains independent execution while sharing common infrastructure.

## Architecture

```text
Helm.Warning.Backend/
├── shared/                    # Shared infrastructure modules
│   ├── coordinates.py         # Coordinate parsing & GeoJSON generation
│   ├── classification.py      # Hazard classification
│   ├── sync.py                # Differential sync engine
│   ├── utils.py               # Common utilities
│   └── models.py              # Data models
├── navareas/                  # NAVAREA-specific modules
│   ├── baltic/                # NAVAREA Baltic (Swedish Maritime Administration)
│   │   ├── scraper.py
│   │   ├── parser.py
│   │   └── config.py
│   ├── navarea_1/             # NAVAREA I (UK Hydrographic Office)
│   │   ├── scraper.py
│   │   ├── parser.py
│   │   └── config.py
│   └── navarea_xi/            # NAVAREA XI (Japan Coast Guard)
│       ├── scraper.py
│       ├── parser.py
│       └── config.py
├── scripts/                   # Entry point scripts
│   ├── run_all.py             # Run all NAVAREA pipelines
│   ├── run_baltic.py          # Run Baltic pipeline only
│   ├── run_navarea_1.py       # Run NAVAREA-1 pipeline only
│   └── run_navarea_xi.py      # Run NAVAREA XI pipeline only
└── tests/                     # Test suite
    ├── test_shared.py
    ├── test_baltic.py
    ├── test_navarea_1.py
    └── test_navarea_xi.py
```

## NAVAREA Regions

| Region | Source | Schedule | Source ID |
|--------|--------|----------|-----------|
| Baltic | Swedish Maritime Administration | Every 6 hours | `sma-baltic-subarea` |
| NAVAREA I | UK Hydrographic Office | Every 6 hours | `ukho-navarea-1` |
| NAVAREA XI | Japan Coast Guard | Every 6 hours | `kaiho-navarea-xi` |

## Quick Start

### Prerequisites
* Python 3.11+
* GitHub Actions (for scheduled runs)
* Supabase account with database

### Installation

```bash
git clone git@github.com:alfredpanakkal/Helm.Warning.Backend.git
cd Helm.Warning.Backend
pip install -r requirements.txt
```

### Running Scrapers

```bash
# Run all NAVAREA pipelines
python scripts/run_all.py

# Run specific NAVAREA pipelines
python scripts/run_baltic.py
python scripts/run_navarea_1.py
python scripts/run_navarea_xi.py
```

## Configuration

Each NAVAREA has its own configuration located in `navareas/<region>/config.py`.

## Data Flow

Each NAVAREA follows a standard 3-stage pipeline:
1. **Scrape:** Fetch raw warning data from source.
2. **Parse:** Normalize, classify, and extract structured data.
3. **Sync:** Differential synchronization with Supabase.

## Database Schema

### Tables
* `raw_messages`: Audit trail for all scraped warnings
* `nav_warnings`: Active navigational warnings

### Hazard Categories
* `electronic`: GNSS, DGPS, AIS, radar interference
* `military`: Detonations, firing, gunnery, missile, weapons
* `aton`: Light, buoy, racón, beacon, unlit, extinguished
* `subsea`: Seismic, cable, pipeline, ROV, towing, dredging
* `drifting`: Drifting, derelict, mine, container, adrift
* `offshore`: Rig, platform, jack-up
* `general`: All other warnings

## GitHub Actions Workflows

Each NAVAREA has its own workflow that runs independently every 6 hours.

---

### **File: `requirements.txt`**

```text
# Core dependencies for all NAVAREA scrapers
requests>=2.28.0
beautifulsoup4>=4.12.0
supabase>=2.0.0
urllib3>=1.26.0
curl_cffi>=0.7.0
scrapling>=0.4.15
```

## License

MIT License
