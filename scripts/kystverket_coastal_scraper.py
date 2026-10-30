#!/usr/bin/env python3
"""
scripts/kystverket_coastal_scraper.py — Norwegian coastal warnings
(Kystverket 'Navigasjonsvarsler' / kystvarsel) scraper.

Source: the Kystverket coastal-warnings report page — the same
NavcoReport ASP.NET application as the NAVAREA XIX report, one table
row per in-force coastal warning (verified live 2026-10-30):

    https://kyvreports.kystverket.no/NavcoReport/navigasjonsvarsler.aspx

Each row carries the coastal series' own numbering — 'Navco År' (year),
'Nr' (number), 'Kunngjort' (announced), a Norwegian 'Varsel' cell and
an English 'Warning' cell. These are Norwegian NATIONAL coastal
warnings outside NAVAREA numbering; they are ingested as the
'coastal-no' pseudo-region (the same pattern as the Australian AUSCOAST
pseudo-regions): canonical ids 'COASTAL NO nnn/yy', source
'manual-coastal-no', navarea column 'COASTAL NO' — the coastal scope is
explicit in every parsed field.

Strategy (fail-closed, mirrors scripts/navarea_xix_scraper.py):
  1. Fetch the page (Scrapling Fetcher — stealthy headers, retries;
     plain-requests fallback). Any error -> non-zero exit, harvest
     untouched, parse and sync NEVER run (never sync a partial snapshot).
  2. Parse the table STRUCTURALLY (stdlib HTMLParser): locate the
     header row by its 'Varsel'/'Warning' cells and map the columns;
     keep, per warning row, the ENGLISH 'Warning' cell text (the
     coordinator's own official translation — ground truth beats any
     machine translation) with line structure preserved. The Norwegian
     'Varsel' cell is archived verbatim alongside (provenance) and is
     used as the warning text ONLY when the English cell is empty.
     A missing header row or column, or a row with an unparsable
     'Navco År'/'Nr' cell, raises ValueError — the harvest is never
     archived and sync never runs (page layout change protection).
     Duplicate rows collapse loudly (keeping the first).
  3. Synthesize one 'COASTAL NO WARNING nnn/yy' block per row (the
     source table carries number/year in columns, not in the text) and
     hand the harvest to the SAME universal parser + generic sync the
     NAVAREA regions use. An empty feed is a legitimate publication
     state: nothing is written and nothing is synced (absence is not
     withdrawal evidence — an empty snapshot must never be synced).

AI assistance (per maintainer direction 2026-10-30), fail-closed, same
layers as every region — never first, never unaudited:
  * Language: the series is published bilingually; the official
    English 'Warning' cell is preferred verbatim. When only the
    Norwegian text exists, the 'coastal-no' parser config enables
    title translation: clearly Norwegian titles are machine-translated
    via shared/translation.py (Gemini, key via the x-goog-api-key
    header only) — on ANY problem the original Norwegian title is kept
    and the ingest still succeeds.
  * Parsing stays deterministic (grounded coordinates only): the Gemini
    bulletin layer refuses keys outside UNIVERSAL_REGIONS, exactly as
    for AUSCOAST; geometry the rule parse cannot resolve fails closed
    to Tier C / no_valid_geometry.

Run:
    python -m scripts.kystverket_coastal_scraper
    python -m scripts.run_kystverket_coastal
"""
import os
import re
import sys
from html.parser import HTMLParser
from typing import Dict, List, Optional

# Scrapling Fetcher: stealthy HTTP client with retries/impersonation
# (https://github.com/D4Vinci/Scrapling) — same idiom as the XIX/X scrapers.
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

COASTAL_NO_URL = (
    "https://kyvreports.kystverket.no/NavcoReport/navigasjonsvarsler.aspx"
)
REGION_KEY = "coastal-no"
HARVEST_DIR = os.path.join("navareas", "coastal_no")
RAW_HTML_PATH = os.path.join(HARVEST_DIR, "latest_raw.html")
RAW_TXT_PATH = os.path.join(HARVEST_DIR, "latest_raw.txt")
RAW_NO_TXT_PATH = os.path.join(HARVEST_DIR, "latest_raw_no.txt")
PARSED_PATH = os.path.join(HARVEST_DIR, "parsed.json")

_TIMEOUT_S = 45

_BROWSER_HEADERS = {
    "accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "referer": (
        "https://kyvreports.kystverket.no/NavcoReport/"
        "navigasjonsvarsler.aspx"
    ),
    "accept-language": "en;q=0.9",
}

