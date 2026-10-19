#!/usr/bin/env python3
"""
scripts/run_all_async.py — Concurrent Async Master Pipeline for All NAVAREA Regions
Features pre-flight configuration validation, concurrent scraping/parsing/sync, metrics export,
and automated triage escalation.
"""

import asyncio
import json
import os
import sys
import os
import time
from typing import Any, Dict

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
from shared.prometheus import PrometheusServer
from shared.cache import initialize_cache

logger = get_logger("async_pipeline")


async def run_region_pipeline(name: str, run_fn) -> Dict[str, Any]:
    """Runs a regional pipeline in a non-blocking background thread."""
    loop = asyncio.get_running_loop()
    start_t = loop.time()
    try:
        logger.info(f"Starting async pipeline for {name}...")
        success = await loop.run_in_executor(None, run_fn)
        duration = loop.time() - start_t
        logger.info(f"Finished {name} pipeline in {duration:.2f}s (success={success})")
        return {"region": name, "success": bool(success), "duration_seconds": duration, "error": None}
    except Exception as e:
        duration = loop.time() - start_t
        logger.error(f"Failed {name} pipeline in {duration:.2f}s: {e}", exc_info=True)
        return {"region": name, "success": False, "duration_seconds": duration, "error": str(e)}


async def main_async() -> int:
    config = AppConfig.from_env()

    # Pre-flight Configuration Validation
    valid_config = config.validate(require_db=False)
    if not valid_config:
        print("❌ Configuration pre-flight validation failed. Check logs for details.", file=sys.stderr)
        return 1

    # Setup Logging
    setup_logging(level=config.log_level, log_file=config.log_file, json_format=True)
    logger.info("Configuration validated successfully", extra={"log_level": config.log_level, "mode": config.feed_policy.mode})

    # Initialize Cache & Optional Prometheus Exporter
    initialize_cache(redis_host=config.redis_host, redis_port=config.redis_port)
    prom_server = PrometheusServer(port=config.prometheus_port)
    prom_server.start()

    print("=" * 70)
    print("🌍 NAVAREA CONCURRENT ASYNC INGESTION MASTER PIPELINE")
    print("=" * 70)

    # Safe imports of regional runners
    try:
        from scripts.run_baltic import main as run_baltic
    except ImportError as e:
        err_baltic = str(e)
        def run_baltic():
            logger.error(f"Cannot run Baltic pipeline: {err_baltic}")
            return False

    try:
        from scripts.run_navarea_1 import main as run_nav1
    except ImportError as e:
        err_nav1 = str(e)
        def run_nav1():
            logger.error(f"Cannot run NAVAREA I pipeline: {err_nav1}")
            return False

    try:
        from scripts.run_navarea_xi import main as run_xi
    except ImportError as e:
        err_xi = str(e)
        def run_xi():
            logger.error(f"Cannot run NAVAREA XI pipeline: {err_xi}")
            return False

    start_total = time.time()

    # Concurrent regional tasks
    tasks = [
        run_region_pipeline("Baltic", run_baltic),
        run_region_pipeline("NAVAREA I", run_nav1),
        run_region_pipeline("NAVAREA XI", run_xi),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)
    total_duration = time.time() - start_total

    print("\n" + "=" * 70)
    print("📊 INGESTION PIPELINE EXECUTION SUMMARY")
    print("=" * 70)
    all_success = True
    for res in results:
        status_icon = "✅" if res["success"] else "❌"
        print(f" {status_icon} {res['region']:<15} : {res['duration_seconds']:.2f}s (Error: {res['error'] or 'None'})")
        if not res["success"]:
            all_success = False

    print("-" * 70)
    print(f"⏱️ Total Execution Time : {total_duration:.2f} seconds")
    print(f"📈 Total Metrics Collected: {len(metrics.to_dict().get('counters', {}))} counters")
    print("=" * 70)

    prom_server.stop()
    return 0 if all_success else 1


def main():
    try:
        exit_code = asyncio.run(main_async())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
