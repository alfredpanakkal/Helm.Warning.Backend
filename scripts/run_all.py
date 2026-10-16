#!/usr/bin/env python3
"""
run_all.py - Run All NAVAREA Pipelines
Runs all NAVAREA scraping pipelines sequentially.
Each pipeline runs independently with its own error handling.
"""

import sys
import os
import subprocess

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

PIPELINES = [
    ("NAVAREA Baltic", "run_baltic.py"),
    ("NAVAREA I", "run_navarea_1.py"),
    ("NAVAREA XI", "run_navarea_xi.py"),
]

def run_pipeline(name: str, script: str) -> bool:
    script_path = os.path.join(SCRIPTS_DIR, script)

    print("\n" + "=" * 65)
    print(f"Starting {name} Pipeline")
    print("=" * 65)

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=os.path.dirname(SCRIPTS_DIR),
            capture_output=False,
            text=True
        )

        if result.returncode == 0:
            print(f"\n\u2705 {name} pipeline completed successfully")
            return True
        else:
            print(f"\n\u274c {name} pipeline failed with exit code {result.returncode}")
            return False

    except Exception as e:
        print(f"\n\u274c Error running {name} pipeline: {e}")
        return False

def main():
    print("=" * 65)
    print("\u2693 STARTING ALL NAVAREA AUTOMATED INGESTION PIPELINES")
    print("=" * 65)

    results = {}

    for name, script in PIPELINES:
        results[name] = run_pipeline(name, script)

    print("\n" + "=" * 65)
    print("\ud83d\udcca ALL PIPELINES EXECUTION SUMMARY")
    print("=" * 65)

    for name, success in results.items():
        status = "\u2705 SUCCESS" if success else "\u274c FAILED"
        print(f"  {status}: {name}")

    if not all(results.values()):
        print("\n\u274c One or more pipelines failed")
        sys.exit(1)
    else:
        print("\n\ud83c\udf89 All pipelines completed successfully!")

if __name__ == "__main__":
    main()
