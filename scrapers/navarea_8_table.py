#!/usr/bin/env python3
"""
scrapers/navarea_8_table.py — NAVAREA VIII (NHO India) Table Scraper

Source: https://hydrobharat.gov.in/navarea-warnings
The NHO portal renders an already-parsed table of NAVAREA VIII warnings
in force (columns: Sr No., Identifier, Types, Feature, Message, Place,
Action). The table is paginated ~10 rows per page with a 'Next' button;
the footer shows 'Showing 1 to 10 of N entries'.

Strategy:
  1. Render the page headlessly with Playwright (the portal is a
     Liferay/React app; the table is fully JS-rendered).
  2. Scrape every row of the CURRENT page.
  3. While a 'Next' pagination control is enabled: click it, wait for the
     table to advance, and scrape the next page — until the complete set
     of in-force warnings is collected (footer 'Showing x to y of N
     entries' where y == N, or Next becomes disabled).
  4. De-duplicate rows (the portal sometimes repeats a warning, e.g.
     the same Identifier appearing twice with identical text).
  5. Emit:
       - navareas/navarea_8/navarea_8_table.json  (structured rows)
       - navareas/navarea_8/navarea_8_warnings.txt (synthesized bulletin
         text in the standard 'NAVAREA VIII n/yy' header format, so the
         existing deterministic parser works unchanged)

Run:
    python scrapers/navarea_8_table.py
    python scrapers/navarea_8_table.py --dry-run   # scrape pages, write nothing
"""

import os
import re
import sys
import json
import argparse
from datetime import datetime, timezone

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

logger = get_logger("scraper.navarea_8_table")

NAVAREA_PAGE_URL = "https://hydrobharat.gov.in/navarea-warnings"
OUTPUT_DIR = os.environ.get("NAVAREA_8_OUTPUT_DIR", os.path.join("navareas", "navarea_8"))

PAGE_LOAD_TIMEOUT_S = 60
NEXT_CLICK_TIMEOUT_S = 20
MAX_PAGES = 200  # hard safety cap against a broken 'Next' control

BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "accept-language": "en-IN,en;q=0.9",
}

# 'Showing 1 to 10 of 55 entries' — DataTables-style footer.
RE_SHOWING = re.compile(
    r"Showing\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+entries?", re.IGNORECASE)
# Year heuristic: 2-digit year in a DTG-like token ('OCT 26', 'NOV 26').
RE_YEAR = re.compile(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{2})\b",
                     re.IGNORECASE)


# ---------------------------------------------------------------------------
# In-browser extraction helpers (executed inside the page context)
# ---------------------------------------------------------------------------

JS_EXTRACT_ROWS = """
() => {
  const table = Array.from(document.querySelectorAll('table')).find(t => {
    const txt = (t.innerText || '').toUpperCase();
    return txt.includes('IDENTIFIER') && txt.includes('MESSAGE');
  });
  if (!table) return null;

  // Column map from the header row (Sr No., Identifier, Types, Feature, Message, Place, ...)
  const ths = Array.from(table.querySelectorAll('thead th, thead td'));
  const headers = ths.map(th => (th.innerText || '').trim().toLowerCase());

  const rows = [];
  for (const tr of table.querySelectorAll('tbody tr')) {
    const cells = Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim());
    if (!cells.length || cells.every(c => !c)) continue;
    const row = {};
    cells.forEach((val, i) => {
      const key = i < headers.length && headers[i] ? headers[i] : ('col_' + i);
      row[key] = val;
    });
    rows.push(row);
  }
  return { headers, rows };
}
"""

