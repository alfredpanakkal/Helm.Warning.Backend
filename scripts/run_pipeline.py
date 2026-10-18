#!/usr/bin/env python3
"""
run_pipeline.py — End-to-End NAVAREA Baltic Ingestion Pipeline
Chains Stage 1 (Scraper), Stage 2 (Parser), and Stage 3 (Supabase Sync).
"""

import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import baltic_scraper
import baltic_parser
import supabase_sync

def main():
    print("=" * 65)
    print("⚓ STARTING NAVAREA BALTIC AUTOMATED INGESTION PIPELINE")
    print("=" * 65)

    # Stage 1: Scrape
    print("\n[STAGE 1] Scraping bulletins from Sjofartsverket VHF endpoint...")
    baltic_scraper.scrape_baltic_warnings(output_filename="navarea_baltic_warnings.txt")

    # Stage 2: Parse
    print("\n[STAGE 2] Parsing bulletins, normalizing WGS84 coords & GeoJSON...")
    baltic_parser.parse_baltic_warnings(input_filename="navarea_baltic_warnings.txt", output_filename="parsed_warnings.json")

    # Stage 3: Sync
    print("\n[STAGE 3] Synchronizing records to Supabase...")
    supabase_sync.sync_to_supabase(json_file="parsed_warnings.json")

    print("\n" + "=" * 65)
    print("🎉 NAVAREA BALTIC PIPELINE EXECUTION COMPLETED")
    print("=" * 65)

if __name__ == "__main__":
    main()
