#!/usr/bin/env python3
"""
baltic_scraper.py — Sjöfartsverket VHF Navigational Warnings Scraper
Hardened scraper with defensive DOM parsing and fallback strategies.

Failure contract: a fetch failure (network error, non-200, missing HTTP
libraries) returns None — the pipeline runner aborts loudly before
parse/sync. A valid empty harvest ({}) is only returned when the page was
fetched successfully and genuinely carries no warnings.
"""

import sys
import os
import re
import html

# Ensure repo root is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    try:
        import requests as cffi_requests
        HAS_CURL_CFFI = False
    except ImportError:
        cffi_requests = None
        HAS_CURL_CFFI = False

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

URL = "https://navvarn.sjofartsverket.se/en/Navigationsvarningar/VHF"


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\xa0', ' ')
    return text.strip()


def _harvest_paragraph(p, area_name: str, collected_warnings: dict):
    p_text = clean_text(p.get_text())
    if not p_text or "No current warnings in the area" in p_text:
        return

    # Check for bold or strong tag
    header_tag = p.find(["b", "strong"])
    header_raw = clean_text(header_tag.get_text()) if header_tag else ""

    # If no bold tag, search for NAV WARN pattern at beginning of text
    if not header_raw:
        header_match = re.search(r'((?:BALTIC\s+SEA|SWEDISH)?\s*NAV\s*WARN\s*[\w\d\/\-]+)', p_text, re.IGNORECASE)
        if header_match:
            header_raw = header_match.group(1).strip()

    if not header_raw:
        return

    header_clean = " ".join(header_raw.split())
    date_match = re.search(r'(\d{6}\s+UTC\s+[A-Z]{3})', p_text)
    date_str = date_match.group(1) if date_match else ""

    span_tag = p.find("span")
    if span_tag:
        body_clean = clean_text(span_tag.get_text())
    else:
        body_clean = p_text.replace(header_raw, "").replace(date_str, "").strip()

    if not body_clean:
        return

    key = header_clean
    if key not in collected_warnings:
        collected_warnings[key] = {
            "header": header_clean,
            "date_str": date_str,
            "body": body_clean,
            "areas": [area_name] if area_name else ["Baltic"]
        }
    else:
        if area_name and area_name not in collected_warnings[key]["areas"]:
            collected_warnings[key]["areas"].append(area_name)


def scrape_baltic_warnings(output_filename="navareas/baltic/navarea_baltic_warnings.txt") -> dict:
    print("=" * 60)
    print("⚓ Sjöfartsverket Baltic Navigational Warnings Scraper")
    print("=" * 60)
    print(f"Fetching live bulletins from {URL}...")

    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    collected_warnings = {}

    page_text = ""
    if cffi_requests is None or BeautifulSoup is None:
        print("⛔ HTTP/HTML libraries not present in environment; aborting.")
        return None
    else:
        try:
            if HAS_CURL_CFFI:
                response = cffi_requests.get(URL, impersonate="chrome", timeout=30, verify=True)
            else:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                response = cffi_requests.get(URL, headers=headers, timeout=30, verify=True)

            if response.status_code != 200:
                print(f"⛔ Non-200 status code received ({response.status_code}); aborting.")
                return None
            else:
                page_text = response.content.decode("utf-8", errors="replace")
        except Exception as e:
            # Site unavailable or network timeout: loud failure, never a
            # silent outage-shaped empty harvest.
            print(f"⛔ Network error accessing {URL}: {e}")
            return None

    if page_text and BeautifulSoup is not None:
        soup = BeautifulSoup(page_text, "html.parser")

        # Fallback Strategy 1: Legacy DOM container
        warnings_container = soup.find(id="warnings_by_area")
        if warnings_container:
            area_divs = warnings_container.find_all("div", class_="nav-area-div")
            print(f"Legacy DOM detected: {len(area_divs)} area sections found.")
            for area_div in area_divs:
                h5 = area_div.find(["h5", "h4", "h3"])
                area_name = clean_text(h5.get_text()) if h5 else "Unknown"
                for p in area_div.find_all(["p", "div"]):
                    _harvest_paragraph(p, area_name, collected_warnings)

        # Fallback Strategy 2: Heading-based parsing across document
        if not collected_warnings:
            print("Trying heading-based fallback parsing...")
            area_name = "Unknown"
            for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "p", "div"]):
                if el.name in ("h1", "h2", "h3", "h4", "h5"):
                    heading_text = clean_text(el.get_text())
                    if heading_text and "warning" not in heading_text.lower():
                        area_name = heading_text
                    continue
                if el.name in ("p", "div"):
                    _harvest_paragraph(el, area_name, collected_warnings)

        # Fallback Strategy 3: General regex scan across all text blocks
        if not collected_warnings:
            print("Checking page text for NAV WARN markers...")
            for p in soup.find_all(["p", "article", "section", "li"]):
                _harvest_paragraph(p, "Baltic", collected_warnings)

    if not collected_warnings:
        # The page was fetched successfully and genuinely carries no warnings.
        # Write an empty file so the parser and sync engines can run and
        # cancel obsolete warnings.
        print("ℹ️ No active warnings found (valid empty harvest state).")
    else:
        print(f"✅ Harvested {len(collected_warnings)} warnings from feed.")

    # Write output file
    with open(output_filename, "w", encoding="utf-8") as f:
        for warn in collected_warnings.values():
            areas_str = ", ".join(warn["areas"])
            f.write(f"--- {warn['header']} [{areas_str}] ---\n")
            if warn["date_str"]:
                f.write(f"{warn['date_str']}\n")
            f.write(f"{warn['body']}\n\n")

    print(f"📁 Output saved: {output_filename} ({os.path.getsize(output_filename)} bytes)")
    return collected_warnings


if __name__ == "__main__":
    scrape_baltic_warnings()

