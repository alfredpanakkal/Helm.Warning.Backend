#!/usr/bin/env python3
"""
navarea_8_scraper.py — NAVAREA VIII (NHO India) Stage-1 Scraper Wrapper
Delegates to scrapers/navarea_8.py's tiered acquisition chain:
  pdf-route -> nho-page-text -> sealagom-mirror
Each tier is sanity-validated (>= MIN_EXPECTED_WARNINGS headers); the first
tier to yield a real bulletin wins. The wrapper guarantees the pipeline's
standard raw-text file exists afterwards.
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = os.path.join("navareas", "navarea_8")


def scrape_viii_warnings(raw_txt="navareas/navarea_8/navarea_8_warnings.txt") -> str:
    """Runs the tiered acquisition and ensures raw_txt is populated. Returns the text."""
    from scrapers.navarea_8 import run_navarea_8_scraper

    summary = run_navarea_8_scraper(output_dir=OUTPUT_DIR, dry_run=False)
    text = summary.get("bulletin_text")
    if not text:
        raise RuntimeError("Tiered acquisition returned no bulletin text.")

    if not os.path.isabs(raw_txt):
        raw_txt = os.path.join(ROOT_DIR, raw_txt)
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    with open(raw_txt, "w", encoding="utf-8") as f:
        f.write(text)

    tier = summary.get("source_tier")
    n = summary.get("warning_count")
    print(f"Acquired bulletin via tier '{tier}' ({n} warnings, {len(text)} chars) -> {raw_txt}")
    return text


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "navareas/navarea_8/navarea_8_warnings.txt"
    try:
        scrape_viii_warnings(target)
        sys.exit(0)
    except Exception as e:
        print(f"NAVAREA VIII scrape failed: {e}", file=sys.stderr)
        sys.exit(1)
