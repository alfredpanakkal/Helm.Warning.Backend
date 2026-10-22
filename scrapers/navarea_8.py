#!/usr/bin/env python3
"""
scrapers/navarea_8.py — NAVAREA VIII (NHO India) Bulletin Scraper (Tiered)

Architecture distilled from the proven successful runs of
hydrobharat-navarea-scraper: a chain of independent acquisition tiers,
each sanity-validated, first tier to yield a real bulletin wins. No single
tier failure can break ingestion, and 'empty success' is impossible.

Tiers (in order):
  1. NHO page via plain requests  -> PDF link -> PDF download -> pypdf text
  2. NHO page via Scrapling StealthyFetcher (Camoufox stealth render,
     no Playwright process management) -> PDF -> pypdf text
  3. NHO page via Playwright headless Chromium -> PDF -> pypdf text
  4. NHO public page rendered text (StealthyFetcher) parsed directly
  5. SeaLagom NAVAREA VIII mirror (anonymous, no auth, always-fresh
     community copy of the same in-force bulletin)

Design rules (from the old repo's post-mortem):
  - Never trust an empty/near-empty result: every tier must clear
    MIN_EXPECTED_WARNINGS warning headers or it is treated as failed.
  - Auth-gated endpoints (Liferay dlapp, nho-headless JSON) are NOT used:
    anonymous access is denied and credentials rot — that is what broke
    the previous pipeline. Only anonymous tiers here.
  - The bulletin PDF is saved alongside for audit/grounding whenever a
    PDF tier succeeds.

Run:
    python scrapers/navarea_8.py            # writes text + audit PDF
    python scrapers/navarea_8.py --dry-run  # tier probe only, no writes
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
MIRROR_URL = "https://www.sealagom.com/navarea/8/"
OUTPUT_DIR = os.environ.get("NAVAREA_8_OUTPUT_DIR", os.path.join("navareas", "navarea_8"))

RENDER_TIMEOUT_S = 90
DOWNLOAD_TIMEOUT_S = 60
DOWNLOAD_RETRIES = 3
SETTLE_DELAY_S = 3
STALENESS_WARN_DAYS = 14

# Post-mortem rule: an in-force bulletin carries dozens of warnings. A tier
# yielding fewer than this is an error page / truncated doc / degraded parse,
# NOT a success (the old Node pipeline 'succeeded' with 1/50 warnings upserted).
MIN_EXPECTED_WARNINGS = 10

BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
}

# Matches both observed forms: 'NAVAREA VIII 1066/26' and 'NAVAREA VIII -1102/26'
RE_WARNING_HEADER = re.compile(r"NAVAREA\s+VIII\s*[-\u2013]?\s*\d{1,4}\s*/\s*\d{2}", re.IGNORECASE)
RE_AS_ON = re.compile(r"WARNINGS?\s+IN\s+FORCE\s+AS\s+ON\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", re.IGNORECASE)
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def parse_as_on_date(text: str) -> Optional[datetime]:
    m = RE_AS_ON.search(text or "")
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


def clean_html_text(text: str) -> str:
    """HTML -> plain text (proven routine from nho_fetch.py)."""
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    return text


def validate_bulletin_text(text: str, tier_name: str) -> int:
    """Post-mortem guard: near-empty text is a FAILURE, not a success."""
    n = len(RE_WARNING_HEADER.findall(text))
    if n < MIN_EXPECTED_WARNINGS:
        raise RuntimeError(
            f"{tier_name}: only {n} warning header(s) found "
            f"(threshold {MIN_EXPECTED_WARNINGS}); error page or truncated document."
        )
    return n


def check_staleness(as_on: Optional[datetime]) -> None:
    if as_on is None:
        return
    age_days = (datetime.now() - as_on).days
    if age_days > STALENESS_WARN_DAYS:
        logger.warning(
            f"Bulletin looks stale: 'AS ON {as_on.strftime('%d %b %Y')}' is {age_days} days old "
            f"(threshold {STALENESS_WARN_DAYS}).",
            extra={"as_on": as_on.isoformat(), "age_days": age_days},
        )


# ---------------------------------------------------------------------------
# PDF link discovery (static / Scrapling / Playwright renderers)
# ---------------------------------------------------------------------------

def collect_pdf_links(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if ".pdf" not in (href + " " + text).lower() or "navarea" not in (href + " " + text).lower():
            continue
        absolute = urljoin(BASE_URL + "/", href)
        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return links


def _scrapling_fetch_text(url: str, timeout: int = 90) -> Optional[str]:
    """Scrapling StealthyFetcher (Camoufox stealth render). Proven in the old
    pipeline for this exact JS-rendered Liferay portal. Lazy import: tiers
    that don't need it still work when scrapling isn't installed."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        logger.info("scrapling not installed; skipping StealthyFetcher tier.")
        return None
    try:
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True,
                                     stealthy_headers=True, timeout=timeout)
    except Exception as e:
        logger.warning(f"StealthyFetcher failed for {url}: {e}")
        return None
    if page.status >= 400:
        logger.warning(f"StealthyFetcher got HTTP {page.status} for {url}")
        return None
    return page.get_all_text() if hasattr(page, "get_all_text") else str(page.body)


