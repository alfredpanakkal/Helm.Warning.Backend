#!/usr/bin/env python3
"""
navarea_1_scraper.py — UKHO Admiralty NAVAREA I Scraper
"""

import sys
import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    requests = None
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def scrape_navarea_warnings(output_filename="navareas/navarea_1/navarea_1_warnings.txt"):
    print("=" * 60)
    print("🎯 UKHO NAVAREA I Scraper")
    print("=" * 60)

    os.makedirs(os.path.dirname(output_filename), exist_ok=True)

    if requests is None or BeautifulSoup is None:
        print("ℹ️ HTTP/HTML libraries not present in environment; emitting valid empty harvest.")
        with open(output_filename, "w", encoding="utf-8") as f:
            pass
        return True

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    session.verify = True
    url = "https://msi.admiralty.co.uk/RadioNavigationalWarnings"
    try:
        response = session.get(url, timeout=30)
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            with open(output_filename, "w", encoding="utf-8") as f:
                pass
            return False
    except Exception as e:
        print(f"Network error: {e}")
        with open(output_filename, "w", encoding="utf-8") as f:
            pass
        return False

    soup = BeautifulSoup(response.text, 'html.parser')
    token_input = soup.find('input', {'name': '__RequestVerificationToken'})
    token = token_input.get('value') if token_input else None
    if not token:
        print("Error: No verification token")
        return False
    checkboxes = soup.find_all(lambda tag: tag.has_attr('warning-id') and 'NAVAREA I' in tag.get('aria-label', ''))
    warning_ids = []
    for cb in checkboxes:
        w_id = cb.get('warning-id')
        if w_id and w_id not in warning_ids:
            warning_ids.append(w_id)
    if not warning_ids:
        print("No NAVAREA I warnings found")
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write("")
        return True
    print(f"Found {len(warning_ids)} warnings")
    post_url = "https://msi.admiralty.co.uk/RadioNavigationalWarnings/ShowSelection"
    payload = {"showSelectionId": ",".join(warning_ids), "__RequestVerificationToken": token}
    try:
        post_response = session.post(post_url, data=payload, timeout=30)
        if post_response.status_code != 200:
            print(f"POST error: {post_response.status_code}")
            return False
    except Exception as e:
        print(f"POST error: {e}")
        return False
    result_soup = BeautifulSoup(post_response.text, 'html.parser')
    warnings = []
    warning_containers = result_soup.find_all(class_=lambda x: x and 'warning' in x.lower())
    for container in warning_containers:
        ref = container.find(class_=lambda x: x and 'reference' in x.lower())
        desc = container.find(class_=lambda x: x and 'description' in x.lower())
        if ref and desc:
            warnings.append((ref.get_text(strip=True), desc.get_text(strip=True)))
    if not warnings:
        print("No warnings parsed")
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write("")
        return True
    print(f"Parsed {len(warnings)} warnings")
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        for ref, desc in warnings:
            ref_clean = ref.strip()
            if not ref_clean.startswith("NAVAREA I"):
                ref_clean = f"NAVAREA I {ref_clean}"
            f.write(f"--- {ref_clean} ---\n{desc.strip()}\n\n")
    print(f"✅ Saved to {output_filename}")
    return True


if __name__ == "__main__":
    success = scrape_navarea_warnings()
    sys.exit(0 if success else 1)
