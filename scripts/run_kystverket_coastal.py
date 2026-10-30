#!/usr/bin/env python3
"""run_kystverket_coastal.py — Norwegian Coastal Warnings Pipeline Runner
(scrape -> parse -> sync)."""
import sys
import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> bool:
    print("=" * 65)
    print("NORWEGIAN COASTAL WARNINGS (KYSTVERKET) PIPELINE")
    print("=" * 65)

    from scripts.kystverket_coastal_scraper import main as scrape_main
    return scrape_main()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
