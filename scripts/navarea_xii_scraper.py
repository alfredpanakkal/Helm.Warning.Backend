#!/usr/bin/env python3
"""
navarea_xii_scraper.py — NGA NAVAREA XII Daily Memo Scraper

The NAVAREA XII coordinator (NGA) publishes the in-force list as a plain
text daily memorandum at msi.nga.mil. Unlike the JCG NAVAREA XI portal there
is no interactive display form, so this scraper is a direct, polite HTTP
harvest with retries and a curl_cffi browser-impersonation profile when
available. Segmentation of the memo happens later in the parser via
shared/navarea_xii_text.py; this module only fetches and persists the
verbatim memo (the scraper idempotency marker "IN FORCE AS OF" is logged).
"""

import sys
import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# HTTP libraries: prefer curl_cffi for TLS fingerprint impersonation,
# fall back to plain requests.
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

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

URL_DAILY_MEMO = "https://msi.nga.mil/apology_objects/DailyMemXII.txt"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
MEMO_MARKER = "NAVAREA XII IN FORCE AS OF"
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5.0


def _looks_like_memo(text: str) -> bool:
    """Sanity check that the payload is the NAVAREA XII daily memo."""
    if not text:
        return False
    return MEMO_MARKER in text and "NAVAREA XII " in text


def fetch_daily_memo(timeout=30) -> str:
    """Fetches the verbatim NAVAREA XII daily memo text.

    Returns the memo text, or an empty string on unrecoverable failure.
    """
    if cffi_requests is None:
        print("ℹ️ No HTTP library available (install curl_cffi or requests).")
        return ""

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://msi.nga.mil/",
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if HAS_CURL_CFFI:
                response = cffi_requests.get(
                    URL_DAILY_MEMO, headers=headers,
                    impersonate="chrome", timeout=timeout, verify=True
                )
            else:
                response = cffi_requests.get(
                    URL_DAILY_MEMO, headers=headers, timeout=timeout, verify=True
                )
            response.raise_for_status()
            text = response.text
            if not _looks_like_memo(text):
                raise ValueError("payload does not look like the NAVAREA XII daily memo")
            return text
        except Exception as e:
            last_err = e
            print(f"⚠️ Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                import time
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    print(f"❌ Could not fetch NAVAREA XII daily memo after {MAX_RETRIES} attempts: {last_err}")
    return ""


def scrape_xii_warnings(output_filename="navareas/navarea_xii/navarea_xii_warnings.txt") -> dict:
    print("=" * 60)
    print("⚓ NGA NAVAREA XII Daily Memo Scraper")
    print("=" * 60)

    memo_text = fetch_daily_memo()

    if not memo_text:
        print("ℹ️ No memo harvested from NGA MSI; writing valid empty harvest.")
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write("")
        return {}

    from shared.navarea_xii_text import get_in_force_dtg, split_into_warnings
    in_force = get_in_force_dtg(memo_text)
    blocks = split_into_warnings(memo_text)
    print(f"✅ Harvested memo (IN FORCE AS OF {in_force or 'unknown'}), "
          f"{len(blocks)} warning blocks detected.")
    print(f"Total warnings: {len(blocks)}")

    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(memo_text)
    print(f"✅ Wrote to {output_filename}")
    return {"in_force_dtg": in_force, "blocks": blocks}


if __name__ == "__main__":
    scrape_xii_warnings()
