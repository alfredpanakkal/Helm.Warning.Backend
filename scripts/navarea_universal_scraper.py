#!/usr/bin/env python3
"""
scripts/navarea_universal_scraper.py — Generic feed scraper for the
universal-parser regions.

Fetches a VERIFIED plain-text endpoint (shared/feed_registry.py,
type='url_text', status='active'), saves it to the region's harvest
directory and runs the same universal parser + generic sync the manual
paste pipeline uses — one pipeline contract, whether the text arrived
by scrape or by admin paste.

Fail-closed by design:
  * No verified url_text feed for the region → clear error, no fetch.
  * Any network/HTTP error → non-zero exit, harvest untouched, sync
    never runs (never sync an empty or partial snapshot).
"""
import os
import sys
import urllib.error
import urllib.request

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared.feed_registry import FEEDS, get_text_feed

_TIMEOUT_S = 60


def scrape_region(region_key: str) -> str | None:
    """Fetches the region's verified plain-text feed. Returns the text
    or None (fail-closed; the error is printed without credentials)."""
    feed = get_text_feed(region_key)
    if feed is None:
        entry = FEEDS.get(region_key)
        if entry:
            print(f"ERROR: NAVAREA {region_key.upper()} feed is "
                  f"'{entry.get('status')}' / type '{entry.get('type')}' — "
                  f"not a verified plain-text endpoint. "
                  f"{entry.get('note', '')}")
        else:
            print(f"ERROR: no known publication feed for NAVAREA "
                  f"{region_key.upper()}.")
        return None
    url = feed["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "Helm.Warning/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"ERROR: fetch failed for NAVAREA {region_key.upper()} "
              f"({type(exc).__name__}); harvest untouched.")
        return None


def main(region_key: str) -> bool:
    text = scrape_region(region_key)
    if text is None or not text.strip():
        return False

    from scripts.navarea_universal_parser import main as parse_main
    from scripts.navarea_generic_sync import sync_to_supabase

    subdir = os.path.join("navareas", region_key)
    os.makedirs(subdir, exist_ok=True)
    raw_path = os.path.join(subdir, "latest_raw.txt")
    parsed_path = os.path.join(subdir, "parsed.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(text)

    if not parse_main(raw_path, parsed_path):
        return False

    return sync_to_supabase(parsed_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.navarea_universal_scraper <region_key>")
        sys.exit(2)
    sys.exit(0 if main(sys.argv[1].lower()) else 1)
