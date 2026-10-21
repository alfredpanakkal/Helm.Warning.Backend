#!/usr/bin/env python3
"""
navarea_xii_scraper.py — NGA NAVAREA XII Daily Memo Scraper

Fetches the plain-text daily memo (in-force warnings) from msi.nga.mil.

Idempotency: the memo's "IN FORCE AS OF" DTG plus a SHA-256 checksum of the
raw text are persisted in state.json. A re-run against an unchanged memo is a
no-op; a changed memo (new DTG or edited content) triggers a fresh write.
The raw memo is stored VERBATIM (no rejoin/normalization) — all text
normalization happens in the parser, so AI-fallback grounding always has the
pristine source available.
"""

import sys
import os
import json
import hashlib
from datetime import datetime, timezone

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

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from shared.navarea_xii_text import get_in_force_dtg

URL = "https://msi.nga.mil/apology_objects/DailyMemXII.txt"
OUT_DIR = "navareas/navarea_xii"
MEMO_FILE = os.path.join(OUT_DIR, "navarea_xii_memo.txt")
STATE_FILE = os.path.join(OUT_DIR, "state.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/plain,*/*",
}


def fetch_memo(timeout: int = 30) -> str:
    """Fetch the raw daily memo text. Returns '' on failure (fail-closed)."""
    if cffi_requests is None:
        print("⚠️ No HTTP library available (curl_cffi/requests); cannot fetch.")
        return ""
    try:
        resp = cffi_requests.get(URL, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text or ""
    except Exception as e:
        print(f"⚠️ Failed to fetch daily memo: {e}")
        return ""


def compute_state(memo_text: str) -> dict:
    """Idempotency state: IN FORCE DTG + SHA-256 of the verbatim raw text."""
    return {
        "in_force_dtg": get_in_force_dtg(memo_text),
        "memo_sha256": hashlib.sha256((memo_text or "").encode("utf-8")).hexdigest(),
    }


def should_process(memo_text: str, state) -> bool:
    """True when there is no prior state, or the memo content changed."""
    if not memo_text:
        return False
    if not state:
        return True
    return compute_state(memo_text).get("memo_sha256") != state.get("memo_sha256")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Could not read state file ({e}); treating as no prior state.")
    return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state["fetched_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def main() -> bool:
    print("=" * 60)
    print("🧭 NAVAREA XII Scraper — NGA Daily Memo")
    print("=" * 60)
    state = load_state()
    memo_text = fetch_memo()
    if not memo_text:
        print("ℹ️ No memo content fetched; keeping existing harvest.")
        return True  # empty harvest is valid; parser treats missing input as empty

    if not should_process(memo_text, state):
        print(f"✅ Memo unchanged since last run (DTG: {state.get('in_force_dtg')}); no-op.")
        return True

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MEMO_FILE, "w", encoding="utf-8") as f:
        f.write(memo_text)
    new_state = compute_state(memo_text)
    save_state(new_state)
    print(f"✅ Memo saved ({len(memo_text)} chars, DTG: {new_state.get('in_force_dtg')}).")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
