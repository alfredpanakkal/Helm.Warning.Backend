#!/usr/bin/env python3
"""
scripts/navarea_v_scraper.py — NAVAREA V (Brazil / CHM) JSON scraper.

Source: the CHM (Centro de Hidrografia da Marinha) 'Avisos-Radio
Nauticos e SAR' portal:

    https://www.marinha.mil.br/chm/dados-do-segnav-aviso-radio-nautico-tela/avisos-radio-nauticos-e-sar

The interactive page (behind bot protection) is fed by a plain JSON
snapshot attached to it as a Drupal file link named 'avradio_NN.json'
(NN increments per publish, e.g. avradio_79.json, ~540 KB). The file
carries one 'atualizado' timestamp plus an 'avisos' array; each record:
  numero   '0648/26' bare (NAVAREA V series), 'SAR 0169/26', 'I 9179/26'
  costa    category code ('SAR'/'I'/'N'/'E'/'S'/... or empty)
  tipo     single-letter type code ('Z'/'L'/'C')
  textoPT / textoEN   full warning text (Portuguese / English)
  geometry raw google.maps JS snippet (marker/polygon/polyline),
           '|'-separated; archived verbatim, never fed to the parser.

Strategy (fail-closed, mirrors scripts/navarea_iii_scraper.py):
  1. Fetch the listing page, locate the avradio_NN.json link by name
     (highest NN wins — the publish number increments) and fetch the
     JSON (Scrapling Fetcher — stealthy headers, retries; requests
     fallback). Any error -> non-zero exit, harvest untouched, parse
     and sync NEVER run (never sync a partial snapshot).
  2. Keep ONLY the bare-numbered records ('0648/26') — the NAVAREA V
     series. SAR ('SAR 0169/26') and costeiro ('I 9179/26', 'N', 'E',
     'S', ...) records are Brazilian national warnings outside the
     NAVAREA numbering; they are counted and skipped loudly (the
     region 'v' parser only recognizes bare 'nnnn/yy' headers — a
     prefixed record would glue itself onto the previous block and
     corrupt it). Records without English text are skipped loudly.
  3. Synthesize the plain-text bulletin in the exact bare-'0648/26'
     block format the universal parser ingests for region 'v' (see
     tests/fixtures/navarea_v_sample.txt), English text only, newest
     first. The verbatim JSON is archived alongside for provenance.
  4. Hand the harvest to the SAME universal parser + generic sync the
     manual paste pipeline uses — one contract, scrape or paste.

NOTE the harvest dir is 'navareas/navarea_v/': region resolution is
PATH-based for this feed — the bare-number bulletin carries no NAVAREA
numeral, so resolve_region() must find the region in the dir name.

Run:
    python -m scripts.navarea_v_scraper
    python -m scripts.run_navarea_v
"""
import html
import json
import os
import re
import sys
from typing import List, Optional
from urllib.parse import urljoin

# Scrapling Fetcher: stealthy HTTP client with retries/impersonation
# (https://github.com/D4Vinci/Scrapling) — same idiom as
# scripts/navarea_iii_scraper.py.
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

NAVAREA_V_LISTING_URL = ("https://www.marinha.mil.br/chm/dados-do-segnav-"
                         "aviso-radio-nautico-tela/avisos-radio-nauticos-e-sar")
REGION_KEY = "v"
# Path-based region resolution: the universal parser's resolve_region()
# matches 'navarea[_-]v' in the harvest dir name (the bare-number
# bulletin carries no NAVAREA numeral for the text-based fallback).
HARVEST_DIR = os.path.join("navareas", "navarea_" + REGION_KEY)
RAW_JSON_PATH = os.path.join(HARVEST_DIR, "latest_raw.json")
RAW_TXT_PATH = os.path.join(HARVEST_DIR, "latest_raw.txt")
PARSED_PATH = os.path.join(HARVEST_DIR, "parsed.json")

_TIMEOUT_S = 45
_MIN_WARNINGS = 1  # a live-but-empty feed fails loudly; never sync 0.

_BROWSER_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/json;q=0.9,"
               "*/*;q=0.8"),
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "referer": NAVAREA_V_LISTING_URL,
    "accept-language": "en,pt-BR;q=0.8",
}

# Drupal file attachment: <a href=".../avradio_79.json">... The file
# number increments per publish, so the HIGHEST avradio_NN wins.
RE_AVRADIO_HREF = re.compile(
    r"""href=["']([^"'<>\s]*avradio_(\d+)\.json[^"'<>\s]*)["']""",
    re.IGNORECASE,
)
# Bare NAVAREA V series number ('0648/26'). Prefixed records ('SAR
# 0169/26', 'I 9179/26', 'N 0599/26', ...) are national warnings.
RE_BARE_NAVAREA_NUMBER = re.compile(r"^\d{1,4}/\d{2}$")


def _fetch_text(url: str, expect: str) -> Optional[str]:
    """Fetches a URL. Scrapling's stealthy Fetcher when available, plain
    requests otherwise. Returns the body text, or None (fail-closed;
    the error is printed). 'expect' is a marker the body must contain
    (guards against bot-check / captive-portal HTML pages)."""
    text = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                url,
                headers=_BROWSER_HEADERS,
                timeout=_TIMEOUT_S,
                retries=3,
                stealthy_headers=True,
            )
            status = getattr(page, "status", None)
            body = page.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            text = str(body or "")
            if status != 200:
                snippet = text[:200].replace("\n", " ")
                print(f"WARNING: {url} returned HTTP {status}: {snippet}")
                return None
        except Exception as e:
            print(f"WARNING: Scrapling fetch failed ({e}); "
                  f"falling back to requests...")
            text = ""

    if not text:
        if not HAS_REQUESTS:
            print("ERROR: no HTTP client available "
                  "(install scrapling or requests).")
            return None
        try:
            resp = requests.get(url, headers=_BROWSER_HEADERS,
                                timeout=_TIMEOUT_S)
        except Exception as e:
            print(f"ERROR: fetch failed for {url} ({e}); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"ERROR: {url} returned HTTP {resp.status_code}: "
                  f"{snippet}")
            return None
        text = resp.text or ""

    if expect not in text:
        # A bot-check / error page would otherwise be archived as the
        # harvest and fail obscurely in the parser.
        print(f"ERROR: response from {url} did not contain {expect!r}: "
              f"{text[:200]}")
        return None

    return text


