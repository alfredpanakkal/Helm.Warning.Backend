#!/usr/bin/env python3
"""
NAVAREA Baltic Configuration
Configuration for the Baltic Sea and Swedish navigational warnings scraper.
Source: Swedish Maritime Administration (Sjofartsverket)
"""

# Source identification
SOURCE_ID = "sma-baltic-subarea"
NAVAREA_ID = "Baltic"

# URLs
SOURCE_URL = "https://navvarn.sjofartsverket.se/en/Navigationsvarningar/VHF"

# Output files
OUTPUT_WARNINGS_FILE = "navareas/baltic/navarea_baltic_warnings.txt"
OUTPUT_PARSED_FILE = "navareas/baltic/parsed_baltic_warnings.json"

# Encoding
ENCODING = "utf-8"

# HTTP settings
USE_CURL_CFFI = True
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
