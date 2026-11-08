#!/usr/bin/env python3
"""
run_navarea_8.py — NAVAREA VIII (NHO India) Pipeline Runner
Stage 1: Tiered scrape (NHO table / NHO PDF / SeaLagom mirror) -> navareas/navarea_8/navarea_8_warnings.txt
Stage 2: Deterministic parse        -> navareas/navarea_8/parsed_navarea_8_warnings.json
         VIII_PARSER=universal switches Stage 2 to the universal parser's
         'viii' region config and writes a SIDE-BY-SIDE comparison JSON
         (parsed_navarea_8_warnings.universal.json) — Stage 3 sync is
         SKIPPED in that mode, so the A/B diff never touches the DB.
Stage 3: Supabase differential sync (with CANCEL-ref supersede pass);
         a salvaged partial harvest syncs with full_snapshot=False so absent
         rows are never treated as withdrawn warnings.
"""
import sys
import os
import json

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def main(raw_txt="navareas/navarea_8/navarea_8_warnings.txt",
         parsed_json="navareas/navarea_8/parsed_navarea_8_warnings.json") -> bool:
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    os.makedirs(os.path.dirname(parsed_json), exist_ok=True)

    print("=" * 65)
    print("NAVAREA VIII PIPELINE (NHO INDIA IN-FORCE BULLETIN)")
    print("=" * 65)

    print("\n[STAGE 1] Scraping (tiered: NHO table / PDF / mirror)...")
    from scripts.navarea_8_scraper import scrape_viii_warnings
    try:
        harvest = scrape_viii_warnings(raw_txt)
    except Exception as e:
        print(f"\n[STAGE 1] Scrape FAILED — {e}")
        print("Aborting before parse/sync (existing DB rows untouched).")
        return False

    parser_mode = os.environ.get("VIII_PARSER", "legacy").strip().lower()
    print("\n[STAGE 2] Parsing (VIII_PARSER=" + parser_mode + ")...")
    if parser_mode == "universal":
        # A/B mode: parse through the universal parser's 'viii' region
        # config into a SEPARATE comparison JSON and SKIP the sync —
        # the production parsed JSON and the DB stay untouched until
        # the diff against the legacy output is verified clean.
        ab_output = parsed_json.replace(".json", ".universal.json")
        print("    A/B run: universal output -> " + ab_output
              + " (sync SKIPPED)")
        from scripts.navarea_universal_parser import parse_bulletin_text as parse_universal
        with open(raw_txt, "r", encoding="utf-8") as f:
            content = f.read()
        parsed_data = parse_universal(content, "viii")
        os.makedirs(os.path.dirname(ab_output), exist_ok=True)
        with open(ab_output, "w", encoding="utf-8") as f:
            json.dump(parsed_data, f, indent=2, ensure_ascii=False)
        n = len(parsed_data["nav_warnings"])
        n_geom = len([w for w in parsed_data["nav_warnings"] if w.get("spatial")])
        print("Parsed " + str(n) + " warning(s); " + str(n_geom)
              + " with resolvable geometry.")
        print("\nNAVAREA VIII pipeline finished (A/B comparison run only).")
        return True
    from scripts.navarea_8_parser import main as parse_main
    parse_success = parse_main(raw_txt, parsed_json)

    print("\n[STAGE 3] Syncing...")
    from scripts.navarea_8_sync import sync_to_supabase
    sync_success = sync_to_supabase(
        parsed_json, full_snapshot=harvest.get("full_snapshot", True))

    if parse_success is False or sync_success is False:
        print("\nNAVAREA VIII pipeline finished with issues.")
        return False

    print("\nNAVAREA VIII pipeline completed!")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