def find_latest_avradio_url(listing_html: str) -> Optional[str]:
    """Extracts the newest avradio_NN.json URL from the CHM listing page.

    The publish number NN increments, so the highest match wins. Returns
    the absolute URL, or None (fail-closed; the error is printed)."""
    matches = RE_AVRADIO_HREF.findall(listing_html or "")
    if not matches:
        print("ERROR: no avradio_NN.json link found on the CHM listing "
              "page (bot-check page or layout change?).")
        return None
    href, _seq = max(matches, key=lambda m: int(m[1]))
    resolved = urljoin(NAVAREA_V_LISTING_URL, html.unescape(href))
    print(f"Found avradio link: {resolved} "
          f"({len(matches)} link(s) on the page)")
    return resolved


def parse_aviso_records(json_text: str) -> dict:
    """Extracts the in-force NAVAREA V records from the CHM JSON.

    Returns {'atualizado': str, 'records': [...], 'skipped': {...}}:
    records are {'number', 'year', 'text'}, newest first. Non-NAVAREA
    records (SAR / costeiro / prefixed numbers) and records without
    English text cannot be keyed into the region 'v' bulletin and are
    skipped loudly (counted per category)."""
    try:
        data = json.loads(json_text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"CHM JSON did not parse: {exc}")

    avisos = data.get("avisos") if isinstance(data, dict) else None
    if not isinstance(avisos, list):
        raise ValueError("CHM JSON carries no 'avisos' array")

    records: List[dict] = []
    skipped: dict = {}
    for aviso in avisos:
        if not isinstance(aviso, dict):
            skipped["malformed"] = skipped.get("malformed", 0) + 1
            print("WARNING: skipping non-object aviso record.")
            continue
        numero = str(aviso.get("numero") or "").strip()
        text_en = str(aviso.get("textoEN") or "").strip()
        if not numero:
            skipped["without_number"] = skipped.get("without_number", 0) + 1
            print("WARNING: skipping aviso record without numero.")
            continue
        if not RE_BARE_NAVAREA_NUMBER.match(numero):
            label = numero.split()[0] if " " in numero else "prefixed"
            skipped[label] = skipped.get(label, 0) + 1
            continue
        if not text_en:
            skipped["without_english_text"] = \
                skipped.get("without_english_text", 0) + 1
            print(f"WARNING: skipping aviso without English text "
                  f"(numero={numero!r}).")
            continue
        number, year = numero.split("/")
        records.append({"number": number, "year": year, "text": text_en})

    records.sort(key=lambda r: (r["year"], r["number"].zfill(4)),
                 reverse=True)
    return {
        "atualizado": str(data.get("atualizado") or "").strip(),
        "records": records,
        "skipped": skipped,
    }


def synthesize_bulletin(records: List[dict]) -> str:
    """Renders the records as the plain-text bulletin the universal
    parser ingests for region 'v': bare '0648/26' header lines (the
    Brazil quirk — no NAVAREA numeral anywhere), then the English text
    (block format identical to tests/fixtures/navarea_v_sample.txt)."""
    blocks = []
    for r in records:
        blocks.append(f"{r['number']}/{r['year']}\n{r['text']}")
    return "\n\n\n".join(blocks) + "\n"


def main() -> bool:
    print("=" * 60)
    print("NAVAREA V (Brazil / CHM) JSON Scraper")
    print(f"Listing page: {NAVAREA_V_LISTING_URL}")
    print(f"HTTP Fetcher: {'Scrapling' if HAS_SCRAPLING else 'requests' if HAS_REQUESTS else 'none'}")
    print("=" * 60)

    listing_html = _fetch_text(NAVAREA_V_LISTING_URL, expect="avradio")
    if listing_html is None:
        return False

    json_url = find_latest_avradio_url(listing_html)
    if json_url is None:
        return False

    json_text = _fetch_text(json_url, expect='"avisos"')
    if json_text is None:
        return False

    try:
        parsed = parse_aviso_records(json_text)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return False

    records = parsed["records"]
    if len(records) < _MIN_WARNINGS:
        print(f"ERROR: CHM JSON carried {len(records)} usable NAVAREA V "
              f"record(s); refusing to overwrite the harvest / sync an "
              f"empty snapshot.")
        return False

    if parsed["skipped"]:
        parts = ", ".join(f"{k}={v}"
                          for k, v in sorted(parsed["skipped"].items()))
        print(f"Skipped non-NAVAREA / unusable record(s): {parts}")
    if parsed["atualizado"]:
        print(f"Source snapshot updated at: {parsed['atualizado']}")

    bulletin = synthesize_bulletin(records)
    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_JSON_PATH, "w", encoding="utf-8") as f:
        f.write(json_text)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin)
    print(f"Harvested {len(records)} in-force NAVAREA V warning(s) -> {RAW_TXT_PATH}")
    print(f"Verbatim JSON archived -> {RAW_JSON_PATH}")

    from scripts.navarea_universal_parser import main as parse_main
    if not parse_main(RAW_TXT_PATH, PARSED_PATH):
        return False

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
