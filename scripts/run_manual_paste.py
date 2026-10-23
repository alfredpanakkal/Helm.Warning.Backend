#!/usr/bin/env python3
"""
run_manual_paste.py — Bulk manual NAVAREA ingestion from pasted text.

Pipeline: pasted bulletin text -> region parser -> Supabase sync.
Reuses the EXACT per-region parser and sync modules the scheduled
pipelines use (no second parser, no parallel logic), so a manually
pasted warning goes through the same deterministic parse, geometry
classification and differential sync as a scraped one.

Regions WITHOUT a dedicated scraper/parser (II, III, V, VI, VII, IX, X)
route through the universal parser + generic sync — same pipeline
contracts, so a region can be promoted to a dedicated parser later by
swapping its registry entry only.

Usage:
    python -m scripts.run_manual_paste --navarea 8 --input pasted.txt
    python -m scripts.run_manual_paste --navarea auto --input pasted.txt
"""
import argparse
import importlib
import os
import re
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# region key -> (parser module, sync module, staging subdir)
# Dedicated scrapers/parsers:
REGIONS = {
    "1":      ("scripts.navarea_1_parser",    "scripts.navarea_1_sync",    "navarea_1"),
    "8":      ("scripts.navarea_8_parser",    "scripts.navarea_8_sync",    "navarea_8"),
    "iv":     ("scripts.navarea_iv_parser",   "scripts.navarea_iv_sync",   "navarea_iv"),
    "xi":     ("scripts.navarea_xi_parser",   "scripts.navarea_xi_sync",   "navarea_xi"),
    "xii":    ("scripts.navarea_xii_parser",  "scripts.navarea_xii_sync",  "navarea_xii"),
    "baltic": ("scripts.baltic_parser",       "scripts.baltic_sync",       "baltic"),
    # No dedicated scraper yet — universal parser + generic sync:
    "ii":     ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_ii"),
    "iii":    ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_iii"),
    "v":      ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_v"),
    "vi":     ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_vi"),
    "vii":    ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_vii"),
    "ix":     ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_ix"),
    "x":      ("scripts.navarea_universal_parser", "scripts.navarea_generic_sync", "navarea_x"),
}

# Region auto-detection from the pasted text header. Longest roman numerals
# are checked first so "VIII" never matches as "I"/"IV" etc. A plain
# "NAVAREA 123/26" (warning number, no numeral) must NOT map anywhere.
_HEADER_PATTERNS = [
    (re.compile(r"NAV\s*AREA\s+XII\b", re.IGNORECASE), "xii"),
    (re.compile(r"NAV\s*AREA\s+XI\b", re.IGNORECASE), "xi"),
    (re.compile(r"NAV\s*AREA\s+X\b", re.IGNORECASE), "x"),
    (re.compile(r"NAV\s*AREA\s+IX\b", re.IGNORECASE), "ix"),
    (re.compile(r"NAV\s*AREA\s+VIII\b", re.IGNORECASE), "8"),
    (re.compile(r"NAV\s*AREA\s+VII\b", re.IGNORECASE), "vii"),
    (re.compile(r"NAV\s*AREA\s+VI\b", re.IGNORECASE), "vi"),
    (re.compile(r"NAV\s*AREA\s+V\b", re.IGNORECASE), "v"),
    (re.compile(r"NAV\s*AREA\s+IV\b", re.IGNORECASE), "iv"),
    (re.compile(r"NAV\s*AREA\s+III\b", re.IGNORECASE), "iii"),
    (re.compile(r"NAV\s*AREA\s+II\b", re.IGNORECASE), "ii"),
    (re.compile(r"NAV\s*AREA\s+I\b", re.IGNORECASE), "1"),
    (re.compile(r"SWEDISH\s+NAV\s+WARN\b", re.IGNORECASE), "baltic"),
]


def detect_navarea(raw_text) -> str | None:
    """Returns the region key implied by the text header, or None.

    The text header is authoritative: the admin's dropdown selection is
    only a fallback (see scripts/run_paste_queue.py).
    """
    if not raw_text:
        return None
    for pattern, region in _HEADER_PATTERNS:
        if pattern.search(raw_text):
            return region
    return None


def main(argv=None) -> bool:
    ap = argparse.ArgumentParser(description="Bulk ingest pasted NAVAREA warning text")
    ap.add_argument("--navarea", required=True, choices=sorted(REGIONS) + ["auto"],
                    help="NAVAREA region of the pasted text ('auto' detects "
                         "from the text header; fails closed if undetectable)")
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

    navarea = args.navarea
    if navarea == "auto":
        navarea = detect_navarea(raw_text)
        if not navarea:
            print("ERROR: --navarea auto could not detect the region from the "
                  "text header — no NAVAREA/Baltic header found. Select the "
                  "region explicitly.")
            return False
        print(f"Auto-detected region: {navarea}")

    parser_mod_name, sync_mod_name, subdir = REGIONS[navarea]
    raw_txt = os.path.join("navareas", "manual", subdir, "pasted_raw.txt")
    parsed_json = os.path.join("navareas", "manual", subdir, "parsed.json")
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    os.makedirs(os.path.dirname(parsed_json), exist_ok=True)
    with open(raw_txt, "w", encoding="utf-8") as f:
        f.write(raw_text)

    print("=" * 65)
    print(f"MANUAL BULK PASTE INGEST — NAVAREA {navarea.upper()}")
    print(f"({len(raw_text)} chars, {raw_text.count(chr(10)) + 1} lines)")
    print("=" * 65)

    print("\n[STAGE 1] Parsing pasted text (region parser)...")
    parse_main = importlib.import_module(parser_mod_name).main
    parse_success = parse_main(raw_txt, parsed_json)

    # Fail closed: a paste that yields ZERO warnings almost certainly has
    # the wrong region selected or an unrecognised format — syncing an
    # empty snapshot could then drive absence/archive logic for that
    # source. Never sync an empty manual paste.
    import json as _json
    try:
        with open(parsed_json, "r", encoding="utf-8") as f:
            parsed = _json.load(f)
        n_warnings = len(parsed.get("nav_warnings") or [])
    except (OSError, ValueError):
        n_warnings = 0
    if n_warnings == 0:
        print("\nERROR: pasted text parsed to 0 warnings — wrong region or "
              "format? Aborting BEFORE sync (empty snapshot not synced).")
        return False
    print(f"\nParse OK: {n_warnings} warning(s) extracted.")

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
