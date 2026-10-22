#!/usr/bin/env python3
"""run_all.py — Master Pipeline for All NAVAREA Regions with Pre-Flight Checks & Logging"""
import sys
import os
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

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
    start_total = time.time()

    print("\n" + "=" * 70)
    print("🚀 NAVAREA BALTIC")
    print("=" * 70)
    try:
        from scripts.run_baltic import main as run_baltic
        res = run_baltic()
        if res is False:
            all_success = False
    except Exception as e:
        logger.error(f"Baltic pipeline failed: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"NAVAREA I pipeline failed: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"NAVAREA XI pipeline failed: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"NAVAREA XII pipeline failed: {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"NAVAREA IV pipeline failed: {e}", exc_info=True)
        print(f"❌ NAVAREA IV failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA II (S-124 SECOM)")
    print("=" * 70)
    try:
        print("[*] Running NAVAREA II S-124 sync...")
        from scrapers.navarea_ii import run_navarea_ii_pipeline
        run_navarea_ii_pipeline()
    except Exception as e:
        print(f"[!] NAVAREA II sync failed: {e}")
        all_success = False

    print("\n" + "=" * 70)
    print("🚀 NAVAREA VIII (NHO INDIA IN-FORCE BULLETIN)")
    print("=" * 70)
    try:
        from scripts.run_navarea_8 import main as run_viii
        res = run_viii()
        if res is False:
            all_success = False
    except Exception as e:
        logger.error(f"NAVAREA VIII pipeline failed: {e}", exc_info=True)
        print(f"❌ NAVAREA VIII failed: {e}")
        all_success = False

    total_duration = time.time() - start_total
    print("\n" + "=" * 70)
    if all_success:
        print(f"🎉 ALL PIPELINES COMPLETED SUCCESSFULLY in {total_duration:.2f}s")
    else:
        print(f"❌ SOME PIPELINES FAILED in {total_duration:.2f}s")
    print("=" * 70)

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
