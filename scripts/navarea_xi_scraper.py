#!/usr/bin/env python3
"""
navarea_xi_scraper.py — Japan Coast Guard NAVAREA XI Scraper
"""

import sys
import os
import re
from datetime import datetime
from curl_cffi import requests as cffi_requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

URL_DISP = "https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/disp_warnings.cgi"
URL_MIRROR = "https://www.sealagom.com/navarea/11/"
JCG_ENCODING = "cp932"


def _collect_from_text_lines(blocks):
    collected = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        block = re.sub(r'<.*?>', '', block)
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        id_match = re.search(r'(NO\.\d{2}-\d{4})', lines[0])
        if not id_match:
            continue
        wid = id_match.group(1)
        header = f"NAVAREA XI {wid}"
        body = "\n".join(lines[1:]).strip()
        collected[header] = {"header": header, "date_line": lines[0], "body": body}
    return collected


def _write_output(collected, output_filename):
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        for warn in collected.values():
            f.write(f"--- {warn['header']} ---\n{warn['date_line']}\n{warn['body']}\n\n")


def fetch_direct_disp():
    print("Tier 1: Direct fetch...")
    response = cffi_requests.get(URL_DISP, impersonate="chrome", timeout=30, verify=True)
    response.raise_for_status()
    html = response.content.decode(JCG_ENCODING, errors="replace")
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</?STRONG>', '', html, flags=re.IGNORECASE)
    blocks = re.split(r'<hr\s*/?>', html, flags=re.IGNORECASE)
    return _collect_from_text_lines(blocks)


def fetch_from_mirror():
    print("Tier 3: Mirror fallback...")
    response = cffi_requests.get(URL_MIRROR, impersonate="chrome", timeout=30)
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="replace")
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    parts = re.split(r'(?=NO\.\d{2}-\d{4}\s+Date:)', text)
    blocks = []
    for part in parts:
        m = re.match(r'(NO\.\d{2}-\d{4})\s+(Date:[^\n]*)', part.strip())
        if not m:
            continue
        blocks.append(f"{m.group(1)}       {m.group(2).strip()}\n{part.strip()[m.end(2):].strip()}")
    return _collect_from_text_lines(blocks)


def scrape_xi_warnings(output_filename="navareas/navarea_xi/navarea_xi_warnings.txt", year=None):
    print("=" * 60)
    print("⚓ Japan Coast Guard NAVAREA XI Scraper")
    print("=" * 60)
    if year is None:
        year = datetime.now().year
    collected = {}
    try:
        collected = fetch_direct_disp()
        if collected:
            print("✅ Tier 1 succeeded")
    except Exception as e:
        print(f"⚠️ Tier 1 failed: {e}")
    if not collected:
        try:
            collected = fetch_from_mirror()
            if collected:
                print("✅ Tier 3 succeeded")
        except Exception as e:
            print(f"❌ Mirror failed: {e}")
    if not collected:
        print("❌ All sources failed")
        sys.exit(1)
    print(f"Total warnings: {len(collected)}")
    _write_output(collected, output_filename)
    print(f"✅ Wrote to {output_filename}")
    return collected


if __name__ == "__main__":
    scrape_xi_warnings()
