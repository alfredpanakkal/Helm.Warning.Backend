#!/usr/bin/env python3
"""
run_manual_paste.py — Bulk manual NAVAREA ingestion from pasted text.

Pipeline: pasted bulletin text -> region parser -> Supabase sync.
Reuses the EXACT per-region parser and sync modules the scheduled
pipelines use (no second parser, no parallel logic), so a manually
pasted warning goes through the same deterministic parse, geometry
classification and differential sync as a scraped one.

Usage:
    python -m scripts.run_manual_paste --navarea 8 --input pasted.txt
"""
import argparse
import importlib
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# region key -> (parser module, sync module, staging subdir)
REGIONS = {
    "1":      ("scripts.navarea_1_parser",    "scripts.navarea_1_sync",    "navarea_1"),
    "8":      ("scripts.navarea_8_parser",    "scripts.navarea_8_sync",    "navarea_8"),
    "iv":     ("scripts.navarea_iv_parser",   "scripts.navarea_iv_sync",   "navarea_iv"),
    "xi":     ("scripts.navarea_xi_parser",   "scripts.navarea_xi_sync",   "navarea_xi"),
    "xii":    ("scripts.navarea_xii_parser",  "scripts.navarea_xii_sync",  "navarea_xii"),
    "baltic": ("scripts.baltic_parser",       "scripts.baltic_sync",       "baltic"),
}


def main(argv=None) -> bool:
    ap = argparse.ArgumentParser(description="Bulk ingest pasted NAVAREA warning text")
    ap.add_argument("--navarea", required=True, choices=sorted(REGIONS),
                    help="NAVAREA region of the pasted text")
    ap.add_argument("--input", required=True,
                    help="Path to a text file containing the pasted bulletin")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"ERROR: input file not found: {args.input}")
        return False

    with open(args.input, "r", encoding="utf-8") as f:
        raw_text = f.read()
    if not raw_text.strip():
        print("ERROR: pasted text is empty — nothing to ingest.")
        return False

    parser_mod_name, sync_mod_name, subdir = REGIONS[args.navarea]
    raw_txt = os.path.join("navareas", "manual", subdir, "pasted_raw.txt")
    parsed_json = os.path.join("navareas", "manual", subdir, "parsed.json")
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    os.makedirs(os.path.dirname(parsed_json), exist_ok=True)
    with open(raw_txt, "w", encoding="utf-8") as f:
        f.write(raw_text)

    print("=" * 65)
    print(f"MANUAL BULK PASTE INGEST — NAVAREA {args.navarea.upper()}")
    print(f"({len(raw_text)} chars, {raw_text.count(chr(10)) + 1} lines)")
    print("=" * 65)

    print("\n[STAGE 1] Parsing pasted text (region parser)...")
    parse_main = importlib.import_module(parser_mod_name).main
    parse_success = parse_main(raw_txt, parsed_json)

    print("\n[STAGE 2] Syncing parsed warnings to Supabase...")
    sync_to_supabase = importlib.import_module(sync_mod_name).sync_to_supabase
    sync_success = sync_to_supabase(parsed_json)

    if parse_success is False or sync_success is False:
        print("\nManual paste ingest finished with issues — see log above.")
        return False

    print("\nManual paste ingest completed!")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
