#!/usr/bin/env python3
"""
run_baltic.py - End-to-End NAVAREA Baltic Ingestion Pipeline
Chains Stage 1 (Scraper), Stage 2 (Parser), and Stage 3 (Supabase Sync) for Baltic.
"""

import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from navareas.baltic.scraper import scrape_baltic_warnings
from navareas.baltic.parser import main as parse_baltic_warnings
from shared.sync import DifferentialSyncEngine
from navareas.baltic.config import (
    SOURCE_ID, OUTPUT_WARNINGS_FILE, OUTPUT_PARSED_FILE,
    VALID_RAW_MESSAGE_COLUMNS, VALID_NAV_WARNING_COLUMNS
)

def main():
    print("=" * 65)
    print("\u2693 STARTING NAVAREA BALTIC AUTOMATED INGESTION PIPELINE")
    print("=" * 65)

    print("\n[STAGE 1] Scraping bulletins from Sjofartsverket VHF endpoint...")
    scrape_baltic_warnings(output_filename=OUTPUT_WARNINGS_FILE)

    print("\n[STAGE 2] Parsing bulletins, normalizing WGS84 coords & GeoJSON...")
    parse_baltic_warnings(
        input_filename=OUTPUT_WARNINGS_FILE,
        output_filename=OUTPUT_PARSED_FILE
    )

    print("\n[STAGE 3] Synchronizing records to Supabase...")
    engine = DifferentialSyncEngine(
        SOURCE_ID,
        VALID_RAW_MESSAGE_COLUMNS,
        VALID_NAV_WARNING_COLUMNS
    )
    success = engine.sync_to_supabase(OUTPUT_PARSED_FILE)

    if not success:
        sys.exit(1)

    print("\n" + "=" * 65)
    print("\ud83c\udf89 NAVAREA BALTIC PIPELINE EXECUTION COMPLETED")
    print("=" * 65)

if __name__ == "__main__":
    main()
