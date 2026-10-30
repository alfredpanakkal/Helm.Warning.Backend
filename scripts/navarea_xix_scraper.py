#!/usr/bin/env python3
"""
scripts/navarea_xix_scraper.py — NAVAREA XIX (Norway / Kystverket) scraper.

Source: the Kystverket 'NAVAREA XIX Warnings' report page — an ASP.NET
page rendering one table row per in-force warning. Each row carries
'Number:' / 'Date:' label cells and a 'Warning:' cell containing the
COMPLETE 'NAVAREA XIX nnn/yy' bulletin block (verified live 2026-10-30):

    https://kyvreports.kystverket.no/NavcoReport/navareaxixvarsler.aspx

Strategy (fail-closed, mirrors scripts/navarea_vii_scraper.py):
  1. Fetch the page (Scrapling Fetcher — stealthy headers, retries;
     plain-requests fallback). Any error -> non-zero exit, harvest
     untouched, parse and sync NEVER run (never sync a partial snapshot).
  2. Parse the table STRUCTURALLY (stdlib HTMLParser): keep ONLY the
     'Warning' cell text of each warning row, cross-checked against the
     row's own 'Number: nnn/yy' label. A label/header mismatch or a
     table with no warning row raises ValueError — the harvest is never
     archived and sync never runs (page layout change protection).
     Row chrome ('Number:'/'Date:' label cells, '|' separators) is
     dropped so it never leaks into a warning's raw_text; the bulletin
     is rebuilt from the clean warning blocks the way the coordinator
     broadcasts them, with line structure preserved so the universal
     parser's numbered-item segmentation works (rig lists, sub-areas).
  3. Hand the harvest to the SAME universal parser + generic sync the
     manual paste pipeline uses — one contract, scrape or paste (a paste
     of this page keeps its 'Number:n/yy' anchors and is handled by the
     region-'xix' extra header pattern; the scraped bulletin needs no
     anchors because every block carries its full header).

AI assistance (per maintainer direction 2026-10-30), same layers as
every universal region — never first, never unaudited:
  * Parsing: the Gemini escalation layer (parse_bulletin_with_fallback
    in shared/gemini_navarea_parser) runs only where the deterministic
    rule parse is inconclusive; results are Tier B / INFERRED.
  * Language: the Kystverket NAVAREA XIX series is published in ENGLISH,
    but individual items occasionally carry Norwegian text. Titles that
    clearly look Norwegian are machine-translated via
    shared/translation.py — fail-closed: on ANY problem the original
    title is kept and the ingest still succeeds.

Run:
    python -m scripts.navarea_xix_scraper
    python -m scripts.run_navarea_xix
"""
import os
import re
import sys
from html.parser import HTMLParser
from typing import List, Optional

# Scrapling Fetcher: stealthy HTTP client with retries/impersonation
# (https://github.com/D4Vinci/Scrapling) — same idiom as the VII/X scrapers.
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

NAVAREA_XIX_URL = (
    "https://kyvreports.kystverket.no/NavcoReport/navareaxixvarsler.aspx"
)
REGION_KEY = "xix"
HARVEST_DIR = os.path.join("navareas", "navarea_xix")
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
    "referer": "https://kyvreports.kystverket.no/NavcoReport/navareaxixvarsler.aspx",
    "accept-language": "en;q=0.9",
}

# The 'NAVAREA XIX nnn/yy' header inside a Warning cell. CANCEL-prefixed
# cross-references are never a row header.
_HEADER_RE = re.compile(
    r"NAV\s*AREA\s+XIX\b\s*(?:WARNING\s+|MSG\s+)?"
    r"(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE)
# The row's own number label ('Number: 132/26' — label and value may sit
# in the SAME cell or in two adjacent cells, verified live 2026-10-30).
_NUMBER_RE = re.compile(
    r"Number:?\s*:?\s*(\d{1,4})\s*/\s*(\d{2})(?!\d)", re.IGNORECASE)


def _norm_year(year: str) -> str:
    y = str(year).strip()
    return y[-2:] if len(y) == 4 else y


class _TableParser(HTMLParser):
    """Collects table rows as lists of raw cell texts (stdlib only).

    <br> inside a cell becomes a newline so the warning block keeps its
    line structure (numbered items, coordinate lists).
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            if self._row is not None:
                self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if not self._skip_depth and self._cell is not None:
            self._cell.append(data)


def _clean_cell(raw: str) -> str:
    """One-line, whitespace-collapsed cell text without '|' chrome."""
    text = raw.replace("\xa0", " ")
    return " ".join(text.split()).strip(" |").strip()


def _clean_warning(raw: str) -> str:
    """Warning-cell text: line structure kept, nbsp normalized, chrome
    ('|' edges, a glued 'Warning:' label) stripped, each line's internal
    whitespace collapsed."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip(" |").strip()
             for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"^\s*Warning:?\s*", "", text, flags=re.IGNORECASE)


