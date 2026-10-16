#!/usr/bin/env python3
"""
NAVAREA I Scraper
Scrapes navigational warnings from UK Hydrographic Office (UKHO) Admiralty.
Source: https://msi.admiralty.co.uk/RadioNavigationalWarnings
Uses requests with session to maintain verification token validity.
"""

import sys
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from navareas.navarea_1.config import (
    SOURCE_URL, SHOW_SELECTION_URL, OUTPUT_WARNINGS_FILE, ENCODING
)

def scrape_navarea_1_warnings(output_filename=OUTPUT_WARNINGS_FILE):
    print("Setting up a persistent session to maintain verification token validity...")

    try:
        import requests
    except ImportError:
        print("Error: requests library is required. Install with: pip install requests")
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    session.verify = False

    print("Fetching the main Radio Navigation Warnings page...")

    try:
        response = session.get(SOURCE_URL, timeout=30)
        if response.status_code != 200:
            print(f"Error fetching main page, status code: {response.status_code}")
            return
    except Exception as e:
        print(f"Error fetching main page: {e}")
        return

    try:
        from scrapling.parser import Selector
    except ImportError:
        print("Error: scrapling library is required. Install with: pip install scrapling")
        sys.exit(1)

    page = Selector(response.text)

    print("Extracting verification token...")
    token = page.css('input[name="__RequestVerificationToken"]::attr(value)').get()

    if not token:
        print("Error: Could not find __RequestVerificationToken!")
        return

    print("Extracting warning IDs for NAVAREA I...")
    navarea_checkboxes = page.css('input.checkbox_warning[aria-label*="NAVAREA I"]')

    warning_ids = []
    for cb in navarea_checkboxes:
        w_id = cb.attrib.get('warning-id')
        if w_id:
            warning_ids.append(w_id)

    if not warning_ids:
        print("No NAVAREA I warnings found.")
        return

    print(f"Found {len(warning_ids)} NAVAREA I warnings. Submitting selection...")

    post_url = SHOW_SELECTION_URL
    payload = {
        "showSelectionId": ",".join(warning_ids),
        "__RequestVerificationToken": token
    }

    try:
        post_response = session.post(post_url, data=payload, timeout=30)
        if post_response.status_code != 200:
            print(f"Error submitting selection, status code: {post_response.status_code}")
            return
    except Exception as e:
        print(f"Error submitting selection: {e}")
        return

    print("Parsing the Show Selection page...")
    result_page = Selector(post_response.text)

    references = result_page.css('.warning-reference::text').getall()
    descriptions = result_page.css('.warning-description::text').getall()

    if not references and not descriptions:
        print("Warning: Could not find structured elements. Dumping raw text...")
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(result_page.css('body').get())
        print(f"Saved raw HTML to {output_filename}")
        return

    print(f"Successfully parsed {len(references)} warning details.")

    with open(output_filename, "w", encoding="utf-8") as f:
        for ref, desc in zip(references, descriptions):
            ref_clean = ref.strip()
            desc_clean = desc.strip()
            f.write(f"--- NAVAREA I {ref_clean} ---\n")
            f.write(f"{desc_clean}\n\n")

    print(f"Saved {len(references)} warnings to {output_filename}")

if __name__ == "__main__":
    scrape_navarea_1_warnings()
