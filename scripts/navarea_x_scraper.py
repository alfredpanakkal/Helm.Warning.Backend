#!/usr/bin/env python3
"""
scripts/navarea_x_scraper.py — NAVAREA X (Australia / AMSA RCC) scraper.

Source: AMSA's public 'Maritime safety information database' page
(www.amsa.gov.au/safety-navigation/navigation-systems/maritime-safety-
information-database) is a search UI over RCC Australia's MSI
publication system, whose plain publication page needs NO browser
(verified 2026-10-27):

    https://www.operations.amsa.gov.au/AMSA.Web.MSIPublication/Home

The publication carries the full Australian MSI in five parts; 'Part 2.
NAVAREA X warnings' holds the COMPLETE texts of all in-force NAVAREA X
warnings as SECURITE ... NNNN radio blocks — already the format the
universal parser ingests for region 'x' (see
tests/fixtures/navarea_x_sample.txt). 'Part 3. Coastal warnings'
(AUSCOAST areas A-H) are Australian national warnings outside NAVAREA
numbering — sliced out loudly, the same way the NAVAREA V scraper skips
the Brazilian costeiro/SAR records.

Strategy (fail-closed, mirrors scripts/navarea_vii_scraper.py):
  1. Fetch the page (Scrapling Fetcher — stealthy headers, retries;
     requests fallback); any error -> non-zero exit, harvest untouched,
     parse and sync NEVER run (never sync a partial snapshot).
  2. Strip the HTML to text (stdlib HTMLParser), slice Part 2 between
     the page's own anchors ('Part 2. NAVAREA X warnings:' ..
     'Part 3. Coastal warnings:' — BOTH anchors are required, because a
     missing end anchor would let the AUSCOAST blocks leak into the
     regional harvest), then split the slice on the 'NNNN' broadcast
     terminator and keep, per message, the text from its
     'NAVAREA X nnn/yy' header up to (excluding) the terminator.
     The dropped 'SECURITE' / 'FM JRCC AUSTRALIA ...' preamble is
     discarded by the universal parser anyway (blocks start at the
     header match); removing it here ALSO prevents the next message's
     preamble from leaking into the previous block's raw_text tail.
     The verbatim HTML is archived alongside for provenance.
  3. Hand the harvest to the SAME universal parser + generic sync the
     manual paste pipeline uses — one contract, scrape or paste.

Run:
    python -m scripts.navarea_x_scraper
    python -m scripts.run_navarea_x
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

NAVAREA_X_URL = "https://www.operations.amsa.gov.au/AMSA.Web.MSIPublication/Home"
REGION_KEY = "x"
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
    "referer": (
        "https://www.amsa.gov.au/safety-navigation/navigation-systems/"
        "maritime-safety-information-database"
    ),
    "accept-language": "en;q=0.9",
}

# Page anchors bounding the in-force NAVAREA X message region (verified
# live 2026-10-27). BOTH are required: without the end anchor the
# AUSCOAST coastal warnings (Part 3) would be absorbed into the harvest.
# The start pattern consumes its whole line so the ':' heading remnant
# never seeds a junk segment.
_START_RE = re.compile(r"Part\s*2\.\s*NAVAREA\s+X\s+warnings[^\n]*", re.IGNORECASE)
_END_RE = re.compile(r"Part\s*3\.\s*Coastal\s+warnings", re.IGNORECASE)

# In-force warning header inside a Part 2 message (the universal
# parser's region 'x' default header shape; the parser applies its own
# CANCEL-prefix exclusion downstream).
_HEADER_RE = re.compile(
    r"NAV\s*AREA\s+X\b\s*(?:WARNING\s+|MSG\s+)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE)

# Broadcast terminator line: Australia closes every message with 'NNNN'
# (the parser strips it from the LAST block via RE_BROADCAST_TAIL; here
# it delimits EVERY block). A run of 3-6 N's mirrors RE_BROADCAST_TAIL
# so a trailing hemisphere letter is never mistaken for a terminator.
_NNNN_LINE_RE = re.compile(r"^[ \t]*N{3,6}[ \t.=]*$", re.MULTILINE)


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
    """Strips the AMSA publication page to the in-force NAVAREA X text.

    Steps: HTML -> text, slice strictly between the 'Part 2. NAVAREA X
    warnings' and 'Part 3. Coastal warnings' anchors, split on the NNNN
    broadcast terminator, keep each block from its 'NAVAREA X nnn/yy'
    header (dropping the SECURITE/FM preamble the parser discards
    anyway), normalize non-breaking spaces and CRs, trim lines. Raises
    ValueError when an anchor is missing or no NAVAREA X header survives
    (fail-closed: never archive junk as the harvest).
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = extractor.get_text()
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")

    start_m = _START_RE.search(text)
    if not start_m:
        raise ValueError(
            "start anchor 'Part 2. NAVAREA X warnings:' not found in the "
            "page; refusing to archive a junk harvest (page layout change?)")
    end_m = _END_RE.search(text, start_m.end())
    if not end_m:
        raise ValueError(
            "end anchor 'Part 3. Coastal warnings:' not found after the "
            "Part 2 anchor; refusing to slice an unbounded harvest "
            "(AUSCOAST leak guard — page layout change?)")
    part2 = text[start_m.end():end_m.start()]

    # Split into radio messages on the NNNN terminator line. A missing
    # terminator between two messages is tolerated: the segment then
    # carries two headers and the universal parser still splits it on
    # the region header. Segments without a NAVAREA X header are skipped
    # loudly (page junk, layout change).
    segments = []
    prev_end = 0
    for term in _NNNN_LINE_RE.finditer(part2):
        segments.append((prev_end, term.start()))
        prev_end = term.end()
    if part2[prev_end:].strip():
        segments.append((prev_end, len(part2)))  # unterminated last message

    blocks = []
    for seg_start, seg_end in segments:
        segment = part2[seg_start:seg_end]
        header = _HEADER_RE.search(segment)
        if header is None:
            if segment.strip():
                print("WARNING: skipping non-NAVAREA-X segment in Part 2 "
                      "(no 'NAVAREA X nnn/yy' header): "
                      + repr(segment.strip()[:80]))
            continue
        block = segment[header.start():seg_end]
        lines = [line.rstrip() for line in block.split("\n")]
        blocks.append("\n".join(lines).strip())

    if not blocks:
        raise ValueError(
            "no 'NAVAREA X nnn/yy' warning found between the Part 2 and "
            "Part 3 anchors; refusing to archive a junk harvest "
            "(page layout change?)")
    return "\n\n".join(blocks) + "\n"


def fetch_page_html() -> Optional[str]:
    """Fetches the AMSA RCC MSI publication page HTML.
    Scrapling's stealthy Fetcher when available, plain requests otherwise.
    Returns the HTML, or None (fail-closed; the error is printed)."""
    html = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                NAVAREA_X_URL,
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
                print(f"WARNING: AMSA publication page returned HTTP {status}: {snippet}")
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
            resp = requests.get(NAVAREA_X_URL,
                                headers=_BROWSER_HEADERS, timeout=_TIMEOUT_S)
        except Exception as e:
            print(f"ERROR: fetch failed for the AMSA publication page ({e}); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"ERROR: AMSA publication page returned HTTP {resp.status_code}: {snippet}")
            return None
        html = resp.text or ""

    return html


def main() -> bool:
    print("=" * 60)
    print("NAVAREA X (Australia / AMSA RCC) Scraper")
    print(f"Endpoint: {NAVAREA_X_URL}")
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
        print(f"ERROR: page carried {n_blocks} NAVAREA X block(s); "
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
