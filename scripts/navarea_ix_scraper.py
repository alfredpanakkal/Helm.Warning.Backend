#!/usr/bin/env python3
"""
scripts/navarea_ix_scraper.py — NAVAREA IX (Pakistan / NHO) scraper.

Source: the National Hydrographic Office Pakistan 'NAVAREA IX WARNINGS'
page. The page itself carries only a metadata table (S.NO / REGION /
DTG / WARNING # / DESCRIPTION / ATTACHMENT) — the full text of every
in-force warning sits in a separate plain-text 'View Document' file
published by the site's navarea-warnings plugin (verified live
2026-10-27):

    https://hydrography.paknavy.gov.pk/wp-content/plugins/
      navarea-warnings/custom_uploaded_warnings_for_navarea/
      20261027SEC 412.txt

Each file is ALREADY the exact block format the universal parser
ingests for region 'ix' (DTG line, 'NAVAREA IX nnn/yy' header, region /
area / charts lines, numbered paragraphs — see
tests/fixtures/navarea_ix_sample.txt), so the harvest is a plain
concatenation — no synthesis step.

The upload date in the filename does NOT always match the row DTG
(e.g. 394/26: DTG 211500 UTC OCT 2026 but no '20261021SEC 394.txt'
exists), so the scraper follows each row's own 'View Document' link
instead of guessing URLs.

Strategy (fail-closed, mirrors scripts/navarea_vii_scraper.py):
  1. Fetch the page (Scrapling Fetcher — stealthy headers, retries;
     requests fallback); any error -> non-zero exit, harvest untouched,
     parse and sync NEVER run (never sync a partial snapshot).
  2. Extract one (warning number, href) pair per table row, fetch each
     linked document, and validate it really is the advertised warning.
     The verbatim page HTML is archived alongside for provenance.
  3. Hand the harvest to the SAME universal parser + generic sync the
     manual paste pipeline uses — one contract, scrape or paste.

Run:
    python -m scripts.navarea_ix_scraper
    python -m scripts.run_navarea_ix
"""
import html as _html
import os
import re
import sys
import time
from typing import Callable, List, Optional, Tuple

# Scrapling Fetcher: stealthy HTTP client with retries/impersonation
# (https://github.com/D4Vinci/Scrapling) — same idiom as scrapers/navarea_ii.py.
try:
    from scrapling.fetchers import Fetcher
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NAVAREA_IX_URL = "https://hydrography.paknavy.gov.pk/navarea-ix-warnings/"
REGION_KEY = "ix"
HARVEST_DIR = os.path.join("navareas", REGION_KEY)
RAW_HTML_PATH = os.path.join(HARVEST_DIR, "latest_raw.html")
RAW_TXT_PATH = os.path.join(HARVEST_DIR, "latest_raw.txt")
PARSED_PATH = os.path.join(HARVEST_DIR, "parsed.json")

_TIMEOUT_S = 45
_MIN_WARNINGS = 1  # a live-but-empty feed fails loudly; never sync 0.
_DOC_PAUSE_S = 0.2  # politeness pause between document fetches

_BROWSER_HEADERS = {
    "accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "referer": "https://hydrography.paknavy.gov.pk/",
    "accept-language": "en;q=0.9",
}

# Table structure (verified live 2026-10-27): one <tr> per in-force
# warning, cells: S.NO / REGION-AREA / DTG / WARNING # / DESCRIPTION /
# ATTACHMENT ('View Document' anchor). The WARNING # cell is the only
# bare 'nnn/yy' token; the ATTACHMENT cell carries the document link.
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_WARNING_NUM_RE = re.compile(r"^\s*(\d{1,4})\s*/\s*(\d{2,4})\s*$")

# Every harvested document must open with its own 'NAVAREA IX nnn/yy'
# header (verified in every live file sampled: 412/26, 410/26, 409/26,
# 347/26, 463/25) — this is what the universal parser anchors on.
_HEADER_FOR_RE = re.compile(r"NAV\s*AREA\s+IX\b", re.IGNORECASE)


