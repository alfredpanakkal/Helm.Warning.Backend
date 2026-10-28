#!/usr/bin/env python3
"""
scripts/navarea_ix_scraper.py — NAVAREA IX (Pakistan / NHO) scraper.

Source: the National Hydrographic Office Pakistan 'NAVAREA IX WARNINGS'
page. The page itself carries only a metadata table (S.NO / REGION /
DTG / WARNING # / DESCRIPTION / ATTACHMENT) — the full text of every
in-force warning sits in a separate plain-text 'View Document' file
published by the site's navarea-warnings plugin:

    https://hydrography.paknavy.gov.pk/wp-content/plugins/
      navarea-warnings/custom_uploaded_warnings_for_navarea/
      20261027SEC 412.txt

Each file is ALREADY the exact block format the universal parser
ingests for region 'ix' (DTG line, 'NAVAREA IX nnn/yy' header, region /
area / charts lines, numbered paragraphs — see
tests/fixtures/navarea_ix_sample.txt), so the harvest is a plain
concatenation — no synthesis step.

Document-link resolution (re-verified live 2026-10-27):
  1. Prefer the row's own link: the raw server HTML sometimes carries
     the 'View Document' href, sometimes only a data-* / onclick
     variant, and sometimes none at all (the live page now builds the
     anchors client-side — the first CI run found no href in any row
     and correctly refused to sync). Relative or unquoted values are
     resolved against the page URL.
  2. Otherwise derive the document URL from the row DTG. The filename
     is '<YYYYMMDD><SEC|EC> <NNN>.txt' where the date follows the DTG
     day, the prefix is inconsistent (412/26 -> '20261027SEC 412.txt'
     but 394/26 -> '20261021EC 394.txt' — the reason a plain 'SEC'
     guess once looked like a missing file) and the warning number is
     zero-padded to three digits. Both prefixes are probed, in order.
     Every candidate is validated against the advertised warning's
     own 'NAVAREA IX nnn/yy' header — the site's 404 page comes back
     with an HTTP-200 body, so status alone proves nothing.

Strategy (fail-closed, mirrors scripts/navarea_vii_scraper.py):
  1. Fetch the page (Scrapling Fetcher — stealthy headers, retries;
     requests fallback); any error -> non-zero exit, harvest untouched,
     parse and sync NEVER run (never sync a partial snapshot).
     Transient HTTP 429 / 503 answers (the site rate-limits request
     bursts) are retried with backoff before any fail-closed refusal.
  2. Resolve one document per table row. A row whose document
     cannot be fetched — unreachable even after transient retries; the
     site advertises links its own WAF refuses (persistent HTTP 429 on
     20250903SEC 405.txt for the CI runner, live 2026-10-28) — or whose
     DTG-derived candidates all miss is skipped loudly (never silently).
     A row whose ADVERTISED document carries the WRONG warning header
     still fails the whole harvest (systematic link corruption). Zero
     resolved rows -> refuse (empty snapshot). The verbatim page HTML
     is archived alongside for provenance.
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
from urllib.parse import quote as _urlquote, urljoin as _urljoin

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
# Politeness pause before EVERY document fetch (resolved hits and
# candidate misses alike). The site rate-limited a ~1.8 req/s harvest
# burst with HTTP 429 (Cloudflare) after ~110 files in ~60s — seen
# live 2026-10-28, when one 429 on a single advertised document
# aborted the whole harvest.
_DOC_PAUSE_S = 0.6
# Transient HTTP answers retried with backoff before a fetch fails
# closed: rate limiting (429) / temporary unavailability (503).
_TRANSIENT_STATUSES = frozenset({429, 503})
_TRANSIENT_RETRIES = 3
_RETRY_AFTER_DEFAULT_S = 20.0

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
# ATTACHMENT ('View Document'). The WARNING # cell is the only bare
# 'nnn/yy' token; the ATTACHMENT cell carries the document link when
# the server renders one at all.
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_WARNING_NUM_RE = re.compile(r"^\s*(\d{1,4})\s*/\s*(\d{2,4})\s*$")

# Link attributes: quoted, single-quoted or UNQUOTED values, plus the
# common data-* carriers and onclick URL literals. '#' placeholders and
# javascript: URLs are ignored (they are not document links).
_ATTR_URL_RES = (
    re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
               re.IGNORECASE),
    re.compile(r"""data-(?:href|file|url|src|attachment)\s*=\s*"""
               r"""(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE),
)
_ONCLICK_URL_RE = re.compile(
    r"""(?:"|')(https?://[^"'\s]+\.txt)(?:"|')""", re.IGNORECASE)

