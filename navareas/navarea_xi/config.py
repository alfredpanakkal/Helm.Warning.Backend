#!/usr/bin/env python3
"""
NAVAREA XI Configuration
Configuration for NAVAREA XI navigational warnings scraper.
Source: Japan Coast Guard (JCG)
"""

# Source identification
SOURCE_ID = "kaiho-navarea-xi"
NAVAREA_ID = "XI"

# URLs (3-tier fallback)
SOURCE_URLS = {
    "direct": "https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/disp_warnings.cgi",
    "warnings": "https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/warnings.cgi",
    "mirror": "https://www.sealagom.com/navarea/11/"
}

# Output files
OUTPUT_WARNINGS_FILE = "navareas/navarea_xi/navarea_xi_warnings.txt"
OUTPUT_PARSED_FILE = "navareas/navarea_xi/parsed_navarea_xi_warnings.json"

# Encoding
ENCODING = "cp932"

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
