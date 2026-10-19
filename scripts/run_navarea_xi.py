#!/usr/bin/env python3
"""run_navarea_xi.py — NAVAREA XI Pipeline Runner"""
import sys
import os

# Root directory injection for robust module resolution
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def main(raw_txt="navareas/navarea_xi/navarea_xi_warnings.txt",
         parsed_json="navareas/navarea_xi/parsed_navarea_xi_warnings.json") -> bool:
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    os.makedirs(os.path.dirname(parsed_json), exist_ok=True)

    print("=" * 65)
    print("🇯🇵 NAVAREA XI PIPELINE")
    print("=" * 65)

    print("\n[STAGE 1] Scraping...")
    from scripts.navarea_xi_scraper import scrape_xi_warnings
    scrape_xi_warnings(raw_txt)

    print("\n[STAGE 2] Parsing...")
    from scripts.navarea_xi_parser import main as parse_main
    parse_success = parse_main(raw_txt, parsed_json)

    print("\n[STAGE 3] Syncing...")
    from scripts.navarea_xi_sync import sync_to_supabase
    sync_success = sync_to_supabase(parsed_json)

    if parse_success is False or sync_success is False:
        print("\n⚠️ NAVAREA XI pipeline finished with issues.")
        return False

    print("\n✅ NAVAREA XI pipeline completed!")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

