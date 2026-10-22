#!/usr/bin/env python3
"""
navarea_8_scraper.py — NAVAREA VIII (NHO India) Stage-1 Scraper Wrapper
Acquires the latest 'NAVAREA VIII - Warnings In Force' bulletin text.

Acquisition tiers (in order, first success wins):
  TIER 1 (preferred): NHO portal warnings TABLE via scrapers/navarea_8_table.py
       (Playwright; auto-presses 'Next' until every paginated page is
       scraped). Emits both structured rows (navarea_8_table.json) and
       synthesized bulletin text.
  TIER 2 (authoritative PDF): NHO portal PDF via scrapers/navarea_8.py
       (requests fast-path, Playwright fallback) + pypdf text extraction.
       Used when the table cannot be scraped (e.g. portal redesign).
  TIER 3 (fallback): SeaLagom NAVAREA VIII mirror (sealagom.com/navarea/8) —
       anonymous plain-requests fetch of the same in-force bulletin text,
       community-contributed. Used only when both NHO tiers fail.

Writes the raw text to navareas/navarea_8/navarea_8_warnings.txt; structured
table rows are kept alongside (navarea_8_table.json) for audit/grounding.
"""

import os
import sys
import re

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = os.path.join("navareas", "navarea_8")
MIRROR_URL = "https://www.sealagom.com/navarea/8/"
MIRROR_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
# Minimum sanity: in-force bulletins carry dozens of warnings; fewer than
# this suggests we captured an error page or a truncated document.
MIN_EXPECTED_WARNINGS = 5


def _fetch_tier1_table() -> str:
    """NHO table acquisition (auto-pagination). Returns synthesized text."""
    from scrapers.navarea_8_table import run_navarea_8_table_scraper

    summary = run_navarea_8_table_scraper(
        output_dir=OUTPUT_DIR, dry_run=False,
        raw_txt=os.path.join(OUTPUT_DIR, "navarea_8_warnings.txt"))
    n = summary.get("warnings") or 0
    if n < MIN_EXPECTED_WARNINGS:
        raise RuntimeError(
            f"Tier 1 (NHO table): only {n} warning(s) collected "
            f"(threshold {MIN_EXPECTED_WARNINGS}); possible partial scrape.")

    txt_path = os.path.join(ROOT_DIR, OUTPUT_DIR, "navarea_8_warnings.txt")
    with open(txt_path, "r", encoding="utf-8") as f:
        return f.read()


def _fetch_tier2_pdf() -> str:
    """NHO PDF acquisition + pypdf extraction. Returns extracted text."""
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

    if not text.strip():
        raise RuntimeError("PDF text extraction produced empty text; bulletin may be "
                            "scanned images or the layout changed.")
    return text


def _fetch_tier3_mirror() -> str:
    """SeaLagom mirror: anonymous requests fetch of the in-force text."""
    import requests

    print(f"[Tier 3] Falling back to SeaLagom mirror: {MIRROR_URL}")
    resp = requests.get(
        MIRROR_URL,
        headers={
            "User-Agent": MIRROR_UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30,
    )
    resp.raise_for_status()
    html = resp.text

    # Strip scripts/styles/tags to plain text (same approach as the proven
    # nho_fetch.py pipeline from hydrobharat-navarea-scraper).
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    return text


def _validate(text: str, tier: str) -> None:
    n = len(re.findall(r"NAVAREA\s+VIII\s*[-\u2013]?\s*\d{1,4}\s*/\s*\d{2}", text, re.IGNORECASE))
    if n < MIN_EXPECTED_WARNINGS:
        raise RuntimeError(
            f"{tier}: only {n} warning header(s) found (threshold {MIN_EXPECTED_WARNINGS}); "
            "possible error page or truncated document."
        )
    print(f"[{tier}] Sanity check passed: {n} warning header(s) detected.")


def scrape_viii_warnings(raw_txt="navareas/navarea_8/navarea_8_warnings.txt") -> str:
    """Runs the tiered acquisition and writes raw text to raw_txt. Returns the text."""
    text = None
    errors = []
    tiers = (("Tier 1 (NHO table)", _fetch_tier1_table),
             ("Tier 2 (NHO PDF)", _fetch_tier2_pdf),
             ("Tier 3 (SeaLagom mirror)", _fetch_tier3_mirror))
    for tier_name, fetcher in tiers:
        try:
            candidate = fetcher()
            _validate(candidate, tier_name)
            text = candidate
            print(f"[+] Acquisition succeeded via {tier_name}")
            break
        except Exception as e:
            print(f"[!] {tier_name} failed: {e}")
            errors.append(f"{tier_name}: {e}")

    if text is None:
        raise RuntimeError("All acquisition tiers failed: " + " | ".join(errors))

    if not os.path.isabs(raw_txt):
        raw_txt = os.path.join(ROOT_DIR, raw_txt)
    os.makedirs(os.path.dirname(raw_txt), exist_ok=True)
    with open(raw_txt, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Extracted {len(text)} chars -> {raw_txt}")
    return text


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "navareas/navarea_8/navarea_8_warnings.txt"
    try:
        scrape_viii_warnings(target)
        sys.exit(0)
    except Exception as e:
        print(f"NAVAREA VIII scrape failed: {e}", file=sys.stderr)
        sys.exit(1)