def _strip_tags(fragment: str) -> str:
    """HTML fragment -> visible text (tags to spaces, entities decoded)."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_url(url: str, accept: str) -> Optional[str]:
    """Fetches a URL as text.

    Scrapling's stealthy Fetcher when available, plain requests
    otherwise. Returns the body text, or None (fail-closed; printed).
    """
    _headers = dict(_BROWSER_HEADERS)
    _headers["accept"] = accept
    body_text = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(url, headers=_headers, timeout=_TIMEOUT_S,
                               retries=3, stealthy_headers=True)
            status = getattr(page, "status", None)
            body = page.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            body_text = str(body or "")
            if status != 200:
                snippet = body_text[:200].replace("\n", " ")
                print(f"WARNING: {url} returned HTTP {status}: {snippet}")
                return None
        except Exception as e:
            print(f"WARNING: Scrapling fetch failed for {url} ({e}); "
                  f"falling back to requests...")
            body_text = ""

    if not body_text:
        if not HAS_REQUESTS:
            print("ERROR: no HTTP client available "
                  "(install scrapling or requests).")
            return None
        try:
            resp = requests.get(url, headers=_headers, timeout=_TIMEOUT_S)
        except Exception as e:
            print(f"ERROR: fetch failed for {url} ({e}); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"ERROR: {url} returned HTTP {resp.status_code}: {snippet}")
            return None
        body_text = resp.text or ""

    return body_text


def extract_rows(page_html: str) -> List[Tuple[str, str, str]]:
    """Extracts (number, year, href) per in-force warning row.

    Follows each row's own ATTACHMENT link (the upload date inside the
    document filename does NOT reliably follow the row DTG — verified
    2026-10-27 — so URLs are never guessed). Rows that advertise a
    warning number but carry no usable document link are skipped loudly
    (never silently); the header row is ignored.
    """
    rows: List[Tuple[str, str, str]] = []
    for row_html in _ROW_RE.findall(page_html):
        cells = _CELL_RE.findall(row_html)
        if len(cells) < 4:
            continue  # header / layout row
        warning_cell = _strip_tags(cells[3])
        m = _WARNING_NUM_RE.match(warning_cell)
        if not m:
            if "View Document" in _strip_tags(row_html):
                print(f"WARNING: table row has a document link but no "
                      f"parseable WARNING # cell: {warning_cell!r}")
            continue
        number, year = m.group(1), m.group(2)
        href = None
        for cell_html in cells:
            if "View Document" in _strip_tags(cell_html) or "href" in cell_html.lower():
                hm = _HREF_RE.search(cell_html)
                if hm:
                    href = hm.group(1)
                    break
        if not href or not href.lower().startswith("http"):
            print(f"WARNING: no document link for warning {number}/{year} "
                  f"— skipping row loudly (page layout change?)")
            continue
        rows.append((number, year, href))
    return rows


def assemble_bulletin(rows: List[Tuple[str, str, str]],
                      fetch_doc: Callable[[str], Optional[str]]) -> Optional[str]:
    """Fetches every linked document and concatenates the blocks.

    Fail-closed: any fetch failure or document that does not carry the
    advertised warning's own 'NAVAREA IX nnn/yy' header makes the whole
    harvest fail (never sync a partial snapshot).
    """
    blocks: List[str] = []
    for number, year, href in rows:
        doc = fetch_doc(href)
        if doc is None or not doc.strip():
            print(f"ERROR: no content for warning {number}/{year} from {href}; "
                  f"harvest untouched.")
            return None
        doc = doc.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in doc.split("\n")]
        block = "\n".join(lines).strip()

        yy = year[-2:]
        expected = re.compile(
            r"NAV\s*AREA\s+IX\s+" + re.escape(number) +
            r"\s*/\s*" + re.escape(yy) + r"(?!\d)", re.IGNORECASE)
        if not expected.search(block):
            print(f"ERROR: document for {number}/{year} does not carry its own "
                  f"'NAVAREA IX {number}/{yy}' header; refusing it "
                  f"(wrong link? {href})")
            return None
        blocks.append(block)
        if _DOC_PAUSE_S:
            time.sleep(_DOC_PAUSE_S)
    return "\n\n".join(blocks) + "\n"


def main() -> bool:
    print("=" * 60)
    print("NAVAREA IX (Pakistan / NHO) Scraper")
    print(f"Endpoint: {NAVAREA_IX_URL}")
    print(f"HTTP Fetcher: {'Scrapling' if HAS_SCRAPLING else 'requests' if HAS_REQUESTS else 'none'}")
    print("=" * 60)

    page_html = fetch_url(NAVAREA_IX_URL, "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    if page_html is None or not page_html.strip():
        return False
    if "View Document" not in page_html:
        # An HTML error page would otherwise be archived as the harvest.
        print(f"ERROR: page does not look like the NAVAREA IX table: "
              f"{_strip_tags(page_html)[:200]}")
        return False

    rows = extract_rows(page_html)
    if len(rows) < _MIN_WARNINGS:
        print(f"ERROR: extracted {len(rows)} warning row(s); refusing to "
              f"sync an empty snapshot (page layout change?)")
        return False

    bulletin = assemble_bulletin(
        rows, lambda href: fetch_url(href, "text/plain;q=0.9,*/*;q=0.8"))
    if bulletin is None:
        return False

    n_blocks = len(_HEADER_FOR_RE.findall(bulletin))
    if n_blocks < len(rows):
        # Should be impossible post-validation; belt and braces.
        print(f"ERROR: {len(rows)} row(s) but {n_blocks} block header(s); "
              f"refusing to sync a partial snapshot.")
        return False

    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(page_html)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin)
    print(f"Harvested {len(rows)} in-force warning(s) -> {RAW_TXT_PATH}")
    print(f"Verbatim page HTML archived -> {RAW_HTML_PATH}")

    from scripts.navarea_universal_parser import main as parse_main
    if not parse_main(RAW_TXT_PATH, PARSED_PATH):
        return False

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
