#!/usr/bin/env python3
"""
navarea_xi_scraper.py — Japan Coast Guard NAVAREA XI Scraper
Harvests active navigational warnings from the Japan Coast Guard portal.
Three-tier acquisition strategy via curl_cffi with Chrome TLS fingerprint.
"""

import sys
import re
import urllib3
import xml.etree.ElementTree as ET
from datetime import datetime
from curl_cffi import requests as cffi_requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL_WARNINGS = "https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/warnings.cgi"
URL_DISP = "https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/disp_warnings.cgi"
URL_MIRROR = "https://www.sealagom.com/navarea/11/"
JCG_ENCODING = "cp932"

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
    print(f"Tier 1: Direct fetch of {URL_DISP} ...")
    response = cffi_requests.get(URL_DISP, impersonate="chrome", timeout=30, verify=False)
    response.raise_for_status()
    html_text = response.content.decode(JCG_ENCODING, errors="replace")
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</?STRONG>', '', html_text, flags=re.IGNORECASE)
    blocks = re.split(r'<hr\s*/?>', html_text, flags=re.IGNORECASE)
    return _collect_from_text_lines(blocks)

def fetch_two_step(year):
    print(f"Tier 2: Fetching XML bulletin list for year {year}...")
    response_xml = cffi_requests.post(
        URL_WARNINGS,
        data={'YEAR': str(year), 'TYPE': 'NAVAREA11', 'LANG': 'EG'},
        impersonate="chrome", timeout=30, verify=False
    )
    response_xml.raise_for_status()
    xml_text = response_xml.content.decode(JCG_ENCODING, errors="replace")
    xml_text = re.sub(r'^\s*<\?xml[^>]*\?>', '', xml_text.strip())
    root = ET.fromstring(xml_text)
    tanas = [member.find('tana').text for member in root.findall('Member') if member.find('tana') is not None]
    if not tanas:
        print("❓ No warnings found for the specified year on the JCG endpoint.")
        return {}
    print(f"Found {len(tanas)} active warnings. Fetching bulk HTML...")
    tana_str = ":".join(tanas) + ":"
    response_html = cffi_requests.post(
        URL_DISP,
        data={'TYPE': 'NAVAREA11', 'TANA': tana_str, 'LANG': 'EG'},
        impersonate="chrome", timeout=30, verify=False
    )
    response_html.raise_for_status()
    html_text = response_html.content.decode(JCG_ENCODING, errors="replace")
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</?STRONG>', '', html_text, flags=re.IGNORECASE)
    blocks = re.split(r'<hr\s*/?>', html_text, flags=re.IGNORECASE)
    return _collect_from_text_lines(blocks)

def fetch_from_mirror():
    print(f"Tier 3: Falling back to mirror: {URL_MIRROR}")
    response = cffi_requests.get(URL_MIRROR, impersonate="chrome", timeout=30)
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

def scrape_xi_warnings(output_filename="navarea_xi_warnings.txt", year=None):
    print("=" * 60)
    print("⚓ Japan Coast Guard NAVAREA XI Navigational Warnings Scraper")
    print("=" * 60)
    if year is None:
        year = datetime.now().year
    collected_warnings = {}
    try:
        collected_warnings = fetch_direct_disp()
        if collected_warnings:
            print("✅ Tier 1 (direct disp_warnings.cgi) succeeded.")
    except Exception as e:
        print(f"⚠️ Tier 1 (direct disp_warnings.cgi) unavailable: {e}")
    if not collected_warnings:
        try:
            collected_warnings = fetch_two_step(year)
            if collected_warnings:
                print("✅ Tier 2 (JCG two-step chain) succeeded.")
        except Exception as e:
            print(f"⚠️ Tier 2 (JCG two-step chain) unavailable: {e}")
    if not collected_warnings:
        try:
            collected_warnings = fetch_from_mirror()
            if collected_warnings:
                print("✅ Tier 3 (SeaLagom mirror) succeeded.")
        except Exception as e:
            print(f"❌ Tier 3 (SeaLagom mirror) also failed: {e}")

    if not collected_warnings:
        print("❌ Could not harvest any NAVAREA XI warnings from all 3 tiers.")
        sys.exit(1)

    _write_output(collected_warnings, output_filename)
    print(f"✅ Successfully written {len(collected_warnings)} NAVAREA XI warnings to '{output_filename}'.")
    return collected_warnings

if __name__ == "__main__":
    scrape_xi_warnings()