JS_PAGINATION_STATE = """
() => {
  // Footer info: 'Showing 1 to 10 of 55 entries'
  let showing = null;
  for (const el of document.querySelectorAll('div, span, p')) {
    const m = (el.innerText || '').match(/Showing\s+(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+entries?/i);
    if (m) { showing = [Number(m[1]), Number(m[2]), Number(m[3])]; break; }
  }
  // Find the 'Next' control among pagination buttons/links.
  let nextSel = null;
  for (const el of document.querySelectorAll('a, button, li')) {
    const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim().toLowerCase();
    const cls = (el.className || '').toString().toLowerCase();
    if (label === 'next' || label.startsWith('next') ||
        (cls.includes('paginate_button') && cls.includes('next'))) {
      const disabled =
        el.disabled === true ||
        cls.includes('disabled') ||
        (el.parentElement && ((el.parentElement.className || '').toString().toLowerCase().includes('disabled'))) ||
        el.getAttribute('aria-disabled') === 'true';
      nextSel = { found: true, disabled, tag: el.tagName.toLowerCase() };
      break;
    }
  }
  return { showing, next: nextSel };
}
"""

JS_CLICK_NEXT = """
() => {
  const candidates = Array.from(document.querySelectorAll('a, button, li'));
  for (const el of candidates) {
    const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).trim().toLowerCase();
    const cls = (el.className || '').toString().toLowerCase();
    if (label === 'next' || label.startsWith('next') ||
        (cls.includes('paginate_button') && cls.includes('next'))) {
      const target = el.tagName.toLowerCase() === 'li' ? (el.querySelector('a') || el) : el;
      const disabled =
        target.disabled === true ||
        (target.className || '').toString().toLowerCase().includes('disabled') ||
        (target.parentElement && ((target.parentElement.className || '').toString().toLowerCase().includes('disabled'))) ||
        target.getAttribute('aria-disabled') === 'true';
      if (!disabled) { target.click(); return true; }
    }
  }
  return false;
}
"""


def _wait_for_table(page):
    page.wait_for_selector("table", timeout=PAGE_LOAD_TIMEOUT_S * 1000)
    page.wait_for_function(
        "!!Array.from(document.querySelectorAll('table')).find(t => {"
        " const x = (t.innerText||'').toUpperCase();"
        " return x.includes('IDENTIFIER') && x.includes('MESSAGE') && t.querySelector('tbody tr');"
        "})",
        timeout=PAGE_LOAD_TIMEOUT_S * 1000,
    )


def _wait_for_page_advance(page, prev_start):
    """Waits until the 'Showing x to ...' offset moves past prev_start."""
    deadline = datetime.now().timestamp() + NEXT_CLICK_TIMEOUT_S
    while datetime.now().timestamp() < deadline:
        state = page.evaluate(JS_PAGINATION_STATE)
        showing = (state or {}).get("showing")
        if showing and showing[0] > prev_start:
            return True
        page.wait_for_timeout(250)
    return False


# ---------------------------------------------------------------------------
# Pagination loop
# ---------------------------------------------------------------------------

def _table_warning_id(entry):
    """Canonical id for one normalized table row ('NAVAREA VIII 123/26')."""
    return f"NAVAREA VIII {entry['warning_number']}/{entry['year']}"


