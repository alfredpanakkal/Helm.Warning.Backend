#!/usr/bin/env python3
"""
scripts/audit_navwarn_corpus.py — Audit Layer for NAVAREA Corpus Normalization and Metrics
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from hashlib import sha256
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

HEADER_PATTERNS = [
    re.compile(r"(?im)^\s*NAVAREA\s+[IVX]+\b"),
    re.compile(r"(?im)^\s*AUSCOAST\s+WARNING\b"),
    re.compile(r"(?im)^\s*NO\.\d{2}-\d{4}\s+Date:"),
]

def normalize_for_matching(text: str) -> str:
    """Normalizes Unicode text and standardizes dash variants."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ")
    return text.translate(str.maketrans({
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }))

def audit_file(path: Path) -> dict:
    """Reads and audits a single file path for NAVAREA header patterns and metrics."""
    if not path.exists():
        return {
            "source_file": path.name,
            "status": "FILE_NOT_FOUND",
            "counts": {"bytes": 0, "characters": 0, "recognized_headers": 0}
        }

    raw = path.read_bytes()
    text = normalize_for_matching(raw.decode("utf-8", errors="replace"))

    header_positions = sorted({
        match.start()
        for pattern in HEADER_PATTERNS
        for match in pattern.finditer(text)
    })

    counts = Counter({
        "bytes": len(raw),
        "characters": len(text),
        "recognized_headers": len(header_positions),
    })

    return {
        "source_file": path.name,
        "sha256": sha256(raw).hexdigest(),
        "counts": dict(counts),
        "recognized_header_offsets": header_positions,
        "status": "AUDIT_ONLY",
    }

def main():
    parser = argparse.ArgumentParser(description="NAVAREA Corpus Audit Utility")
    parser.add_argument("--input", required=True, help="Input file path to audit")
    parser.add_argument("--output", default="build/corpus-audit.json", help="Output JSON report path")
    args = parser.parse_args()

    input_path = Path(args.input)
    report = audit_file(input_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["counts"], indent=2))
    print(f"Audit report successfully written to {output_path}")

if __name__ == "__main__":
    main()
