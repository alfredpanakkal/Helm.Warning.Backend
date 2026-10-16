# Helm.Warning.Backend

Consolidated NAVAREA Navigational Warning Scraper Backend

## Overview
Helm.Warning.Backend collects, normalizes, and serves NAVAREA navigational warnings from multiple sources. It exposes a REST API for consumers to query active warnings, historical data, and metadata.

## Features
- Periodic scraping of NAVAREA sources
- Normalization and deduplication of warnings
- REST API for querying current and historical warnings
- Filtering by region, severity, and time range
- Simple configuration for sources and scrape intervals

## Installation
1. Clone the repo:
   git clone https://github.com/alfredpanakkal/Helm.Warning.Backend.git
2. Configure the application (see Configuration section).
3. Build and run using your preferred method (Docker, dotnet CLI, etc.).

## Configuration
Provide a configuration file or environment variables to specify:
- Source URLs for NAVAREA feeds
- Scrape interval
- Database connection string
- API port and CORS settings

## Usage
- Start the service.
- Call the REST endpoints (see API) to fetch warnings or subscribe to updates.

## API (example)
- GET /api/warnings — list active warnings
- GET /api/warnings/{id} — get a specific warning
- GET /api/warnings?region={region} — filter by region
- GET /api/warnings?from={iso}&to={iso} — filter by time range

(Replace with actual endpoints once implemented.)

## Development
- Requirements: .NET SDK (version X), Docker (optional)
- Run tests: dotnet test
- Start locally: dotnet run --project src/Helm.Warning.Backend

## Contributing
Contributions welcome. Please open issues or pull requests with descriptive titles and tests where possible.

## License
Specify the project license here (e.g., MIT).

## Contact
Maintainer: Alfred Panakkal