def scrape_all_pages(page, known_ids=None):
    """
    Scrapes every page of the NAVAREA VIII table, pressing 'Next' after each
    page until the complete set is collected. Returns
    (rows, pages, total, stop_reason) where stop_reason is:
      'completed'  — footer count reached / Next disabled / single page
      'all_known'  — steady-state skip: page 1 carries only warnings
                      already stored in the DB (the table is newest-first,
                      so nothing newer exists further in); pagination stops
                      after page 1 and nothing is re-scraped
      'early_stop' — pagination broke mid-sweep (WAF block, dead 'Next',
                      timeout); the rows collected so far are SALVAGED and
                      returned instead of being discarded
    """
    all_rows = []
    seen_keys = set()
    total_expected = None
    pages = 0

    while True:
        pages += 1
        if pages > MAX_PAGES:
            if all_rows:
                logger.warning(
                    f"Exceeded MAX_PAGES ({MAX_PAGES}); salvaging "
                    f"{len(all_rows)} row(s) collected so far.")
                return all_rows, pages, total_expected, "early_stop"
            raise RuntimeError(
                f"Exceeded MAX_PAGES ({MAX_PAGES}); pagination appears broken.")

        extracted = page.evaluate(JS_EXTRACT_ROWS)
        if not extracted:
            raise RuntimeError("NAVAREA VIII table not found in rendered page.")

        new_rows = 0
        for row in extracted["rows"]:
            key = json.dumps(row, sort_keys=True, ensure_ascii=False)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_rows.append(row)
            new_rows += 1

        state = page.evaluate(JS_PAGINATION_STATE)
        showing = (state or {}).get("showing")
        nxt = (state or {}).get("next") or {}

        # Stored-row skipping (steady state): when every warning on page 1
        # is already in the database, newer warnings (if any) would be on
        # page 1 — the table lists warnings newest-first. Stop here instead
        # of re-scraping every page.
        if pages == 1 and known_ids:
            page_ids = {_table_warning_id(w)
                        for w in normalize_rows(extracted["rows"])}
            if page_ids and page_ids.issubset(known_ids):
                logger.info(
                    "Page 1 carries only already-stored warning(s) "
                    f"({len(page_ids)}); steady-state skip — not paginating "
                    "further.")
                return all_rows, pages, total_expected, "all_known"

        if showing:
            start, upto, total = showing
            total_expected = total
            logger.info(
                f"Page {pages}: showing {start}-{upto} of {total} entries "
                f"({new_rows} new row(s)).")
            if upto >= total:
                logger.info("Complete set reached via footer count; done.")
                break
        else:
            logger.info(f"Page {pages}: {new_rows} new row(s); no footer count found.")

        # If the portal shows <=10 rows with no Next control, we already have
        # the complete set.
        if not nxt.get("found"):
            logger.info("No 'Next' control present; single-page table, done.")
            break
        if nxt.get("disabled"):
            logger.info("'Next' is disabled; last page reached, done.")
            break

        prev_start = showing[0] if showing else len(all_rows)
        if not page.evaluate(JS_CLICK_NEXT):
            if all_rows:
                logger.warning(
                    "No enabled 'Next' control mid-sweep; salvaging "
                    f"{len(all_rows)} row(s) collected so far.")
                return all_rows, pages, total_expected, "early_stop"
            raise RuntimeError("Could not find an enabled 'Next' control to click.")
        if not _wait_for_page_advance(page, prev_start):
            if all_rows:
                logger.warning(
                    f"Table did not advance after clicking 'Next' (start "
                    f"offset stayed at {prev_start}); salvaging "
                    f"{len(all_rows)} row(s) collected so far.")
                return all_rows, pages, total_expected, "early_stop"
            raise RuntimeError(
                f"Table did not advance after clicking 'Next' (start offset "
                f"stayed at {prev_start}); pagination may be broken.")

    if total_expected is not None and len(all_rows) < total_expected:
        logger.warning(
            f"Collected {len(all_rows)} unique row(s) but footer reports "
            f"{total_expected} entries (duplicates on the portal explain a "
            f"small shortfall).")

    return all_rows, pages, total_expected, "completed"


# ---------------------------------------------------------------------------
# Row normalization
# ---------------------------------------------------------------------------

def _pick(row, *names):
    for n in names:
        for k, v in row.items():
            if k == n or k.startswith(n):
                if v and str(v).strip():
                    return str(v).strip()
    return ""


def _derive_year(message: str) -> str:
    """Derives the 2-digit warning year from DTG tokens in the message."""
    matches = RE_YEAR.findall(message or "")
    if matches:
        # Prefer the last month-year token (usually the CANCEL DTG year).
        return matches[-1][1]
    return f"{datetime.now(timezone.utc).year % 100:02d}"


def normalize_rows(rows):
    """Maps raw table rows to normalized warning dicts."""
    warnings = []
    seen = set()
    for row in rows:
        identifier = _pick(row, "identifier", "warning")
        message = _pick(row, "message")
        if not identifier or not message:
            continue
        entry = {
            "warning_number": identifier,
            "year": _derive_year(message),
            "hazard_type": _pick(row, "type"),
            "feature_geometry": _pick(row, "feature"),
            "place": _pick(row, "place"),
            "message": message,
        }
        key = (identifier, entry["year"], message)
        if key in seen:
            continue  # portal repeats the same warning under two rows
        seen.add(key)
        warnings.append(entry)
    return warnings