# Row DTG shapes seen on the live page: '271500 UTC OCT 2026',
# '300935 UTC SEP 26', '240800 UTC JULY 2026'.
_DTG_RE = re.compile(r"\b(\d{2})(\d{4})\s+UTC\s+([A-Za-z]+)\.?\s+(\d{2,4})\b",
                     re.IGNORECASE)
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}

# Plain-text document directory of the navarea-warnings plugin (stable
# across every Wayback capture of the site back to 2022).
_DOC_URL_BASE = ("https://hydrography.paknavy.gov.pk/wp-content/plugins/"
                 "navarea-warnings/custom_uploaded_warnings_for_navarea/")
_DOC_PREFIXES = ("SEC", "EC")  # both live on the site (see docstring)

# Every harvested document must open with its own 'NAVAREA IX nnn/yy'
# header (verified in every live file sampled: 412/26, 410/26, 409/26,
# 394/26, 378/26, 347/26, 463/25) — this is what the universal parser
# anchors on, and what validates DTG-derived candidate URLs.
_HEADER_FOR_RE = re.compile(r"NAV\s*AREA\s+IX\b", re.IGNORECASE)


def _strip_tags(fragment: str) -> str:
    """HTML fragment -> visible text (tags to spaces, entities decoded)."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _retry_after_seconds(headers) -> Optional[float]:
    """Numeric 'Retry-After' header value in seconds, when present."""
    if not headers:
        return None
    try:
        raw = headers.get("Retry-After")
        return float(raw) if raw else None
    except (AttributeError, TypeError, ValueError):
        return None


def _fetch_once(url: str, headers: dict
                ) -> Tuple[Optional[str], Optional[int], Optional[float]]:
    """One fetch attempt: Scrapling Fetcher first, requests fallback.

    Returns (body_text, status, retry_after_seconds). body_text is
    None on any failure; status is reported for HTTP-level failures so
    the caller can retry the transient ones (429 / 503).
    """
    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(url, headers=headers, timeout=_TIMEOUT_S,
                               retries=3, stealthy_headers=True)
            status = getattr(page, "status", None)
            body = page.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            body_text = str(body or "")
            if status == 200:
                return body_text, status, None
            if status in _TRANSIENT_STATUSES:
                return None, status, _retry_after_seconds(
                    getattr(page, "headers", None))
            snippet = body_text[:200].replace("\n", " ")
            print(f"WARNING: {url} returned HTTP {status}: {snippet}")
            return None, status, None
        except Exception as e:
            print(f"WARNING: Scrapling fetch failed for {url} ({e}); "
                  f"falling back to requests...")

    if not HAS_REQUESTS:
        print("ERROR: no HTTP client available "
              "(install scrapling or requests).")
        return None, None, None
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT_S)
    except Exception as e:
        print(f"ERROR: fetch failed for {url} ({e}); harvest untouched.")
        return None, None, None
    if resp.status_code == 200:
        return resp.text or "", resp.status_code, None
    if resp.status_code in _TRANSIENT_STATUSES:
        return None, resp.status_code, _retry_after_seconds(resp.headers)
    snippet = (resp.text or "")[:200].replace("\n", " ")
    print(f"ERROR: {url} returned HTTP {resp.status_code}: {snippet}")
    return None, resp.status_code, None


def fetch_url(url: str, accept: str) -> Optional[str]:
    """Fetches a URL as text.

    Scrapling's stealthy Fetcher when available, plain requests
    otherwise. Transient answers (HTTP 429 / 503 — the site rate-limits
    request bursts; seen live 2026-10-28) are retried with backoff,
    honouring a numeric Retry-After header when present, before the
    fetch fails closed. Returns the body text, or None (printed).
    """
    _headers = dict(_BROWSER_HEADERS)
    _headers["accept"] = accept

    for attempt in range(_TRANSIENT_RETRIES + 1):
        body_text, status, retry_after = _fetch_once(url, _headers)
        if body_text is not None:
            return body_text
        if status not in _TRANSIENT_STATUSES:
            return None
        if attempt < _TRANSIENT_RETRIES:
            wait_s = retry_after or (_RETRY_AFTER_DEFAULT_S * (attempt + 1))
            print(f"WARNING: {url} returned HTTP {status}; retrying in "
                  f"{wait_s:.0f}s "
                  f"(attempt {attempt + 1}/{_TRANSIENT_RETRIES})...")
            time.sleep(wait_s)
    return None


def _attr_url_values(fragment: str) -> List[str]:
    """Raw values of href / data-href / data-file / ... in a fragment."""
    values: List[str] = []
    for rx in _ATTR_URL_RES:
        for hm in rx.finditer(fragment):
            val = next((g for g in hm.groups() if g), None)
            if val:
                values.append(val)
    return values


def _row_link(cells: List[str], row_html: str) -> Optional[str]:
    """The row's document URL, or None.

    Looks in every cell first, then the whole row. Values are entity-
    decoded, resolved against the page URL and only accepted when they
    are http(s); '#'-placeholders and javascript: URLs are ignored.
    """
    for fragment in list(cells) + [row_html]:
        for raw in _attr_url_values(fragment):
            val = _html.unescape(raw).strip()
            if not val or val.startswith("#") or val.lower().startswith("javascript:"):
                continue
            url = _urljoin(NAVAREA_IX_URL, val)
            if url.lower().startswith("http"):
                return url
    hm = _ONCLICK_URL_RE.search(row_html)
    if hm:
        return hm.group(1)
    return None


def _dtg_datestamp(dtg_text: str) -> Optional[str]:
    """Row DTG text -> 'YYYYMMDD', or None when unparseable."""
    m = _DTG_RE.search(dtg_text or "")
    if not m:
        return None
    day, _hhmm, mon, yr = m.groups()
    month = _MONTHS.get(mon[:3].upper())
    if month is None or not 1 <= int(day) <= 31:
        return None
    year = int(yr)
    if year < 100:
        year += 2000
    return "%04d%02d%02d" % (year, month, int(day))


def _candidate_doc_urls(number: str, dtg_text: str) -> List[str]:
    """DTG-derived candidate document URLs for a link-less row.

    Filename anatomy (verified live 2026-10-27): '<YYYYMMDD><SEC|EC>
    <NNN>.txt' — date follows the DTG day, prefix is inconsistent
    (SEC for most rows, EC for e.g. 394/26), warning number is zero-
    padded to three digits (Wayback shows '024.txt', '086.txt').
    Candidates are probed in order and validated by header, so a wrong
    guess is a cheap miss, never a bad ingest.
    """
    datestamp = _dtg_datestamp(dtg_text)
    if not datestamp:
        return []
    padded = number.zfill(3)
    return [_DOC_URL_BASE + _urlquote("%s%s %s.txt" % (datestamp, prefix, padded))
            for prefix in _DOC_PREFIXES]


def extract_rows(page_html: str) -> List[Tuple[str, str, Optional[str], str]]:
    """Extracts (number, year, href-or-None, dtg) per in-force warning row.

    A row that advertises a warning number is kept even when its
    ATTACHMENT cell carries no link — the document URL can be derived
    from the row DTG (see _candidate_doc_urls). The header row is
    ignored.
    """
    rows: List[Tuple[str, str, Optional[str], str]] = []
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
        dtg = _strip_tags(cells[2]) if len(cells) > 2 else ""
        href = _row_link(cells, row_html)
        rows.append((number, year, href, dtg))
    return rows


def _expected_header_re(number: str, year: str) -> "re.Pattern":
    yy = year[-2:]
    return re.compile(
        r"NAV\s*AREA\s+IX\s+" + re.escape(number) +
        r"\s*/\s*" + re.escape(yy) + r"(?!\d)", re.IGNORECASE)


def assemble_bulletin(rows: List[Tuple[str, str, Optional[str], str]],
                      fetch_doc: Callable[[str], Optional[str]]) -> Optional[str]:
    """Resolves every row's document and concatenates the blocks.

    Fail-closed where it matters:
      * a row whose document cannot be fetched — unreachable even
        after transient retries (the site advertises links its own WAF
        refuses for some clients; seen live 2026-10-28) — is skipped
        loudly like a candidate miss: one dead document must not abort
        the whole ~100-warning sync;
      * a row whose ADVERTISED document carries the WRONG warning
        header still fails the whole harvest (systemic corruption);
      * zero resolved documents overall -> None (empty snapshot).
    """
    blocks: List[str] = []
    for number, year, href, dtg in rows:
        expected = _expected_header_re(number, year)
        if href:
            candidates: List[Tuple[str, bool]] = [(href, False)]
        else:
            candidates = [(u, True) for u in _candidate_doc_urls(number, dtg)]

        block: Optional[str] = None
        for url, skippable in candidates:
            doc = fetch_doc(url)
            if doc is None or not doc.strip():
                # Unreachable after transient retries (persistent 429/
                # 404 — the site advertises links its own WAF refuses
                # for some clients; seen live 2026-10-28). Skip loudly
                # and keep harvesting — one dead document must not
                # abort a ~100-warning sync; zero resolved overall
                # still refuses the empty snapshot below.
                print(f"WARNING: no content for warning {number}/{year} "
                      f"from {url} — skipping row loudly "
                      f"({'advertised link unreachable' if not skippable else 'candidate miss'})")
                continue
            doc = doc.replace("\r\n", "\n").replace("\r", "\n")
            block = "\n".join(line.rstrip() for line in doc.split("\n")).strip()
            if not expected.search(block):
                if not skippable:
                    print(f"ERROR: document for {number}/{year} does not carry "
                          f"its own 'NAVAREA IX {number}/{year[-2:]}' header; "
                          f"refusing it (wrong link? {url})")
                    return None
                block = None
                continue
            break

        if block is None:
            print(f"WARNING: no document found for warning {number}/{year} "
                  f"(no usable link{'' if href else ' and no DTG-derived candidate hit'}) "
                  f"— skipping row loudly (page layout change?)")
            continue
        blocks.append(block)

    if not blocks:
        print("ERROR: no warning document resolved; refusing to sync an "
              "empty snapshot (page layout change?)")
        return None
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

    def _fetch_doc(url: str) -> Optional[str]:
        # Politeness pause before EVERY document fetch — resolved hits
        # and candidate misses alike (see _DOC_PAUSE_S: the site rate-
        # limits request bursts).
        if _DOC_PAUSE_S:
            time.sleep(_DOC_PAUSE_S)
        return fetch_url(url, "text/plain;q=0.9,*/*;q=0.8")

    bulletin = assemble_bulletin(rows, _fetch_doc)
    if bulletin is None:
        return False

    n_blocks = len(_HEADER_FOR_RE.findall(bulletin))
    skipped = len(rows) - n_blocks
    if skipped:
        print(f"NOTE: resolved {n_blocks} of {len(rows)} warning row(s); "
              f"{skipped} skipped loudly (see warnings above).")

    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(page_html)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin)
    print(f"Harvested {n_blocks} in-force warning(s) -> {RAW_TXT_PATH}")
    print(f"Verbatim page HTML archived -> {RAW_HTML_PATH}")

    from scripts.navarea_universal_parser import main as parse_main
    if not parse_main(RAW_TXT_PATH, PARSED_PATH):
        return False

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
