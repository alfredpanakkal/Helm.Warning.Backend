#!/usr/bin/env python3
"""
scrapers/navarea_8.py — NAVAREA VIII (Indian Ocean / NHO India) PDF Scraper
Downloads the latest "NAVAREA VIII - WARNINGS IN FORCE" weekly PDF bulletin
published by the National Hydrographic Office (hydrobharat.gov.in).

The NHO portal is a Liferay/React app that renders its document tables via
JavaScript, so the PDF links are not present in the raw HTML. We render the
page headlessly with Playwright, wait (event-driven) for the PDF anchors to
appear, pick the *newest* bulletin by its "AS ON <date>" caption, and download
it with a browser-like User-Agent and retries.

Run:
    python scrapers/navarea_8.py            # save under navareas/navarea_8/
    python scrapers/navarea_8.py --dry-run  # locate + verify link only, no download
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urljoin

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

BASE_URL = "https://hydrobharat.gov.in"
NAVAREA_PAGE_URL = "https://hydrobharat.gov.in/navarea-warnings"
OUTPUT_DIR = os.environ.get("NAVAREA_8_OUTPUT_DIR", os.path.join("navareas", "navarea_8"))

# How long to wait (seconds) for the JS-rendered PDF anchors to appear.
# Event-driven: the wait ends as soon as a matching anchor is in the DOM.
RENDER_TIMEOUT_S = 90
DOWNLOAD_TIMEOUT_S = 60
DOWNLOAD_RETRIES = 3

# Extra settle time after anchors appear, in case the table is still re-ordering.
SETTLE_DELAY_S = 3

DOWNLOAD_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "accept": "application/pdf,*/*;q=0.8",
    "referer": NAVAREA_PAGE_URL,
}

# e.g. "AS ON 20 MAR 2026", "as on 02 Apr 2026"
DATE_RE = re.compile(r"as\s+on\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", re.IGNORECASE)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_as_on_date(text: str) -> Optional[datetime]:
    """Parses an 'AS ON 20 MAR 2026' style date; returns None if absent/invalid."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        day, mon, year = m.group(1).split()
        month = MONTHS.get(mon[:3].lower())
        if not month:
            return None
        return datetime(int(year), month, int(day))
    except (ValueError, IndexError):
        return None