def synthesize_bulletin_text(warnings):
    """
    Renders the table rows as the standard bulletin text the deterministic
    parser expects: 'NAVAREA VIII n/yy <place> (.) <message>'.
    """
    lines = ["NAVAREA VIII - WARNINGS IN FORCE AS ON "
             + datetime.now(timezone.utc).strftime("%d %b %Y").upper()]
    for w in warnings:
        place = w["place"] or ""
        lines.append(
            f"NAVAREA VIII {w['warning_number']}/{w['year']} {place} (.) {w['message']}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_navarea_8_table_scraper(output_dir: str = OUTPUT_DIR,
                               dry_run: bool = False,
                               raw_txt: str = None,
                               known_ids=None) -> dict:
    if not HAS_PLAYWRIGHT:
        raise RuntimeError(
            "playwright is required for this JS-rendered table. Install with: "
            "pip install playwright && playwright install chromium")
    if HAS_SHARED:
        setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    logger.info("=" * 60)
    logger.info("NAVAREA VIII (NHO India) Table Scraper")
    logger.info(f"Source page: {NAVAREA_PAGE_URL}")

    summary = {"warnings": 0, "pages": 0, "total_entries": None,
               "skipped": [], "dry_run": dry_run, "stop_reason": "completed"}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=BROWSER_HEADERS["user-agent"],
                                     locale="en-IN")
            page.goto(NAVAREA_PAGE_URL, wait_until="domcontentloaded",
                      timeout=PAGE_LOAD_TIMEOUT_S * 1000)
            logger.info("Waiting for the warnings table to render...")
            _wait_for_table(page)

            rows, pages, total, stop_reason = scrape_all_pages(
                page, known_ids=known_ids)
            summary["pages"] = pages
            summary["total_entries"] = total
            summary["stop_reason"] = stop_reason
            logger.info(f"Scraped {pages} page(s); {len(rows)} unique row(s) "
                        f"total (stop_reason={stop_reason}).")
        finally:
            browser.close()

    warnings = normalize_rows(rows)
    summary["warnings"] = len(warnings)
    if not warnings:
        raise RuntimeError("No warnings extracted from the NHO table.")

    if dry_run:
        logger.info("[DRY-RUN] Not writing outputs.")
        return summary

    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "navarea_8_table.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"source": NAVAREA_PAGE_URL,
                   "scraped_at": datetime.now(timezone.utc).isoformat(),
                   "total_entries_reported": total,
                   "warnings": warnings}, f, indent=2, ensure_ascii=False)
    logger.info(f"Structured rows written to {json_path}")

    text = synthesize_bulletin_text(warnings)
    txt_path = raw_txt or os.path.join(output_dir, "navarea_8_warnings.txt")
    if not os.path.isabs(txt_path):
        txt_path = os.path.join(os.getcwd(), txt_path)
    os.makedirs(os.path.dirname(txt_path) or ".", exist_ok=True)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"Synthesized bulletin text ({len(text)} chars) -> {txt_path}")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as sf:
                sf.write(f"""### NAVAREA VIII Table Scraper Summary
| Metric | Value |
| :--- | :--- |
| **Pages Scraped (Next presses + first page)** | {summary['pages']} |
| **Entries Reported by Portal** | {summary['total_entries'] or 'unknown'} |
| **Unique Warnings Collected** | {summary['warnings']} |
| **Execution Mode** | {'Dry-Run' if dry_run else 'Live'} |
""")
        except Exception:
            pass

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NAVAREA VIII (NHO India) table scraper with pagination")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        run_navarea_8_table_scraper(output_dir=args.output_dir, dry_run=args.dry_run)
        return 0
    except Exception as e:
        logger.error(f"Table scraper failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
