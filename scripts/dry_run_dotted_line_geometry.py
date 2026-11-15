#!/usr/bin/env python3
"""Read-only dry run of the dotted-line geometry parser against live raw text.

This script SELECTs three known warnings, reparses their stored raw_text with
the current deterministic NAVAREA parser, and writes a local JSON report.
It never updates Supabase, creates proposals, calls an AI model, or changes
publication tier/status.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Dict, List

from scripts import navarea_universal_parser
from shared.models import build_master_payload


TARGETS = {
    "NAVAREA III 0169/26": {
        "region": "iii",
        "number": "0169",
        "year": "26",
        "expected_types": ["LineString", "LineString"],
        "expected_labels": ["A", "B"],
        "expected_coordinate_counts": [7, 22],
        "expected_tier": "B",
        "requires_review_flag": True,
    },
    "NAVAREA III 0171/26": {
        "region": "iii",
        "number": "0171",
        "year": "26",
        "expected_types": ["LineString"],
        "expected_labels": [None],
        "expected_coordinate_counts": [21],
        "expected_tier": "B",
        "requires_review_flag": True,
    },
    "NAVAREA IX 440/26": {
        "region": "ix",
        "number": "440",
        "year": "26",
        "expected_types": None,
        "expected_labels": None,
        "expected_coordinate_counts": None,
        "expected_tier": "B",
        "requires_review_flag": False,
    },
}


def parse_live_record(record: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    """Run the deterministic parser against one fetched raw bulletin."""
    raw_text = record.get("raw_text") or ""
    if not raw_text.strip():
        raise ValueError(f"{record.get('canonical_id')}: raw_text is empty")

    header_text = raw_text.splitlines()[0].strip()
    if not header_text:
        raise ValueError(f"{record.get('canonical_id')}: first raw-text line is empty")

    block = {
        "number": expected["number"],
        "year": expected["year"],
        "header_text": header_text,
        "raw_text": raw_text,
    }
    config = navarea_universal_parser._region_config(expected["region"])
    _, parsed = navarea_universal_parser.parse_warning(
        block,
        config,
        now_utc=datetime.now(timezone.utc),
    )
    payload = build_master_payload(parsed)

    features = (parsed.get("spatial") or {}).get("features") or []
    feature_summary: List[Dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        properties = feature.get("properties") or {}
        feature_summary.append({
            "geometry_type": geometry.get("type"),
            "sub_area": properties.get("sub_area"),
            "coordinate_count": len(coordinates),
        })

    return {
        "canonical_id": record.get("canonical_id"),
        "database_status": record.get("status"),
        "database_data_quality": record.get("data_quality"),
        "database_triage_tier": record.get("triage_tier"),
        "parsed_data_quality": parsed.get("data_quality"),
        "parsed_triage_tier": payload.get("triage_tier"),
        "parsed_qa_flags": parsed.get("qa_flags") or [],
        "features": feature_summary,
    }


def validate_result(result: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    """Return mismatches; an empty list means the dry-run expectations passed."""
    errors: List[str] = []
    features = result["features"]
    types = [item["geometry_type"] for item in features]
    labels = [item["sub_area"] for item in features]
    counts = [item["coordinate_count"] for item in features]

    if result["parsed_triage_tier"] != expected["expected_tier"]:
        errors.append(
            f"expected Tier {expected['expected_tier']}, got {result['parsed_triage_tier']}"
        )

    if expected["expected_types"] is not None:
        if types != expected["expected_types"]:
            errors.append(f"expected geometry types {expected['expected_types']}, got {types}")
        if labels != expected["expected_labels"]:
            errors.append(f"expected route labels {expected['expected_labels']}, got {labels}")
        if counts != expected["expected_coordinate_counts"]:
            errors.append(
                f"expected coordinate counts {expected['expected_coordinate_counts']}, got {counts}"
            )
    else:
        if not features:
            errors.append("expected ambiguous source positions to remain represented")
        if any(kind in ("LineString", "MultiLineString", "Polygon", "MultiPolygon")
               for kind in types):
            errors.append(f"ambiguous cable positions were promoted to route/area: {types}")
        if result["parsed_data_quality"] != "AMBIGUOUS":
            errors.append(
                f"expected AMBIGUOUS data quality, got {result['parsed_data_quality']}"
            )

    has_review_flag = "DOTTED_LINE_ROUTE_REVIEW" in result["parsed_qa_flags"]
    if has_review_flag != expected["requires_review_flag"]:
        errors.append(
            "DOTTED_LINE_ROUTE_REVIEW flag mismatch "
            f"(expected {expected['requires_review_flag']}, got {has_review_flag})"
        )
    return errors


def run_dry_run(client: Any) -> Dict[str, Any]:
    """Fetch exactly the target rows and reparse them without database writes."""
    response = (
        client.table("nav_warnings")
        .select("id,canonical_id,navarea,status,raw_text,data_quality,triage_tier")
        .in_("canonical_id", list(TARGETS))
        .execute()
    )
    rows = response.data or []
    report: Dict[str, Any] = {
        "mode": "read_only_parser_dry_run",
        "database_writes": False,
        "ai_calls": False,
        "targets": {},
        "passed": False,
    }

    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_id.setdefault(row.get("canonical_id"), []).append(row)

    all_passed = True
    for canonical_id, expected in TARGETS.items():
        matching = by_id.get(canonical_id, [])
        active = [row for row in matching if row.get("status") == "active"]
        if len(active) != 1:
            report["targets"][canonical_id] = {
                "passed": False,
                "errors": [
                    f"expected exactly one active record, found {len(active)} "
                    f"(total exact-ID rows: {len(matching)})"
                ],
            }
            all_passed = False
            continue

        record = active[0]
        try:
            result = parse_live_record(record, expected)
            errors = validate_result(result, expected)
            report["targets"][canonical_id] = {
                **result,
                "passed": not errors,
                "errors": errors,
            }
            if errors:
                all_passed = False
        except Exception as exc:
            report["targets"][canonical_id] = {
                "passed": False,
                "errors": [f"{type(exc).__name__}: {exc}"],
            }
            all_passed = False

    report["passed"] = all_passed
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only dry run of dotted-line parsing against live Supabase raw text."
    )
    parser.add_argument(
        "--output",
        default="dotted-line-dry-run.json",
        help="Local JSON report path (default: dotted-line-dry-run.json).",
    )
    args = parser.parse_args()

    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) are required.",
              file=sys.stderr)
        return 2

    try:
        from supabase import create_client
        client = create_client(url, key)
        report = run_dry_run(client)
    except Exception as exc:
        print(f"Read-only dry run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Report written to {args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
