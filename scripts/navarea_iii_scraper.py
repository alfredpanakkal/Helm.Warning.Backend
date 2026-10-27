#!/usr/bin/env python3
"""
scripts/navarea_iii_scraper.py — NAVAREA III (Spain / IHM) XML scraper.

Source: the IHM 'Navareas en vigor' portal. The interactive page
(Index_Navareas_xml_en.html — 'display all' opens a JS popup) is fed by a
plain XML snapshot that needs NO browser:

    https://armada.defensa.gob.es/ihm/XML/navareas_crudo.xml

One <NAVAREASVIGOR> record per in-force warning, bilingual:
  nnuna  sort key 'YYnnnn'   nnunaf warning number '0092/22'
  nfemi  issue date (ISO)    nlocae/nlocai area (ES/EN)
  ntees / ntein  full text (ES/EN)   nasun/nasuni subject (ES/EN)

Strategy (fail-closed, mirrors scripts/navarea_universal_scraper.py):
  1. Fetch the XML (Scrapling Fetcher — stealthy headers, retries;
     requests fallback); any error -> non-zero exit, harvest untouched,
     parse and sync NEVER run (never sync a partial snapshot).
  2. Synthesize the plain-text bulletin in the exact 'NAVAREA III -
     nnn/yy' block format the universal parser ingests for region 'iii'
     (see tests/fixtures/navarea_iii_sample.txt): newest first, English
     fields only. The verbatim XML is archived alongside for provenance.
  3. Hand the harvest to the SAME universal parser + generic sync the
     manual paste pipeline uses — one contract, scrape or paste.

Run:
    python -m scripts.navarea_iii_scraper
    python -m scripts.run_navarea_iii
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
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

NAVAREA_III_XML_URL = "https://armada.defensa.gob.es/ihm/XML/navareas_crudo.xml"
REGION_KEY = "iii"
HARVEST_DIR = os.path.join("navareas", REGION_KEY)
RAW_XML_PATH = os.path.join(HARVEST_DIR, "latest_raw.xml")
RAW_TXT_PATH = os.path.join(HARVEST_DIR, "latest_raw.txt")
PARSED_PATH = os.path.join(HARVEST_DIR, "parsed.json")

_TIMEOUT_S = 45
_MIN_WARNINGS = 1  # a live-but-empty feed fails loudly; never sync 0.

_BROWSER_HEADERS = {
    "accept": "text/xml,application/xml;q=0.9,*/*;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "referer": "https://armada.defensa.gob.es/ihm/Aplicaciones/Navareas/Index_Navareas_xml_en.html",
    "accept-language": "en,es;q=0.8",
}


# --- IHM malformed-tag repair -------------------------------------------
# The live crudo XML embeds stray CR/LF inside <NAVAREASVIGOR> tag names
# (verified 2026-10-27: an opening tag rendered as '<NAVAR<newline>EASVIGOR>'
# and one closing tag '</NAVAREASVIGOR<newline>>'), which is not well-formed
# XML and aborts ElementTree. Collapse whitespace inside tag names before
# parsing. Attribute-bearing tags (e.g. <dataroot xmlns:od=...>) do not
# match and are left untouched.
_TAG_WITH_WS = re.compile(r"<(/?)([A-Za-z]+(?:\s+[A-Za-z]+)*)\s*>")


def _repair_ihm_tag_names(xml_text: str) -> str:
    """Collapses stray whitespace inside XML tag names (see comment above)."""
    return _TAG_WITH_WS.sub(
        lambda m: "<" + m.group(1) + re.sub(r"\s+", "", m.group(2)) + ">",
        xml_text,
    )


def fetch_crudo_xml() -> Optional[str]:
    """Fetches the IHM in-force NAVAREA III XML snapshot.

    Scrapling's stealthy Fetcher when available, plain requests otherwise.
    Returns the XML text, or None (fail-closed; the error is printed).
    """
    text = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                NAVAREA_III_XML_URL,
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
                print(f"WARNING: crudo XML returned HTTP {status}: {snippet}")
                return None
        except Exception as e:
            print(f"WARNING: Scrapling fetch failed ({e}); falling back to requests...")
            text = ""

    if not text:
        if not HAS_REQUESTS:
            print("ERROR: no HTTP client available "
                  "(install scrapling or requests).")
            return None
        try:
            resp = requests.get(NAVAREA_III_XML_URL,
                                headers=_BROWSER_HEADERS, timeout=_TIMEOUT_S)
        except Exception as e:
            print(f"ERROR: fetch failed for NAVAREA III XML ({e}); harvest untouched.")
            return None
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"ERROR: crudo XML returned HTTP {resp.status_code}: {snippet}")
            return None
        text = resp.text or ""

    if "NAVAREASVIGOR" not in text:
        # An HTML error page / captive portal would otherwise be archived
        # as the harvest and fail obscurely in the parser.
        print(f"ERROR: response did not contain NAVAREASVIGOR records: {text[:200]}")
        return None

    return text


def parse_xml_records(xml_text: str) -> List[dict]:
    """Extracts the English in-force warning records from the IHM XML.

    Returns a list of {sort_key, number, issued, area, subject, text},
    newest first (nnuna 'YYnnnn' descending — the same order the portal
    table shows). Records without a number or English text are skipped
    loudly (they cannot be keyed into nav_warnings).
    """
    try:
        root = ET.fromstring(_repair_ihm_tag_names(xml_text))
    except ET.ParseError as exc:
        raise ValueError(f"IHM XML did not parse: {exc}")

    records: List[dict] = []
    for node in root.iter("NAVAREASVIGOR"):
        def _get(tag: str) -> str:
            return (node.findtext(tag) or "").strip()

        number = _get("nnunaf")
        text = _get("ntein")
        if not number or "/" not in number or not text:
            print(f"WARNING: skipping NAVAREASVIGOR record without "
                  f"number/English text (nnunaf={number!r}).")
            continue
        records.append({
            "sort_key": _get("nnuna") or "000000",
            "number": number,
            "issued": _get("nfemi"),
            "area": _get("nlocai"),
            "subject": _get("nasuni"),
            "text": text,
        })

    records.sort(key=lambda r: r["sort_key"], reverse=True)
    return records


def _format_issued(iso: str) -> str:
    """'2026-10-12T00:00:00' -> '12 October 2026 00:00 UTC' (fixture format).
    Falls back to the raw string when the date is not ISO."""
    try:
        return datetime.fromisoformat(iso).strftime("%d %B %Y %H:%M UTC")
    except (ValueError, TypeError):
        return iso


def synthesize_bulletin(records: List[dict]) -> str:
    """Renders the records as the plain-text bulletin the universal parser
    ingests for region 'iii' (block format: header / issue date / area /
    subject / body, blank-line separated)."""
    blocks = []
    for r in records:
        lines = [f"NAVAREA III - {r['number']}",
                 _format_issued(r["issued"]),
                 r["area"]]
        if r["subject"]:
            lines.append(r["subject"])
        lines.append(r["text"])
        blocks.append("\n".join(lines))
    return "\n\n\n".join(blocks) + "\n"


def main() -> bool:
    print("=" * 60)
    print("NAVAREA III (Spain / IHM) XML Scraper")
    print(f"Endpoint: {NAVAREA_III_XML_URL}")
    print(f"HTTP Fetcher: {'Scrapling' if HAS_SCRAPLING else 'requests' if HAS_REQUESTS else 'none'}")
    print("=" * 60)

    xml_text = fetch_crudo_xml()
    if xml_text is None or not xml_text.strip():
        return False

    try:
        records = parse_xml_records(xml_text)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return False

    if len(records) < _MIN_WARNINGS:
        print(f"ERROR: IHM XML carried {len(records)} usable record(s); "
              f"refusing to overwrite the harvest / sync an empty snapshot.")
        return False

    bulletin = synthesize_bulletin(records)
    os.makedirs(HARVEST_DIR, exist_ok=True)
    with open(RAW_XML_PATH, "w", encoding="utf-8") as f:
        f.write(xml_text)
    with open(RAW_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(bulletin)
    print(f"Harvested {len(records)} in-force warning(s) -> {RAW_TXT_PATH}")
    print(f"Verbatim XML archived -> {RAW_XML_PATH}")

    from scripts.navarea_universal_parser import main as parse_main
    if not parse_main(RAW_TXT_PATH, PARSED_PATH):
        return False

    from scripts.navarea_generic_sync import sync_to_supabase
    return sync_to_supabase(PARSED_PATH)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
