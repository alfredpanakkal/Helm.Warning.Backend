#!/usr/bin/env python3
"""
scrapers/navarea_8.py — NAVAREA VIII (Indian Ocean / NHO India) PDF Scraper
Downloads the latest "NAVAREA VIII - WARNINGS IN FORCE" weekly PDF bulletin
published by the National Hydrographic Office (hydrobharat.gov.in).

Strategy:
  1. FAST PATH: fetch the page with plain `requests` first (cheap). The NHO
     portal sometimes serves cached/static HTML that already contains the PDF
     anchors — if so, we skip the browser entirely.
  2. FALLBACK: if no PDF links are found in the static HTML, render the page
     headlessly with Playwright (the portal is a Liferay/React app) and wait
     event-driven for the PDF anchors to appear.
  3. Select the *newest* bulletin by its "AS ON <date>" caption.
  4. Download it (retries via shared.retry), verify it is a real PDF, skip
     if we already have the identical dated file, and warn if the bulletin
     looks stale.

Run:
    python scrapers/navarea_8.py            # save under navareas/navarea_8/
    python scrapers/navarea_8.py --dry-run  # locate + verify link only, no download
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timedelta
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
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    from shared.logging import get_logger, setup_logging
    from shared.retry import retry
    HAS_SHARED = True
except ImportError:
    HAS_SHARED = False

logger = get_logger("scraper.navarea_8")

BASE_URL = "https://hydrobharat.gov.in"
NAVAREA_PAGE_URL = "https://hydrobharat.gov.in/navarea-warnings"
OUTPUT_DIR = os.environ.get("NAVAREA_8_OUTPUT_DIR", os.path.join("navareas", "navarea_8"))

# How long to wait (seconds) for the JS-rendered PDF anchors to appear.
RENDER_TIMEOUT_S = 90
DOWNLOAD_TIMEOUT_S = 60
DOWNLOAD_RETRIES = 3

# Extra settle time after anchors appear, in case the table is still re-ordering.
SETTLE_DELAY_S = 3

# Warn (do not fail) if the selected bulletin is older than this many days.
STALENESS_WARN_DAYS = 14

BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-IN,en;q=0.9",
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
    NAVAREA-VIII 'warnings in force' PDF anchor found in the HTML.
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
    logger.warning("No 'AS ON <date>' captions found; falling back to first PDF link in DOM order.")
    return links[0] if links else None


# ---------------------------------------------------------------------------
# Step 1: fast-path static fetch; Step 2: Playwright fallback
# ---------------------------------------------------------------------------

@retry(max_attempts=2, delay=2.0, exceptions=(Exception,))
def fetch_page_static() -> Optional[str]:
    """
    FAST PATH: plain HTTP GET of the warnings page.
    Returns the HTML if the request succeeds, else raises (handled by retry).
    The caller checks whether PDF links are present before trusting this.
    """
    logger.info("⚡ Fast path: fetching page with plain requests...", extra={"url": NAVAREA_PAGE_URL})
    response = requests.get(NAVAREA_PAGE_URL, headers=BROWSER_HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def render_page_html() -> str:
    """FALLBACK: renders the NHO NAVAREA warnings page with headless Chromium."""
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("playwright is required for this JS-rendered page. "
                           "Install with: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            logger.info(f"🌐 Fallback: navigating with headless Chromium to {NAVAREA_PAGE_URL} ...")
            # Liferay portals often hold long-poll connections and may never reach
            # 'networkidle'; anchor on the DOM and then wait for PDF links instead.
            page.goto(NAVAREA_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
            logger.info(f"⏳ Waiting up to {RENDER_TIMEOUT_S}s for JS to render the PDF table...")
            page.wait_for_selector("a[href*='.pdf' i]", timeout=RENDER_TIMEOUT_S * 1000)
            # Give a still-rendering table a moment to finish re-ordering/updating.
            time.sleep(SETTLE_DELAY_S)
            html = page.content()
        finally:
            browser.close()

    return html


def get_pdf_links() -> Tuple[List[Tuple[str, str, Optional[datetime]]], str]:
    """
    Tries the fast static path first; falls back to Playwright rendering
    if the static HTML carries no NAVAREA PDF links.
    Returns (links, method) where method is 'static' or 'playwright'.
    """
    # --- Fast path ---------------------------------------------------------
    if HAS_REQUESTS and HAS_BS4:
        try:
            static_html = fetch_page_static()
            links = collect_pdf_links(static_html)
            if links:
                logger.info(f"⚡ Fast path succeeded: {len(links)} PDF link(s) found without a browser.")
                return links, "static"
            logger.info("Fast path found no PDF links (JS-rendered page); falling back to Playwright.")
        except Exception as e:
            logger.warning(f"Static fetch failed ({e}); falling back to Playwright.")

    # --- Fallback ----------------------------------------------------------
    html = render_page_html()
    links = collect_pdf_links(html)
    return links, "playwright"


# ---------------------------------------------------------------------------
# Step 3+4: staleness check, download, verify, idempotent save
# ---------------------------------------------------------------------------

def check_staleness(as_on: Optional[datetime]) -> None:
    """Warns (never fails) if the selected bulletin is older than STALENESS_WARN_DAYS."""
    if as_on is None:
        return
    age_days = (datetime.now() - as_on).days
    if age_days > STALENESS_WARN_DAYS:
        logger.warning(
            f"Bulletin looks stale: 'AS ON {as_on.strftime('%d %b %Y')}' is {age_days} days old "
            f"(threshold: {STALENESS_WARN_DAYS}). The portal may not have published a newer weekly bulletin.",
            extra={"as_on": as_on.isoformat(), "age_days": age_days},
        )


@retry(max_attempts=DOWNLOAD_RETRIES, delay=2.0, backoff=1.5, exceptions=(Exception,))
def _fetch_pdf_bytes(pdf_url: str) -> Tuple[bytes, str]:
    """Single download attempt. Returns (payload, content_type). Raises if not a real PDF."""
    headers = dict(BROWSER_HEADERS)
    headers["accept"] = "application/pdf,*/*;q=0.8"
    headers["referer"] = NAVAREA_PAGE_URL

    response = requests.get(pdf_url, headers=headers, timeout=DOWNLOAD_TIMEOUT_S, stream=True)
    response.raise_for_status()

    content_type = (response.headers.get("content-type") or "").lower()
    chunks = []
    for chunk in response.iter_content(chunk_size=65536):
        chunks.append(chunk)
    payload = b"".join(chunks)

    # hydrobharat sometimes serves an HTML error page with HTTP 200;
    # verify the payload really looks like a PDF before saving.
    if not payload[:5].startswith(b"%PDF") or "pdf" not in content_type:
        raise RuntimeError(
            f"Response is not a PDF (content-type: {content_type!r}, "
            f"magic: {payload[:5]!r}); possible portal error page"
        )
    return payload, content_type


def download_pdf(pdf_url: str, output_dir: str, dry_run: bool = False) -> Optional[str]:
    """
    Downloads the bulletin PDF with retries; returns the local file path.
    Skips the download when the dated file already exists on disk (idempotent).
    """
    os.makedirs(output_dir, exist_ok=True)

    filename = os.path.basename(pdf_url.split("?")[0]).strip() or "navarea_8_warnings.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    dated_path = os.path.join(output_dir, filename)
    latest_path = os.path.join(output_dir, "latest_warnings.pdf")

    if os.path.exists(dated_path) and os.path.getsize(dated_path) > 0:
        logger.info(f"📦 Bulletin already on disk, skipping download: {dated_path}")
        # Keep the stable 'latest' copy in sync in case it drifted.
        with open(dated_path, "rb") as src, open(latest_path, "wb") as dst:
            dst.write(src.read())
        return dated_path

    if dry_run:
        logger.info(f"🧪 [DRY-RUN] Would download: {pdf_url}")
        return None

    payload, _ = _fetch_pdf_bytes(pdf_url)

    with open(dated_path, "wb") as f:
        f.write(payload)
    with open(latest_path, "wb") as f:
        f.write(payload)

    logger.info(f"✅ PDF saved to {dated_path} ({len(payload)/1024:.1f} KB); refreshed {latest_path}")
    return dated_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_navarea_8_scraper(output_dir: str = OUTPUT_DIR, dry_run: bool = False) -> dict:
    """
    Executes the NAVAREA VIII bulletin scraper.
    Returns a summary dict; raises on unrecoverable failure.
    """
    if HAS_SHARED:
        setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    logger.info("=" * 60)
    logger.info("⚓ NAVAREA VIII (NHO India) PDF Scraper")
    logger.info(f"📡 Source page: {NAVAREA_PAGE_URL}")
    logger.info(f"📁 Output dir: {output_dir}")

    summary = {
        "pdf_url": None,
        "as_on_date": None,
        "saved_path": None,
        "pdf_links_found": 0,
        "fetch_method": None,
        "skipped_existing": False,
        "dry_run": dry_run,
        "errors": "",
    }

    if not HAS_REQUESTS or not HAS_BS4:
        raise RuntimeError("requests and beautifulsoup4 are required. Run: pip install -r requirements.txt")

    links, method = get_pdf_links()
    summary["pdf_links_found"] = len(links)
    summary["fetch_method"] = method
    logger.info(f"🔗 Found {len(links)} NAVAREA PDF link(s) via {method}.")

    if not links:
        raise RuntimeError(
            "No NAVAREA PDF links found in the rendered HTML. The portal layout "
            "may have changed; inspect " + NAVAREA_PAGE_URL + " manually."
        )

    chosen = pick_latest(links)
    pdf_url, caption, as_on = chosen
    summary["pdf_url"] = pdf_url
    summary["as_on_date"] = as_on.strftime("%Y-%m-%d") if as_on else None
    logger.info(f"📌 Selected: {pdf_url}")
    if caption:
        logger.info(f"   Caption: {caption!r}")
    if as_on:
        logger.info(f"   Bulletin date (AS ON): {as_on.strftime('%d %b %Y')}")

    check_staleness(as_on)

    already = summary.get("saved_path")
    saved = download_pdf(pdf_url, output_dir, dry_run=dry_run)
    summary["saved_path"] = saved
    summary["skipped_existing"] = bool(saved and os.path.exists(saved) and saved == already)

    # GitHub Actions step summary
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as sf:
                sf.write(f"""### ⚓ NAVAREA VIII PDF Scraper Summary
| Metric | Value |
| :--- | :--- |
| **Fetch Method** | {summary['fetch_method']} |
| **PDF Links Found** | {summary['pdf_links_found']} |
| **Selected Bulletin Date** | {summary['as_on_date'] or 'unknown (DOM-order fallback)'} |
| **PDF URL** | {pdf_url} |
| **Saved To** | {summary['saved_path'] or '(dry-run)'} |
| **Skipped (already on disk)** | {'Yes' if summary['skipped_existing'] else 'No'} |
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
        logger.error(f"❌ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
