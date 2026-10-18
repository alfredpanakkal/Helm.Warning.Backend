#!/usr/bin/env python3
"""
baltic_scraper.py — Sjöfartsverket VHF Navigational Warnings Scraper
Harvests active Swedish and Baltic Sea navigational warnings from the Swedish Maritime Administration portal:
https://navvarn.sjofartsverket.se/en/Navigationsvarningar/VHF
"""

import sys
import re
import html
import urllib3
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://navvarn.sjofartsverket.se/en/Navigationsvarningar/VHF"

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\xa0', ' ')
    return text.strip()

def _extract_area_name(el) -> str:
    return clean_text(el.get_text()) if el else "Unknown Area"

def _harvest_paragraph(p, area_name, collected_warnings):
    p_text = clean_text(p.get_text())
    if not p_text or "No current warnings in the area" in p_text:
        return

    b_tag = p.find("b")
    if not b_tag:
        return

    header_raw = clean_text(b_tag.get_text())
    header_clean = " ".join(header_raw.split())

    date_match = re.search(r'(\d{6}\s+UTC\s+[A-Z]{3})', p.text)
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
            "areas": [area_name]
        }
    else:
        if area_name not in collected_warnings[key]["areas"]:
            collected_warnings[key]["areas"].append(area_name)

def scrape_baltic_warnings(output_filename="navarea_baltic_warnings.txt"):
    print("=" * 60)
    print("⚓ Sjofartsverket Baltic Navigational Warnings Scraper")
    print("=" * 60)
    print(f"Fetching live bulletins from {URL}...")

    try:
        response = cffi_requests.get(URL, impersonate="chrome", timeout=30, verify=False)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Network error while fetching {URL}: {e}")
        sys.exit(1)

    page_text = response.content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(page_text, "html.parser")
    collected_warnings = {}

    warnings_container = soup.find(id="warnings_by_area")
    if warnings_container:
        area_divs = warnings_container.find_all("div", class_="nav-area-div")
        print(f"Legacy DOM found. Located {len(area_divs)} navigational area sections.")
        for area_div in area_divs:
            h5 = area_div.find("h5")
            area_name = _extract_area_name(h5)
            for p in area_div.find_all("p"):
                _harvest_paragraph(p, area_name, collected_warnings)

    if not collected_warnings:
        print("Legacy container not found; using heading-based parsing...")
        area_name = "Unknown Area"
        for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "p"]):
            if el.name in ("h1", "h2", "h3", "h4", "h5"):
                heading_text = _extract_area_name(el)
                if heading_text and "warning" not in heading_text.lower():
                    area_name = heading_text
                continue
            _harvest_paragraph(el, area_name, collected_warnings)

    if not collected_warnings:
        print("❌ Could not extract any warnings from the Sjofartsverket page.")
        sys.exit(1)

    print(f"Total unique warnings extracted: {len(collected_warnings)}")

    with open(output_filename, "w", encoding="utf-8") as f:
        for warn in collected_warnings.values():
            areas_str = ", ".join(warn["areas"])
            f.write(f"--- {warn['header']} [{areas_str}] ---\n")
            if warn["date_str"]:
                f.write(f"{warn['date_str']}\n")
            f.write(f"{warn['body']}\n\n")

    print(f"✅ Successfully wrote {len(collected_warnings)} warnings to '{output_filename}'.")
    return collected_warnings

if __name__ == "__main__":
    scrape_baltic_warnings()
