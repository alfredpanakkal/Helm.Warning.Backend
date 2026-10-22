#!/usr/bin/env python3
"""
navarea_8_scraper.py — NAVAREA VIII (NHO India) Stage-1 Scraper Wrapper
Downloads the latest 'NAVAREA VIII - Warnings In Force' PDF via
scrapers/navarea_8.py and extracts its full text into the pipeline's
standard raw-text file (navareas/navarea_8/navarea_8_warnings.txt).

The PDF itself is kept alongside (latest_warnings.pdf) for audit/grounding.
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
    """Runs the PDF scraper and writes extracted text to raw_txt. Returns the text."""
    from scrapers.navarea_8 import run_navarea_8_scraper

    summary = run_navarea_8_scraper(output_dir=OUTPUT_DIR, dry_run=False)
    pdf_path = summary.get("saved_path")
    if not pdf_path:
        raise RuntimeError("NAVAREA VIII PDF was not saved (dry-run or failure).")

    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf is required for NAVAREA VIII PDF text extraction. "
                           "Install with: pip install pypdf")

    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        pages.append(page.extract_text() or "")
    text = "\n".join(pages)

    if not os.path.isabs(raw_txt):
        raw_txt = os.path.join(ROOT_DIR, raw_txt)
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    with open(raw_txt, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Extracted {len(reader.pages)} PDF page(s) -> {raw_txt} ({len(text)} chars)")
    if not text.strip():
        raise RuntimeError("PDF text extraction produced empty text; bulletin may be "
                            "scanned images or the layout changed.")
    return text


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "navareas/navarea_8/navarea_8_warnings.txt"
    try:
        scrape_viii_warnings(target)
        sys.exit(0)
    except Exception as e:
        print(f"NAVAREA VIII scrape failed: {e}", file=sys.stderr)
        sys.exit(1)
