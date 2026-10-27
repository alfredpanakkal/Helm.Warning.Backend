#!/usr/bin/env python3
"""run_navarea_v.py — NAVAREA V Pipeline Runner (scrape -> parse -> sync)."""
import sys
import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> bool:
    print("=" * 65)
    print("NAVAREA V PIPELINE")
    print("=" * 65)

    from scripts.navarea_v_scraper import main as scrape_main
    ok = scrape_main()
    if not ok:
        # Fail-closed observability: never publish an empty result and
        # never report a fake 'healthy' state. The harvest is untouched
        # — the orchestrator shows NAVAREA V as BLOCKED, not stale.
        print("=" * 65)
        print("🚫 NAVAREA V BLOCKED — manual import needed")
        print("=" * 65)
        print("The scheduled scrape could not bypass the Cloudflare wall")
        print("(or the snapshot carried zero usable records). Nothing was")
        print("published; the feed is NOT silently stale — it is blocked.")
        print("Manual import (~1 min):")
        print("  1. Open the CHM page in your own browser (Cloudflare")
        print("     lets humans through):")
        print("     https://www.marinha.mil.br/chm/dados-do-segnav-avviso-radio-nautico-tela/avisos-radio-nauticos-e-sar")
        print("  2. Copy the raw avradio_NN.json contents (file link on the page).")
        print("  3. Paste via the manual ingest queue (region 'v') — it goes")
        print("     through the same filter, parser, validation and")
        print("     Verification Queue as the scheduled scrape.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
