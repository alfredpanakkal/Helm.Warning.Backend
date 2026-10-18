#!/usr/bin/env python3
"""run_all.py — Master Pipeline for All NAVAREA Regions"""
import sys
import os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
print("=" * 70)
print("🌍 NAVAREA GLOBAL INGESTION MASTER PIPELINE")
print("=" * 70)
all_success = True
print("\n" + "=" * 70)
print("🚀 NAVAREA BALTIC")
print("=" * 70)
try:
    from scripts.run_baltic import main as run_baltic
    run_baltic()
except Exception as e:
    print(f"❌ Baltic failed: {e}")
    all_success = False
print("\n" + "=" * 70)
print("🚀 NAVAREA I")
print("=" * 70)
try:
    from scripts.run_navarea_1 import main as run_nav1
    run_nav1()
except Exception as e:
    print(f"❌ NAVAREA I failed: {e}")
    all_success = False
print("\n" + "=" * 70)
print("🚀 NAVAREA XI")
print("=" * 70)
try:
    from scripts.run_navarea_xi import main as run_xi
    run_xi()
except Exception as e:
    print(f"❌ NAVAREA XI failed: {e}")
    all_success = False
print("\n" + "=" * 70)
if all_success:
    print("🎉 ALL PIPELINES COMPLETED SUCCESSFULLY")
else:
    print("❌ SOME PIPELINES FAILED")
print("=" * 70)
sys.exit(0 if all_success else 1)