# The synthesized block header (number and year come from the table's
# own 'Navco År' / 'Nr' columns; the same regex lives in
# shared/navarea_universal_text.py as RE_COASTAL_NO_HEADER).
_HEADER_TEMPLATE = "COASTAL NO WARNING %s/%s"

_YEAR_RE = re.compile(r"^\s*(20\d{2})\s*$")
_NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s*$")


class _TableParser(HTMLParser):
    """Collects table rows as lists of raw cell texts (stdlib only).

    <br> inside a cell becomes a newline so the warning text keeps its
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
    ('|' edges) stripped, each line's internal whitespace collapsed and
    the source's escaped dots ('1\\. ARBEIDE') normalized so the
    universal parser's numbered-item segmentation can see the items."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    # UPPERCASE entity variants survive the HTML pre-pass when the page
    # double-escapes them ('&amp;NBSP;' decodes to a literal '&NBSP;');
    # stdlib HTMLParser only converts the lowercase forms.
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = text.replace("\\.", ".")
    lines = [re.sub(r"\s+", " ", line).strip(" |").strip()
             for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _map_columns(header_cells: List[str]) -> Dict[str, int]:
    """Maps the coastal table's header cells to column indices.

    Header row (verified live 2026-10-30): 'Navco År', 'Nr',
    'Kunngjort', 'Varsel', 'Warning'. Both language cells are REQUIRED:
    without them the row is not the coastal header and the run fails
    closed rather than guessing columns.
    """
    cols: Dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        u = cell.upper()
        if "KUNNGJORT" in u:
            cols["date"] = idx
        elif u.startswith("VARSEL"):
            cols["norwegian"] = idx
        elif u.startswith("WARNING"):
            cols["english"] = idx
        elif u.strip() == "NR" or u.startswith("NR "):
            cols["number"] = idx
        elif "ÅR" in u:
            cols["year"] = idx
    if "norwegian" not in cols or "english" not in cols:
        raise ValueError(
            "row does not carry both 'Varsel' and 'Warning' header cells "
            "— not the Kystverket coastal table (page layout change?)")
    for need in ("year", "number"):
        if need not in cols:
            raise ValueError(
                "coastal table header lacks the '" + need + "' column "
                "(page layout change?)")
    return cols


def extract_warning_rows(html: str) -> List[Dict[str, str]]:
    """Extracts one record per in-force coastal warning row.

    Returns [{'year': '2026', 'number': '407', 'date': ..., 'english':
    ..., 'norwegian': ...}, ...]. Fail-closed on layout change: a
    missing header row/column raises ValueError; a data row that HAS
    the cells but an unparsable 'Navco År'/'Nr' raises ValueError too
    (a corrupt harvest is never archived). Duplicate (year, number)
    rows collapse loudly, keeping the first.
    """
    # The NavcoReport pages emit UPPERCASE entity variants; stdlib
    # HTMLParser only converts the lowercase ones (&NBSP; observed
    # live; &ARING;/&OSLASH;/&AELIG; defended the same way).
    html = re.sub(r"&nbsp;", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"&aring;", "\u00e5", html, flags=re.IGNORECASE)
    html = re.sub(r"&oslash;", "\u00f8", html, flags=re.IGNORECASE)
    html = re.sub(r"&aelig;", "\u00e6", html, flags=re.IGNORECASE)

    parser = _TableParser()
    parser.feed(html)
    parser.close()

    cols = None
    rows: List[Dict[str, str]] = []
    seen = set()
    for row in parser.rows:
        raw_cells = list(row)
        cleaned = [_clean_cell(c) for c in raw_cells]
        cells = [c for c in cleaned if c]
        if not cells:
            continue
        if cols is None:
            try:
                cols = _map_columns(cleaned)
                continue
            except ValueError:
                # not the header row yet — keep looking (page title,
                # chrome rows come first)
                continue
        if max(cols.values()) >= len(raw_cells):
            continue  # chrome / footer row without the mapped columns

        year_m = _YEAR_RE.match(cleaned[cols["year"]] or "")
        number_m = _NUMBER_RE.match(cleaned[cols["number"]] or "")
        if year_m is None or number_m is None:
            raise ValueError(
                "coastal row carries an unparsable Navco År/Nr cell "
                "(%r / %r) — refusing to archive a corrupt harvest "
                "(page layout change?)"
                % (cleaned[cols["year"]], cleaned[cols["number"]]))

        year = year_m.group(1)
        number = number_m.group(1)
        if (year, number) in seen:
            print("WARNING: duplicate coastal row %s/%s dropped "
                  "(keeping the first)." % (number, year))
            continue
        seen.add((year, number))

        english = _clean_warning(raw_cells[cols["english"]])
        norwegian = _clean_warning(raw_cells[cols["norwegian"]])
        if not english:
            print("WARNING: coastal warning %s/%s has no English cell; "
                  "using the Norwegian text (fail-closed AI title "
                  "translation applies downstream)." % (number, year))
        rows.append({
            "year": year,
            "number": number,
            "date": cleaned[cols.get("date", len(cleaned))] if "date" in cols else "",
            "english": english,
            "norwegian": norwegian,
        })

    if cols is None:
        raise ValueError(
            "no 'Varsel'/'Warning' header row found in the page table — "
            "refusing to archive a junk harvest (page layout change?)")
    return rows


def build_bulletin(rows: List[Dict[str, str]], text_key: str) -> str:
    """Synthesizes the 'coastal-no' bulletin: one 'COASTAL NO WARNING
    nnn/yy' block per row, body taken from the requested language cell.
    The announced date ('Kunngjort') is deliberately NOT part of the
    parse input (it would pollute the extracted title); it stays
    archived in the verbatim HTML and the Norwegian provenance file."""
    blocks = []
    for row in rows:
        body = row[text_key] or row["english"] or row["norwegian"]
        blocks.append(_HEADER_TEMPLATE % (row["number"], row["year"][-2:])
                      + "\n" + body.strip() + "\n")
    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def fetch_page_html() -> Optional[str]:
    """Fetches the Kystverket coastal warnings page HTML.
    Scrapling's stealthy Fetcher when available, plain requests otherwise.
    Returns the HTML, or None (fail-closed; the error is printed)."""
    html = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                COASTAL_NO_URL,
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
                print("WARNING: Kystverket coastal page returned HTTP "
                      + str(status) + ": " + snippet)
                return None
        except Exception as e:
            print("WARNING: Scrapling fetch failed (" + str(e)
                  + "); falling back to requests...")
            html = ""

    if not html:
        if not HAS_REQUESTS:
            print("ERROR: no HTTP client available "
                  "(install scrapling or requests).")
            return None
        try:
            resp = requests.get(COASTAL_NO_URL,
                               headers=_BROWSER_HEADERS, timeout=_TIMEOUT_S)
        except Exception as e:
            print("ERROR: fetch failed for the Kystverket coastal page ("
                  + str(e) + "); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print("ERROR: Kystverket coastal page returned HTTP "
                  + str(resp.status_code) + ": " + snippet)
            return None
        html = resp.text or ""

    return html


def main() -> bool:
    print("=" * 60)
    print("Norwegian Coastal Warnings (Kystverket) Scraper")
    print("Endpoint: " + COASTAL_NO_URL)
    print("HTTP Fetcher: " + ("Scrapling" if HAS_SCRAPLING
                              else "requests" if HAS_REQUESTS else "none"))
    print("=" * 60)

    html = fetch_page_html()
    if html is None or not html.strip():
        return False

    try:
        rows = extract_warning_rows(html)
    except ValueError as exc:
        print("ERROR: " + str(exc))
        return False

    if not rows:
        print("NOTE: the Kystverket coastal table carries no in-force "
              "warning; nothing to parse or sync (absence is not "
              "withdrawal evidence — an empty snapshot is never synced).")
        return True

    bulletin_en = build_bulletin(rows, "english")
    bulletin_no = build_bulletin(rows, "norwegian")

    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin_en)
    with open(RAW_NO_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin_no)
    print("Harvested " + str(len(rows)) + " in-force coastal warning(s) -> "
          + RAW_TXT_PATH)
    print("Norwegian originals archived -> " + RAW_NO_TXT_PATH)
    print("Verbatim HTML archived -> " + RAW_HTML_PATH)

    from scripts.navarea_universal_parser import parse_bulletin_text
    parsed_data = parse_bulletin_text(bulletin_en, REGION_KEY)
    n = len(parsed_data["nav_warnings"])
    if n != len(rows):
        print("ERROR: parser produced " + str(n) + " warning(s) from "
              + str(len(rows)) + " harvested row(s); refusing to sync a "
              "partial parse.")
        return False
    with open(PARSED_PATH, "w", encoding="utf-8") as f:
        import json
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    n_geom = len([w for w in parsed_data["nav_warnings"] if w.get("spatial")])
    print("Parsed " + str(n) + " warning(s); " + str(n_geom)
          + " with resolvable geometry (" + str(n - n_geom)
          + " fail closed to Tier C / no_valid_geometry).")

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
