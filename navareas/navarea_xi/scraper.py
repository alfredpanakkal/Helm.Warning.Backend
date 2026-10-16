#!/usr/bin/env python3
"""
NAVAREA XI Scraper
Harvests active navigational warnings from the Japan Coast Guard portal.
Three-tier acquisition strategy via curl_cffi with Chrome TLS fingerprint.
"""

import sys
import re
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from shared.utils import clean_text
from navareas.navarea_xi.config import (
    SOURCE_URLS, OUTPUT_WARNINGS_FILE, ENCODING, TIMEOUT
)

def _collect_from_text_lines(blocks):
    collected_warnings = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        block = re.sub(r'<.*?>', '', block)
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue
        header_line = lines[0]
        id_match = re.search(r'(NO\.\d{2}-\d{4})', header_line)
        if not id_match:
            continue
        warning_id_raw = id_match.group(1)
        header_clean = f"NAVAREA XI {warning_id_raw}"
        body_text = "\n".join(lines[1:]).strip()
        key = header_clean
        if key not in collected_warnings:
            collected_warnings[key] = {
                "header": header_clean,
                "date_line": header_line,
                "body": body_text
            }
    return collected_warnings

def _write_output(collected_warnings, output_filename):
    with open(output_filename, "w", encoding="utf-8") as f:
        for warn in collected_warnings.values():
            f.write(f"--- {warn['header']} ---\n")
            f.write(f"{warn['date_line']}\n")
            f.write(f"{warn['body']}\n\n")

def fetch_direct_disp():
    print(f"Tier 1: Direct fetch of {SOURCE_URLS['direct']} ...")
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("Error: curl_cffi is required. Install with: pip install curl_cffi")
        sys.exit(1)
    response = cffi_requests.get(
        SOURCE_URLS['direct'],
        impersonate="chrome",
        timeout=TIMEOUT,
        verify=False
    )
    response.raise_for_status()
    html_text = response.content.decode(ENCODING, errors="replace")
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</?STRONG>', '', html_text, flags=re.IGNORECASE)
    blocks = re.split(r'<hr\s*/?>', html_text, flags=re.IGNORECASE)
    return _collect_from_text_lines(blocks)

def fetch_two_step(year):
    print(f"Tier 2: Fetching XML bulletin list for year {year}...")
    try:
        from curl_cffi import requests as cffi_requests
        import xml.etree.ElementTree as ET
    except ImportError as e:
        print(f"Error: Required library missing: {e}")
        sys.exit(1)
    response_xml = cffi_requests.post(
        SOURCE_URLS['warnings'],
        data={'YEAR': str(year), 'TYPE': 'NAVAREA11', 'LANG': 'EG'},
        impersonate="chrome",
        timeout=TIMEOUT,
        verify=False
    )
    response_xml.raise_for_status()
    xml_text = response_xml.content.decode(ENCODING, errors="replace")
    xml_text = re.sub(r'^\\s*<\\?xml[^>]*\\?>', '', xml_text.strip())
    root = ET.fromstring(xml_text)
    tanas = [member.find('tana').text for member in root.findall('Member') if member.find('tana') is not None]
    if not tanas:
        print("\u2139\ufe0f No warnings found for the specified year on the JCG endpoint.")
        return {}
    print(f"Found {len(tanas)} active warnings. Fetching bulk HTML...")
    tana_str = ":".join(tanas) + ":"
    response_html = cffi_requests.post(
        SOURCE_URLS['direct'],
        data={'TYPE': 'NAVAREA11', 'TANA': tana_str, 'LANG': 'EG'},
        impersonate="chrome",
        timeout=TIMEOUT,
        verify=False
    )
    response_html.raise_for_status()
    html_text = response_html.content.decode(ENCODING, errors="replace")
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</?STRONG>', '', html_text, flags=re.IGNORECASE)
    blocks = re.split(r'<hr\s*/?>', html_text, flags=re.IGNORECASE)
    return _collect_from_text_lines(blocks)

def fetch_from_mirror():
    print(f"Tier 3: Falling back to mirror: {SOURCE_URLS['mirror']}")
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("Error: curl_cffi is required. Install with: pip install curl_cffi")
        sys.exit(1)
    response = cffi_requests.get(
        SOURCE_URLS['mirror'],
        impersonate="chrome",
        timeout=TIMEOUT
    )
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="replace")
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#39;', "'", text)
    parts = re.split(r'(?=NO\.\d{2}-\d{4}\s+Date:)', text)
    blocks = []
    for part in parts:
        m = re.match(r'(NO\.\d{2}-\d{4})\s+(Date:[^\n]*)', part.strip())
        if not m:
            continue
        header_line = f"{m.group(1)}       {m.group(2).strip()}"
        body = part.strip()[m.end(2):].strip()
        blocks.append(header_line + "\n" + body)
    return _collect_from_text_lines(blocks)

def scrape_xi_warnings(output_filename=OUTPUT_WARNINGS_FILE, year=None):
    print("=" * 60)
    print("\u2693 Japan Coast Guard NAVAREA XI Navigational Warnings Scraper")
    print("=" * 60)

    if year is None:
        year = datetime.now().year

    collected_warnings = {}

    try:
        collected_warnings = fetch_direct_disp()
        if collected_warnings:
            print("\u2705 Tier 1 (direct disp_warnings.cgi) succeeded.")
    except Exception as e:
        print(f"\u26a0\ufe0f Tier 1 (direct disp_warnings.cgi) unavailable: {e}")

    if not collected_warnings:
        try:
            collected_warnings = fetch_two_step(year)
            if collected_warnings:
                print("\u2705 Tier 2 (JCG two-step chain) succeeded.")
        except Exception as e:
            print(f"\u26a0\ufe0f Tier 2 (JCG two-step chain) unavailable: {e}")

    if not collected_warnings:
        try:
            collected_warnings = fetch_from_mirror()
            if collected_warnings:
                print("\u2705 Tier 3 (SeaLagom mirror) succeeded.")
        except Exception as e:
            print(f"\u274c Mirror also unavailable: {e}")

    if not collected_warnings:
        print("\u274c All sources failed: could not retrieve NAVAREA XI warnings.")
        sys.exit(1)

    print(f"Total unique warnings extracted: {len(collected_warnings)}")
    _write_output(collected_warnings, output_filename)
    print(f"\u2705 Successfully wrote {len(collected_warnings)} warnings to '{output_filename}'.")
    return collected_warnings

if __name__ == "__main__":
    scrape_xi_warnings()
