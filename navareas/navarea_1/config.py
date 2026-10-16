#!/usr/bin/env python3
"""
NAVAREA I Configuration
Configuration for NAVAREA I navigational warnings scraper.
Source: UK Hydrographic Office (UKHO) Admiralty
"""

# Source identification
SOURCE_ID = "ukho-navarea-1"
NAVAREA_ID = "I"

# URLs
SOURCE_URL = "https://msi.admiralty.co.uk/RadioNavigationalWarnings"
SHOW_SELECTION_URL = "https://msi.admiralty.co.uk/RadioNavigationalWarnings/ShowSelection"

# Output files
OUTPUT_WARNINGS_FILE = "navareas/navarea_1/navarea_1_warnings.txt"
OUTPUT_PARSED_FILE = "navareas/navarea_1/parsed_navarea_1_warnings.json"

# Encoding
ENCODING = "utf-8"

# HTTP settings
USE_CURL_CFFI = False
TIMEOUT = 30
RETRY_ATTEMPTS = 3

# Valid database columns
VALID_RAW_MESSAGE_COLUMNS = {
    "warning_id", "source_id", "subject_header",
    "full_raw_text", "received_timestamp", "checksum_sha256"
}

VALID_NAV_WARNING_COLUMNS = {
    "warning_id", "source_id", "navarea", "title",
    "issued_text", "coordinates", "latitude", "longitude",
    "category", "status", "raw_text"
}
