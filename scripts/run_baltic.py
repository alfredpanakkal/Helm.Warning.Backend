#!/usr/bin/env python3
"""run_baltic.py — NAVAREA Baltic Pipeline Runner"""
import sys
import os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
os.makedirs("navareas/baltic", exist_ok=True)
print("=" * 65)
print("⚓ NAVAREA BALTIC PIPELINE")
print("=" * 65)
print("\n[STAGE 1] Scraping...")
from scripts.baltic_scraper import scrape_baltic_warnings
scrape_baltic_warnings("navareas/baltic/navarea_baltic_warnings.txt")
print("\n[STAGE 2] Parsing...")
from scripts.baltic_parser import main as parse_main
parse_main("navareas/baltic/navarea_baltic_warnings.txt", "navareas/baltic/parsed_baltic_warnings.json")
print("\n[STAGE 3] Syncing...")
from scripts.baltic_sync import sync_to_supabase
sync_to_supabase("navareas/baltic/parsed_baltic_warnings.json")
print("\n✅ NAVAREA Baltic pipeline completed!")
