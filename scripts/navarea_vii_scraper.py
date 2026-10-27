#!/usr/bin/env python3
"""
scripts/navarea_vii_scraper.py — NAVAREA VII (South Africa / SANHO) scraper.

Source: the South African Navy Hydrographic Office 'NAVAREA VII Messages'
page. Unlike the IHM portal (NAVAREA III), SANHO publishes the in-force
messages as plain text inside a static HTML page — already exactly the
format the universal parser ingests for region 'vii' (the corpus fixture
tests/fixtures/navarea_vii_sample.txt was extracted from this same page).

    https://www.sanho.co.za/notices_mariners/navarea_v11_messages.htm?b2=NAVAREA+VII

Strategy (fail-closed, mirrors scripts/navarea_iii_scraper.py):
  1. Fetch the page (Scrapling Fetcher — stealthy headers, retries;
     requests fallback); any error -> non-zero exit, harvest untouched,
     parse and sync NEVER run (never sync a partial snapshot).
  2. Strip the HTML to text (stdlib HTMLParser), slice the page to the
     messages region using the page's own anchors ('Nil Prior to these
     Messages' .. 'copyright'), and normalize non-breaking spaces.
     The extracted text IS the bulletin — no synthesis step needed.
     The verbatim HTML is archived alongside for provenance.
  3. Hand the harvest to the SAME universal parser + generic sync the
     manual paste pipeline uses — one contract, scrape or paste.

Run:
    python -m scripts.navarea_vii_scraper
    python -m scripts.run_navarea_vii
"""
import os
import re
import sys
from html.parser import HTMLParser
from typing import List, Optional

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

NAVAREA_VII_URL = (
    "https://www.sanho.co.za/notices_mariners/"
    "navarea_v11_messages.htm?b2=NAVAREA+VII"
)
REGION_KEY = "vii"
HARVEST_DIR = os.path.join("navareas", REGION_KEY)
RAW_HTML_PATH = os.path.join(HARVEST_DIR, "latest_raw.html")
RAW_TXT_PATH = os.path.join(HARVEST_DIR, "latest_raw.txt")
PARSED_PATH = os.path.join(HARVEST_DIR, "parsed.json")

_TIMEOUT_S = 45
_MIN_WARNINGS = 1  # a live-but-empty feed fails loudly; never sync 0.

_BROWSER_HEADERS = {
    "accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "referer": "https://www.sanho.co.za/notices_mariners/navarea_v11_messages.htm",
    "accept-language": "en;q=0.9",
}

# Page anchors bounding the in-force message region (verified live
# 2026-10-27). Fallback: if a marker is missing, keep the full text but
# still require at least one NAVAREA VII header below.
_START_MARKER = "Nil Prior to these Messages"
_END_MARKERS = ("© copyright", "copyright SAN")

# At least one real 'NAVAREA VII nnn OF yyyy' block must survive slicing.
_HEADER_RE = re.compile(
    r"NAV\s*AREA\s+VII\b\s*\d{1,4}\s+OF\s*(\d{4}|\d{2})(?!\d)", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    """Minimal HTML -> text extractor (stdlib only, no new dependency).

    Skips script/style blocks, breaks on block-level tags and <br>.
    Entities (incl. &nbsp;) are converted by HTMLParser itself.
    """
    _BREAK_TAGS = {"br", "p", "div", "li", "tr", "table", "ul", "ol",
                   "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in self._BREAK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def extract_message_text(html: str) -> str:
    """Strips the SANHO page to the in-force NAVAREA VII message text.

    Steps: HTML -> text, slice between the page's own anchors, normalize
    non-breaking spaces (they would defeat the coordinate parser), strip
    trailing whitespace per line. Raises ValueError when no NAVAREA VII
    header survives (fail-closed: never archive junk as the harvest).
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = extractor.get_text()

    start = text.find(_START_MARKER)
    if start != -1:
        text = text[start + len(_START_MARKER):]
    end = -1
    for marker in _END_MARKERS:
        end = text.find(marker)
        if end != -1:
            break
    if end != -1:
        text = text[:end]

    # Normalize non-breaking spaces and CRs, trim lines.
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    if not _HEADER_RE.search(text):
        raise ValueError(
            "no 'NAVAREA VII nnn OF yyyy' header found in the page slice; "
            "refusing to archive a junk harvest (page layout change?)")
    return text.strip() + "\n"


def fetch_page_html() -> Optional[str]:
    """Fetches the SANHO NAVAREA VII messages page HTML.
    Scrapling's stealthy Fetcher when available, plain requests otherwise.
    Returns the HTML, or None (fail-closed; the error is printed)."""
    html = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                NAVAREA_VII_URL,
                headers=_BROWSER_HEADERS,
                timeout=_TIMEOUT_S,
                retries=3,
                stealthy_headers=True,
            )
            status = getattr(page, "status", None)
            body = page.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            html = str(body or "")
            if status != 200:
                snippet = html[:200].replace("\n", " ")
                print(f"WARNING: SANHO page returned HTTP {status}: {snippet}")
                return None
        except Exception as e:
            print(f"WARNING: Scrapling fetch failed ({e}); falling back to requests...")
            html = ""

    if not html:
        if not HAS_REQUESTS:
            print("ERROR: no HTTP client available "
                  "(install scrapling or requests).")
            return None
        try:
            resp = requests.get(NAVAREA_VII_URL,
                                headers=_BROWSER_HEADERS, timeout=_TIMEOUT_S)
        except Exception as e:
            print(f"ERROR: fetch failed for NAVAREA VII page ({e}); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"ERROR: SANHO page returned HTTP {resp.status_code}: {snippet}")
            return None
        html = resp.text or ""

    return html


def main() -> bool:
    print("=" * 60)
    print("NAVAREA VII (South Africa / SANHO) Scraper")
    print(f"Endpoint: {NAVAREA_VII_URL}")
    print(f"HTTP Fetcher: {'Scrapling' if HAS_SCRAPLING else 'requests' if HAS_REQUESTS else 'none'}")
    print("=" * 60)

    html = fetch_page_html()
    if html is None or not html.strip():
        return False

    try:
        bulletin = extract_message_text(html)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return False

    n_blocks = len(_HEADER_RE.findall(bulletin))
    if n_blocks < _MIN_WARNINGS:
        print(f"ERROR: page carried {n_blocks} NAVAREA VII block(s); "
              f"refusing to sync an empty snapshot.")
        return False

    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin)
    print(f"Harvested {n_blocks} in-force message block(s) -> {RAW_TXT_PATH}")
    print(f"Verbatim HTML archived -> {RAW_HTML_PATH}")

    from scripts.navarea_universal_parser import main as parse_main
    if not parse_main(RAW_TXT_PATH, PARSED_PATH):
        return False

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