def render_page_html() -> str:
    """Playwright fallback render (kept for environments without scrapling)."""
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("playwright is required for this JS-rendered page. "
                           "Install with: pip install playwright && playwright install chromium")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            logger.info(f"Navigating with headless Chromium to {NAVAREA_PAGE_URL} ...")
            page.goto(NAVAREA_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("a[href*='.pdf' i]", timeout=RENDER_TIMEOUT_S * 1000)
            time.sleep(SETTLE_DELAY_S)
            return page.content()
        finally:
            browser.close()


def discover_pdf_links() -> Tuple[List[str], str]:
    """Static -> Scrapling -> Playwright. Returns (links, method)."""
    if HAS_REQUESTS and HAS_BS4:
        try:
            resp = requests.get(NAVAREA_PAGE_URL, headers=BROWSER_HEADERS, timeout=30)
            resp.raise_for_status()
            links = collect_pdf_links(resp.text)
            if links:
                return links, "static-requests"
        except Exception as e:
            logger.warning(f"Static fetch failed ({e}).")

    html = _scrapling_fetch_text(NAVAREA_PAGE_URL)
    if html and HAS_BS4:
        links = collect_pdf_links(html)
        if links:
            return links, "scrapling-stealthy"

    html = render_page_html()
    return collect_pdf_links(html), "playwright"


# ---------------------------------------------------------------------------
# PDF download + text extraction
# ---------------------------------------------------------------------------

@retry(max_attempts=DOWNLOAD_RETRIES, delay=2.0, backoff=1.5, exceptions=(Exception,))
def _fetch_pdf_bytes(pdf_url: str) -> bytes:
    headers = dict(BROWSER_HEADERS)
    headers["accept"] = "application/pdf,*/*;q=0.8"
    headers["referer"] = NAVAREA_PAGE_URL
    response = requests.get(pdf_url, headers=headers, timeout=DOWNLOAD_TIMEOUT_S, stream=True)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    payload = b"".join(response.iter_content(chunk_size=65536))
    if not payload[:5].startswith(b"%PDF") or "pdf" not in content_type:
        raise RuntimeError(f"Response is not a PDF (content-type: {content_type!r}); "
                            f"possible portal error page")
    return payload


def extract_pdf_text(pdf_path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf is required for NAVAREA VIII PDF text extraction.")
    reader = PdfReader(pdf_path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise RuntimeError("PDF text extraction produced empty text; bulletin may be scanned images.")
    return text


def download_pdf(pdf_url: str, output_dir: str) -> str:
    """Downloads and saves the bulletin PDF (dated name + latest copy)."""
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.basename(pdf_url.split("?")[0]).strip() or "navarea_8_warnings.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    dated_path = os.path.join(output_dir, filename)
    latest_path = os.path.join(output_dir, "latest_warnings.pdf")

    if os.path.exists(dated_path) and os.path.getsize(dated_path) > 0:
        logger.info(f"Bulletin already on disk, skipping download: {dated_path}")
        with open(dated_path, "rb") as src, open(latest_path, "wb") as dst:
            dst.write(src.read())
        return dated_path

    payload = _fetch_pdf_bytes(pdf_url)
    with open(dated_path, "wb") as f:
        f.write(payload)
    with open(latest_path, "wb") as f:
        f.write(payload)
    logger.info(f"PDF saved to {dated_path} ({len(payload)/1024:.1f} KB); refreshed {latest_path}")
    return dated_path


# ---------------------------------------------------------------------------
# Acquisition tiers
# ---------------------------------------------------------------------------

def _tier_pdf_route() -> Tuple[str, Optional[str], int]:
    """
    NHO PDF route: discover links (static/scrapling/playwright), download the
    newest-looking in-force PDF, extract text with pypdf.
    Returns (text, pdf_path, warning_count). Raises on failure.
    """
    links, method = discover_pdf_links()
    logger.info(f"Found {len(links)} NAVAREA PDF link(s) via {method}.")
    if not links:
        raise RuntimeError("No NAVAREA PDF links found on the rendered page.")
    # Prefer 'Inforce' bulletins (the weekly in-force list), else newest DOM link.
    inforce = [l for l in links if "inforce" in l.lower()]
    pdf_url = inforce[0] if inforce else links[0]
    pdf_path = download_pdf(pdf_url, OUTPUT_DIR)
    text = extract_pdf_text(pdf_path)
    n = validate_bulletin_text(text, "pdf-route")
    return text, pdf_path, n


def _tier_nho_page_text() -> Tuple[str, Optional[str], int]:
    """Rendered NHO public page text parsed directly (no PDF round-trip)."""
    text = _scrapling_fetch_text(NAVAREA_PAGE_URL)
    if not text:
        raise RuntimeError("StealthyFetcher returned no page text.")
    text = clean_html_text(text)
    n = validate_bulletin_text(text, "nho-page-text")
    return text, None, n


def _tier_mirror() -> Tuple[str, Optional[str], int]:
    """SeaLagom mirror — anonymous, no auth, fresh community copy (proven)."""
    resp = requests.get(MIRROR_URL, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    text = clean_html_text(resp.text)
    n = validate_bulletin_text(text, "sealagom-mirror")
    return text, None, n


TIERS = (
    ("pdf-route", _tier_pdf_route),
    ("nho-page-text", _tier_nho_page_text),
    ("sealagom-mirror", _tier_mirror),
)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_navarea_8_scraper(output_dir: str = OUTPUT_DIR, dry_run: bool = False) -> dict:
    """
    Executes the tiered NAVAREA VIII acquisition. Returns a summary dict:
      {bulletin_text, source_tier, warning_count, as_on_date, pdf_path, ...}
    Raises when ALL tiers fail (fail closed, never empty-success).
    """
    global OUTPUT_DIR
    OUTPUT_DIR = output_dir
    if HAS_SHARED:
        setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    logger.info("=" * 60)
    logger.info("NAVAREA VIII (NHO India) tiered bulletin scraper")
    logger.info(f"Source page: {NAVAREA_PAGE_URL} | Mirror: {MIRROR_URL}")

    if not HAS_REQUESTS:
        raise RuntimeError("requests is required. Run: pip install -r requirements.txt")

    summary = {"bulletin_text": None, "source_tier": None, "warning_count": 0,
               "as_on_date": None, "pdf_path": None, "dry_run": dry_run, "tier_errors": {}}

    text = None
    pdf_path = None
    tier_used = None
    n = 0
    errors = []
    for tier_name, fn in TIERS:
        try:
            candidate_text, candidate_pdf, candidate_n = fn()
            text, pdf_path, tier_used, n = candidate_text, candidate_pdf, tier_name, candidate_n
            logger.info(f"Acquisition succeeded via tier '{tier_name}' ({candidate_n} warnings).")
            break
        except Exception as e:
            logger.warning(f"Tier '{tier_name}' failed: {e}")
            errors.append(f"{tier_name}: {e}")
            summary["tier_errors"][tier_name] = str(e)

    if text is None:
        raise RuntimeError("All acquisition tiers failed: " + " | ".join(errors))

    as_on = parse_as_on_date(text)
    check_staleness(as_on)

    summary.update({
        "bulletin_text": text,
        "source_tier": tier_used,
        "warning_count": n,
        "as_on_date": as_on.strftime("%Y-%m-%d") if as_on else None,
        "pdf_path": pdf_path,
    })

    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)
        txt_path = os.path.join(output_dir, "navarea_8_warnings.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        summary["saved_text_path"] = txt_path
        logger.info(f"Bulletin text ({len(text)} chars) written to {txt_path}")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as sf:
                sf.write(f"""### NAVAREA VIII Tiered Scraper Summary
| Metric | Value |
| :--- | :--- |
| **Winning Tier** | {summary['source_tier']} |
| **Warnings Detected** | {summary['warning_count']} |
| **AS ON Date** | {summary['as_on_date'] or 'unknown'} |
| **Audit PDF** | {summary['pdf_path'] or 'not acquired (text tier)'} |
| **Failed Tiers** | {len(summary['tier_errors'])} |
| **Mode** | {'Dry-Run' if dry_run else 'Live'} |
""")
        except Exception:
            pass

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="NAVAREA VIII tiered bulletin scraper")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Directory for outputs")
    parser.add_argument("--dry-run", action="store_true", help="Probe tiers without writing")
    args = parser.parse_args()
    try:
        run_navarea_8_scraper(output_dir=args.output_dir, dry_run=args.dry_run)
        return 0
    except Exception as e:
        logger.error(f"Scraper failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
