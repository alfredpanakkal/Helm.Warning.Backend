#!/usr/bin/env python3
"""run_navarea_1.py — NAVAREA I Pipeline Runner"""
import sys
import os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
os.makedirs("navareas/navarea_1", exist_ok=True)
print("=" * 65)
print("🎯 NAVAREA I PIPELINE")
print("=" * 65)
print("\n[STAGE 1] Scraping...")
from scripts.navarea_1_scraper import scrape_navarea_warnings
scrape_navarea_warnings("navareas/navarea_1/navarea_1_warnings.txt")
print("\n[STAGE 2] Parsing...")
from scripts.navarea_1_parser import main as parse_main
parse_main("navareas/navarea_1/navarea_1_warnings.txt", "navareas/navarea_1/parsed_navarea_1_warnings.json")
print("\n[STAGE 3] Syncing...")
from scripts.navarea_1_sync import sync_to_supabase
sync_to_supabase("navareas/navarea_1/parsed_navarea_1_warnings.json")
print("\n✅ NAVAREA I pipeline completed!")