def collect_pdf_links(html: str) -> List[Tuple[str, str, Optional[datetime]]]:
    """
    Returns a list of (absolute_pdf_url, anchor_text, as_on_date) for every
    NAVAREA-VIII 'warnings in force' PDF anchor found in the rendered HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Tuple[str, str, Optional[datetime]]] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        href_lc = (href + " " + text).lower()
        if ".pdf" not in href_lc or "navarea" not in href_lc:
            continue
        absolute = urljoin(BASE_URL + "/", href)
        if absolute in seen:
            continue
        seen.add(absolute)
        results.append((absolute, text, parse_as_on_date(text) or parse_as_on_date(a.get("title", ""))))

    return results


def pick_latest(links: List[Tuple[str, str, Optional[datetime]]]) -> Optional[Tuple[str, str, Optional[datetime]]]:
    """
    Picks the newest bulletin. Preference order:
      1. The link whose caption carries the latest 'AS ON <date>'.
      2. If no captions carry dates, fall back to the first link in DOM order
         (portal typically lists newest first) and log a warning.
    """
    dated = [l for l in links if l[2] is not None]
    if dated:
        return max(dated, key=lambda l: l[2])
    print("⚠️ No 'AS ON <date>' captions found; falling back to first PDF link in DOM order.")
    return links[0] if links else None


def render_page_html() -> str:
    """Renders the NHO NAVAREA warnings page with headless Chromium and returns its HTML."""
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("playwright is required for this JS-rendered page. "
                           "Install with: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            print(f"🌐 Navigating to {NAVAREA_PAGE_URL} ...")
            # Liferay portals often hold long-poll connections and may never reach
            # 'networkidle'; anchor on the DOM and then wait for PDF links instead.
            page.goto(NAVAREA_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
            print(f"⏳ Waiting up to {RENDER_TIMEOUT_S}s for JS to render the PDF table...")
            page.wait_for_selector("a[href*='.pdf' i]", timeout=RENDER_TIMEOUT_S * 1000)
            # Give a still-rendering table a moment to finish re-ordering/updating.
            time.sleep(SETTLE_DELAY_S)
            html = page.content()
        finally:
            browser.close()

    return html


def download_pdf(pdf_url: str, output_dir: str, dry_run: bool = False) -> Optional[str]:
    """Downloads the bulletin PDF with retries; returns the local file path."""
    os.makedirs(output_dir, exist_ok=True)
    as_on = ""

    if dry_run:
        print(f"🧪 [DRY-RUN] Would download: {pdf_url}")
        return None

    last_err: Optional[Exception] = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            response = requests.get(pdf_url, headers=DOWNLOAD_HEADERS, timeout=DOWNLOAD_TIMEOUT_S, stream=True)
            response.raise_for_status()

            content_type = (response.headers.get("content-type") or "").lower()
            first_bytes = b""
            chunks = []
            for chunk in response.iter_content(chunk_size=65536):
                if not first_bytes:
                    first_bytes = chunk[:5]
                chunks.append(chunk)
            payload = b"".join(chunks)

            # hydrobharat sometimes serves an HTML error page with HTTP 200;
            # verify the payload really looks like a PDF before saving.
            if not first_bytes.startswith(b"%PDF") or "pdf" not in content_type:
                raise RuntimeError(
                    f"Response is not a PDF (content-type: {content_type!r}, "
                    f"magic: {first_bytes!r}); possible portal error page"
                )

            # Dated filename; also refresh a stable 'latest' copy for downstream jobs.
            filename = os.path.basename(pdf_url.split("?")[0]).strip() or "navarea_8_warnings.pdf"
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            dated_path = os.path.join(output_dir, filename)
            latest_path = os.path.join(output_dir, "latest_warnings.pdf")

            with open(dated_path, "wb") as f:
                f.write(payload)
            with open(latest_path, "wb") as f:
                f.write(payload)

            size_kb = len(payload) / 1024
            print(f"✅ PDF saved to {dated_path} ({size_kb:.1f} KB); refreshed {latest_path}")
            return dated_path
        except Exception as e:
            last_err = e
            print(f"⚠️ Download attempt {attempt}/{DOWNLOAD_RETRIES} failed: {e}")
            if attempt < DOWNLOAD_RETRIES:
                time.sleep(2 * attempt)

    raise RuntimeError(f"PDF download failed after {DOWNLOAD_RETRIES} attempts: {last_err}")


def run_navarea_8_scraper(output_dir: str = OUTPUT_DIR, dry_run: bool = False) -> dict:
    """
    Executes the NAVAREA VIII bulletin scraper.
    Returns a summary dict: {pdf_url, as_on_date, saved_path, dry_run, errors}
    Raises on unrecoverable failure (caller decides exit code).
    """
    print("=" * 70)
    print("⚓ NAVAREA VIII (NHO India) PDF Scraper")
    print(f"📡 Source page: {NAVAREA_PAGE_URL}")
    print(f"📁 Output dir: {output_dir}")
    print("=" * 70)

    summary = {
        "pdf_url": None,
        "as_on_date": None,
        "saved_path": None,
        "pdf_links_found": 0,
        "dry_run": dry_run,
        "errors": "",
    }

    if not HAS_REQUESTS or not HAS_BS4:
        raise RuntimeError("requests and beautifulsoup4 are required. Run: pip install -r requirements.txt")

    html = render_page_html()
    links = collect_pdf_links(html)
    summary["pdf_links_found"] = len(links)
    print(f"🔗 Found {len(links)} NAVAREA PDF link(s) on the page.")

    if not links:
        raise RuntimeError(
            "No NAVAREA PDF links found in the rendered HTML. The portal layout "
            "may have changed; inspect " + NAVAREA_PAGE_URL + " manually."
        )

    chosen = pick_latest(links)
    pdf_url, caption, as_on = chosen
    summary["pdf_url"] = pdf_url
    summary["as_on_date"] = as_on.strftime("%Y-%m-%d") if as_on else None
    print(f"📌 Selected: {pdf_url}")
    if caption:
        print(f"   Caption: {caption!r}")
    if as_on:
        print(f"   Bulletin date (AS ON): {as_on.strftime('%d %b %Y')}")

    saved = download_pdf(pdf_url, output_dir, dry_run=dry_run)
    summary["saved_path"] = saved

    # GitHub Actions step summary
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as sf:
                sf.write(f"""### ⚓ NAVAREA VIII PDF Scraper Summary
| Metric | Value |
| :--- | :--- |
| **Source Page** | {NAVAREA_PAGE_URL} |
| **PDF Links Found** | {summary['pdf_links_found']} |
| **Selected Bulletin Date** | {summary['as_on_date'] or 'unknown (DOM-order fallback)'} |
| **PDF URL** | {pdf_url} |
| **Saved To** | {summary['saved_path'] or '(dry-run)'} |
| **Execution Mode** | {'Dry-Run' if dry_run else 'Live'} |
""")
        except Exception:
            pass

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="NAVAREA VIII (NHO India) bulletin PDF scraper")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Directory for downloaded PDFs")
    parser.add_argument("--dry-run", action="store_true", help="Locate the PDF without downloading")
    args = parser.parse_args()

    try:
        run_navarea_8_scraper(output_dir=args.output_dir, dry_run=args.dry_run)
        return 0
    except Exception as e:
        print(f"❌ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
