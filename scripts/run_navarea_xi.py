#!/usr/bin/env python3
"""run_navarea_xi.py — NAVAREA XI Pipeline Runner"""
import sys
import os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
os.makedirs("navareas/navarea_xi", exist_ok=True)
print("=" * 65)
print("🇯🇵 NAVAREA XI PIPELINE")
print("=" * 65)
print("\n[STAGE 1] Scraping...")
from scripts.navarea_xi_scraper import scrape_xi_warnings
scrape_xi_warnings("navareas/navarea_xi/navarea_xi_warnings.txt")
print("\n[STAGE 2] Parsing...")
from scripts.navarea_xi_parser import main as parse_main
parse_main("navareas/navarea_xi/navarea_xi_warnings.txt", "navareas/navarea_xi/parsed_navarea_xi_warnings.json")
print("\n[STAGE 3] Syncing...")
from scripts.navarea_xi_sync import sync_to_supabase
sync_to_supabase("navareas/navarea_xi/parsed_navarea_xi_warnings.json")
print("\n✅ NAVAREA XI pipeline completed!")