def extract_bulletin_text(html: str) -> str:
    """Rebuilds the region-'xix' bulletin from the Kystverket report table.

    One block per warning row, taken verbatim from the row's Warning
    cell (full 'NAVAREA XIX nnn/yy' header included, row chrome dropped).
    The row's own Number label is a cross-check: a contradiction is a
    page layout change and fails closed (ValueError). Duplicate rows
    (same number/year) collapse to the first with a loud warning.
    """
    # 'NBSP;' variants: HTMLParser only converts the lowercase entity.
    html = re.sub(r"&nbsp;", " ", html, flags=re.IGNORECASE)

    parser = _TableParser()
    parser.feed(html)
    parser.close()

    blocks = []
    seen = set()
    for row in parser.rows:
        # Raw cell texts keep the <br>/source line breaks; the CLEANED
        # cells are only for header/label search — _clean_warning must
        # run on the RAW cell or the line structure is lost.
        raw_cells = list(row)
        cleaned = [_clean_cell(c) for c in raw_cells]
        cells = [c for c in cleaned if c]
        if not cells:
            continue
        joined = " ".join(cells)

        header = None
        warning_text = None
        for raw_cell, cell in zip(raw_cells, cleaned):
            if not cell:
                continue
            for m in _HEADER_RE.finditer(cell):
                prefix = cell[max(0, m.start() - 8):m.start()].upper()
                if "CANCEL" in prefix:
                    continue
                header = m
                warning_text = _clean_warning(raw_cell)
                break
            if header is not None:
                break
        if header is None:
            # Fallback: the header may straddle cell boundaries (the
            # joined-row text is the only safe reconstruction then).
            for m in _HEADER_RE.finditer(joined):
                prefix = joined[max(0, m.start() - 8):m.start()].upper()
                if "CANCEL" in prefix:
                    continue
                header = m
                warning_text = _clean_warning(joined)
                break
        if header is None:
            continue  # page title / footer / layout junk row

        number, year = header.group(1), _norm_year(header.group(2))

        # Cross-check against the row's own 'Number: nnn/yy' label.
        label = _NUMBER_RE.search(joined)
        if label is None:
            print("WARNING: warning row NAVAREA XIX %s/%s carries no "
                  "'Number:' label (layout change?); continuing with the "
                  "header number." % (number, year))
        elif (label.group(1), label.group(2)) != (number, year):
            raise ValueError(
                "row Number label %s/%s contradicts its warning header "
                "NAVAREA XIX %s/%s — refusing to archive a corrupt "
                "harvest (page layout change?)"
                % (label.group(1), label.group(2), number, year))

        if (number, year) in seen:
            print("WARNING: duplicate row NAVAREA XIX %s/%s dropped "
                  "(keeping the first)." % (number, year))
            continue
        seen.add((number, year))
        blocks.append(warning_text.strip() + "\n")

    if not blocks:
        raise ValueError(
            "no NAVAREA XIX warning row found in the page table — "
            "refusing to archive a junk harvest (page layout change?)")
    return "\n".join(blocks).strip() + "\n"


def fetch_page_html() -> Optional[str]:
    """Fetches the Kystverket NAVAREA XIX report page HTML.
    Scrapling's stealthy Fetcher when available, plain requests otherwise.
    Returns the HTML, or None (fail-closed; the error is printed)."""
    html = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                NAVAREA_XIX_URL,
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
                print(f"WARNING: Kystverket page returned HTTP {status}: {snippet}")
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
            resp = requests.get(NAVAREA_XIX_URL,
                               headers=_BROWSER_HEADERS, timeout=_TIMEOUT_S)
        except Exception as e:
            print(f"ERROR: fetch failed for NAVAREA XIX page ({e}); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"ERROR: Kystverket page returned HTTP {resp.status_code}: {snippet}")
            return None
        html = resp.text or ""

    return html


def main() -> bool:
    print("=" * 60)
    print("NAVAREA XIX (Norway / Kystverket) Scraper")
    print(f"Endpoint: {NAVAREA_XIX_URL}")
    print(f"HTTP Fetcher: {'Scrapling' if HAS_SCRAPLING else 'requests' if HAS_REQUESTS else 'none'}")
    print("=" * 60)

    html = fetch_page_html()
    if html is None or not html.strip():
        return False

    try:
        bulletin = extract_bulletin_text(html)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return False

    n_blocks = len([m for m in _HEADER_RE.finditer(bulletin)
                    if "CANCEL" not in
                    bulletin[max(0, m.start() - 8):m.start()].upper()])
    if n_blocks < _MIN_WARNINGS:
        print(f"ERROR: page carried {n_blocks} NAVAREA XIX block(s); "
              f"refusing to sync an empty snapshot.")
        return False

    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin)
    print(f"Harvested {n_blocks} in-force warning block(s) -> {RAW_TXT_PATH}")
    print(f"Verbatim HTML archived -> {RAW_HTML_PATH}")

    from scripts.navarea_universal_parser import main as parse_main
    if not parse_main(RAW_TXT_PATH, PARSED_PATH):
        return False

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
