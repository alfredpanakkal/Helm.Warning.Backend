#!/usr/bin/env python3
"""run_all.py — Master Pipeline for All NAVAREA Regions with Pre-Flight Checks & Logging"""
import sys
import os
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from shared.config import AppConfig
from shared.logging import setup_logging, get_logger
from shared.metrics import metrics
from shared.cache import initialize_cache

def main() -> int:
    # 1. Pre-flight configuration validation
    config = AppConfig.from_env()
    if not config.validate(require_db=False):
        print("❌ Fatal: Invalid configuration detected. Aborting startup.", file=sys.stderr)
        return 1

    # 2. Setup application logging & cache
    setup_logging(level=config.log_level, log_file=config.log_file, json_format=True)
    logger = get_logger("master_pipeline")
    logger.info("Initializing master pipeline execution", extra={"mode": config.feed_policy.mode})
    initialize_cache(redis_host=config.redis_host, redis_port=config.redis_port)

    print("=" * 70)
    print("🌍 NAVAREA GLOBAL INGESTION MASTER PIPELINE")
    print("=" * 70)
    print(f"⚙️ Feed Policy: {config.feed_policy.mode.upper()}")
    print(f"📊 Log Level  : {config.log_level}")
    print("=" * 70)

    all_success = True
    # Per-region outcome for the final REGION STATUS SUMMARY — a
    # blocked region must be VISIBLE (fail-closed observability),
    # never a fake 'healthy' state and never a silently stale feed.
    region_status = {}
    start_total = time.time()

    print("\n" + "=" * 70)
    print("🚀 NAVAREA BALTIC")
    print("=" * 70)
    try:
        from scripts.run_baltic import main as run_baltic
        res = run_baltic()
        if res is False:
            all_success = False
            region_status["Baltic"] = "failed"
        else:
            region_status["Baltic"] = "ok"
    except Exception as e:
        logger.error(f"Baltic pipeline failed: {e}", exc_info=True)
        region_status["Baltic"] = "failed"
        print(f"❌ Baltic failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA I")
    print("=" * 70)
    try:
        from scripts.run_navarea_1 import main as run_nav1
        res = run_nav1()
        if res is False:
            all_success = False
            region_status["NAVAREA I"] = "failed"
        else:
            region_status["NAVAREA I"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA I pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA I"] = "failed"
        print(f"❌ NAVAREA I failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA XI")
    print("=" * 70)
    try:
        from scripts.run_navarea_xi import main as run_xi
        res = run_xi()
        if res is False:
            all_success = False
            region_status["NAVAREA XI"] = "failed"
        else:
            region_status["NAVAREA XI"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA XI pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA XI"] = "failed"
        print(f"❌ NAVAREA XI failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA XII (NGA DAILY MEMO)")
    print("=" * 70)
    try:
        from scripts.run_navarea_xii import main as run_xii
        res = run_xii()
        if res is False:
            all_success = False
            region_status["NAVAREA XII"] = "failed"
        else:
            region_status["NAVAREA XII"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA XII pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA XII"] = "failed"
        print(f"❌ NAVAREA XII failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA IV (NGA DAILY MEMO)")
    print("=" * 70)
    try:
        from scripts.run_navarea_iv import main as run_iv
        res = run_iv()
        if res is False:
            all_success = False
            region_status["NAVAREA IV"] = "failed"
        else:
            region_status["NAVAREA IV"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA IV pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA IV"] = "failed"
        print(f"❌ NAVAREA IV failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA II (S-124 SECOM)")
    print("=" * 70)
    try:
        print("[*] Running NAVAREA II S-124 sync...")
        from scrapers.navarea_ii import run_navarea_ii_pipeline
        run_navarea_ii_pipeline()
        region_status["NAVAREA II"] = "ok"
    except Exception as e:
        print(f"[!] NAVAREA II sync failed: {e}")
        all_success = False
        region_status["NAVAREA II"] = "failed"

    print("\n" + "=" * 70)
    print("🚀 NAVAREA III (SPAIN IHM XML)")
    print("=" * 70)
    try:
        from scripts.run_navarea_iii import main as run_iii
        res = run_iii()
        if res is False:
            all_success = False
            region_status["NAVAREA III"] = "failed"
        else:
            region_status["NAVAREA III"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA III pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA III"] = "failed"
        print(f"❌ NAVAREA III failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA V (BRAZIL CHM JSON)")
    print("=" * 70)
    try:
        from scripts.run_navarea_v import main as run_v
        res = run_v()
        if res is False:
            all_success = False
            region_status["NAVAREA V"] = "failed"
        else:
            region_status["NAVAREA V"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA V pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA V"] = "failed"
        print(f"❌ NAVAREA V failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA VII (SOUTH AFRICA SANHO HTML)")
    print("=" * 70)
    try:
        from scripts.run_navarea_vii import main as run_vii
        res = run_vii()
        if res is False:
            all_success = False
    except Exception as e:
        logger.error(f"NAVAREA VII pipeline failed: {e}", exc_info=True)
        print(f"❌ NAVAREA VII failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA VIII (NHO INDIA IN-FORCE BULLETIN)")
    print("=" * 70)
    try:
        from scripts.run_navarea_8 import main as run_viii
        res = run_viii()
        if res is False:
            all_success = False
            region_status["NAVAREA VIII"] = "failed"
        else:
            region_status["NAVAREA VIII"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA VIII pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA VIII"] = "failed"
        print(f"❌ NAVAREA VIII failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA X (AUSTRALIA AMSA RCC MSI)")
    print("=" * 70)
    try:
        from scripts.run_navarea_x import main as run_x
        res = run_x()
        if res is False:
            all_success = False
    except Exception as e:
        logger.error(f"NAVAREA X pipeline failed: {e}", exc_info=True)
        print(f"❌ NAVAREA X failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA IX (PAKISTAN NHO HTML TABLE)")
    print("=" * 70)
    try:
        from scripts.run_navarea_ix import main as run_ix
        res = run_ix()
        if res is False:
            all_success = False
            region_status["NAVAREA IX"] = "failed"
        else:
            region_status["NAVAREA IX"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA IX pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA IX"] = "failed"
        print(f"❌ NAVAREA IX failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA XIX (NORWAY KYSTVERKET HTML TABLE)")
    print("=" * 70)
    try:
        from scripts.run_navarea_xix import main as run_xix
        res = run_xix()
        if res is False:
            all_success = False
            region_status["NAVAREA XIX"] = "failed"
        else:
            region_status["NAVAREA XIX"] = "ok"
    except Exception as e:
        logger.error(f"NAVAREA XIX pipeline failed: {e}", exc_info=True)
        region_status["NAVAREA XIX"] = "failed"
        print(f"❌ NAVAREA XIX failed: {e}")
        all_success = False


    print("\n" + "=" * 70)
    print("🚀 NORWEGIAN COASTAL WARNINGS (KYSTVERKET HTML TABLE)")
    print("=" * 70)
    try:
        from scripts.run_kystverket_coastal import main as run_coastal_no
        res = run_coastal_no()
        if res is False:
            all_success = False
            region_status["Coastal NO"] = "failed"
        else:
            region_status["Coastal NO"] = "ok"
    except Exception as e:
        logger.error(f"Coastal NO pipeline failed: {e}", exc_info=True)
        region_status["Coastal NO"] = "failed"
        print(f"❌ Coastal NO failed: {e}")
        all_success = False

    total_duration = time.time() - start_total

    # Fail-closed observability: a blocked region must be VISIBLE in the
    # orchestrator output — never a fake 'healthy' state, never a
    # silently stale feed. Blocked regions need a manual import.
    print("\n" + "=" * 70)
    print("📋 REGION STATUS SUMMARY")
    print("=" * 70)
    for region, status in region_status.items():
        if status == "ok":
            print(f"✅ {region} OK")
        elif region == "NAVAREA V":
            print(f"🚫 {region} BLOCKED — manual import needed: open the "
                  f"CHM page in a browser, copy the avradio_NN.json "
                  f"contents and paste via the manual ingest queue "
                  f"(same filter/parser/validation as the scrape)")
        else:
            print(f"🚫 {region} BLOCKED — manual import needed")
    print("=" * 70)

    print("\n" + "=" * 70)
    if all_success:
        print(f"🎉 ALL PIPELINES COMPLETED SUCCESSFULLY in {total_duration:.2f}s")
    else:
        print(f"❌ SOME PIPELINES FAILED in {total_duration:.2f}s")
    print("=" * 70)

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
