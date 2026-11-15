#!/usr/bin/env python3
"""Offline, read-only geometry dry run from caller-supplied JSON files.

Input JSON is an array of {"canonical_id": "...", "raw_text": "..."}.
Optional persisted JSON is either an array of {"canonical_id": "...",
"geometry": <GeoJSON>} records or an object mapping canonical IDs to GeoJSON.
No database client, network access, or source-data writes are used.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

from scripts import navarea_universal_parser
from shared.models import build_master_payload


CANONICAL_ID_RE = re.compile(
    r"^NAVAREA\s+(?P<region>[IVX]+)\s+(?P<number>\d{3,4})/(?P<year>\d{2,4})$",
    re.IGNORECASE,
)
NOW_UTC = datetime(2026, 11, 15, tzinfo=timezone.utc)


def _geometry_items(spatial: Any) -> List[Dict[str, Any]]:
    if isinstance(spatial, list):
        return [item for entry in spatial for item in _geometry_items(entry)]
    if not isinstance(spatial, dict):
        return []
    if spatial.get("type") == "FeatureCollection":
        return [
            feature.get("geometry")
            for feature in spatial.get("features", [])
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
        ]
    if spatial.get("type") == "Feature":
        geometry = spatial.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    return [spatial] if isinstance(spatial.get("coordinates"), list) else []


def _coordinate_count(value: Any) -> int:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    ):
        return 1
    if isinstance(value, list):
        return sum(_coordinate_count(item) for item in value)
    return 0


def _coordinate_ends(value: Any) -> tuple[Optional[list], Optional[list]]:
    leaves: List[list] = []

    def visit(node: Any) -> None:
        if (
            isinstance(node, list)
            and len(node) == 2
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in node)
        ):
            leaves.append(node)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    if not leaves:
        return None, None
    return leaves[0], leaves[-1]


def _summarize_geometry(geometry: Dict[str, Any]) -> Dict[str, Any]:
    coordinates = geometry.get("coordinates")
    first, last = _coordinate_ends(coordinates)
    return {
        "geometry_type": geometry.get("type"),
        "coordinate_count": _coordinate_count(coordinates),
        "first_coordinate": first,
        "last_coordinate": last,
        "coordinates": coordinates,
    }


def _persisted_by_id(records: Any) -> Dict[str, Any]:
    if records is None:
        return {}
    if isinstance(records, dict):
        return records
    if not isinstance(records, list):
        raise ValueError("persisted JSON must be an array or an object keyed by canonical_id")
    result = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("canonical_id"), str):
            raise ValueError("each persisted record needs a canonical_id")
        geometry = record.get("geometry", record.get("spatial", record.get("geojson")))
        if geometry is None:
            raise ValueError(f"{record['canonical_id']}: persisted record needs geometry or spatial")
        canonical_id = record["canonical_id"]
        if canonical_id not in result:
            result[canonical_id] = geometry
        else:
            previous = result[canonical_id]
            if not isinstance(previous, list):
                previous = [previous]
            previous.append(geometry)
            result[canonical_id] = previous
    return result


def _compare_geometry(parsed: List[Dict[str, Any]], persisted_spatial: Any) -> Dict[str, Any]:
    persisted = [
        _summarize_geometry(item)
        for item in _geometry_items(persisted_spatial)
    ]
    comparisons = []
    for index in range(max(len(parsed), len(persisted))):
        left = parsed[index] if index < len(parsed) else None
        right = persisted[index] if index < len(persisted) else None
        comparisons.append({
            "index": index,
            "parsed_geometry_type": left.get("geometry_type") if left else None,
            "persisted_geometry_type": right.get("geometry_type") if right else None,
            "parsed_coordinate_count": left.get("coordinate_count") if left else 0,
            "persisted_coordinate_count": right.get("coordinate_count") if right else 0,
            "parsed_first_coordinate": left.get("first_coordinate") if left else None,
            "persisted_first_coordinate": right.get("first_coordinate") if right else None,
            "parsed_last_coordinate": left.get("last_coordinate") if left else None,
            "persisted_last_coordinate": right.get("last_coordinate") if right else None,
            "exact_coordinate_equality": (
                left is not None and right is not None
                and left.get("coordinates") == right.get("coordinates")
            ),
        })
    return {
        "parsed_geometry_count": len(parsed),
        "persisted_geometry_count": len(persisted),
        "geometry_count_equal": len(parsed) == len(persisted),
        "comparisons": comparisons,
    }


def run_json_inputs(
    input_records: Any,
    persisted_records: Any = None,
) -> Dict[str, Any]:
    """Parse local JSON records with the production deterministic parser."""
    if not isinstance(input_records, list):
        raise ValueError("input JSON must be an array of {canonical_id, raw_text}")
    persisted = _persisted_by_id(persisted_records)
    results = []

    for record in input_records:
        if not isinstance(record, dict):
            raise ValueError("each input record must be an object")
        canonical_id = record.get("canonical_id")
        raw_text = record.get("raw_text")
        if not isinstance(canonical_id, str) or not isinstance(raw_text, str):
            raise ValueError("each input record needs string canonical_id and raw_text")
        match = CANONICAL_ID_RE.fullmatch(canonical_id.strip())
        if not match:
            raise ValueError(f"unsupported canonical_id: {canonical_id!r}")
        if not raw_text.strip():
            raise ValueError(f"{canonical_id}: raw_text is empty")

        region = match.group("region").lower()
        number = match.group("number")
        year = match.group("year")
        header_text = raw_text.splitlines()[0] if raw_text.splitlines() else ""
        if not header_text:
            raise ValueError(f"{canonical_id}: first raw-text line is empty")

        config = navarea_universal_parser._region_config(region)
        block = {
            "number": number,
            "year": year,
            "header_text": header_text,
            "raw_text": raw_text,
        }
        _, warning = navarea_universal_parser.parse_warning(
            block, config, now_utc=NOW_UTC
        )
        spatial = warning.get("spatial")
        geometries = [
            _summarize_geometry(item)
            for item in _geometry_items(spatial)
        ]
        geometry_types = [item["geometry_type"] for item in geometries]
        payload = build_master_payload(warning)
        result = {
            "canonical_id": canonical_id,
            "geometry_type": geometry_types[0] if len(geometry_types) == 1 else geometry_types,
            "coordinate_count": sum(item["coordinate_count"] for item in geometries),
            "data_quality": warning.get("data_quality"),
            "qa_flags": warning.get("qa_flags") or [],
            "triage_tier": payload.get("triage_tier"),
            "geometries": [
                {key: value for key, value in item.items() if key != "coordinates"}
                for item in geometries
            ],
        }
        if canonical_id in persisted:
            result["persisted_comparison"] = _compare_geometry(
                geometries, persisted[canonical_id]
            )
        results.append(result)

    return {
        "mode": "offline_read_only_geometry_dry_run",
        "input_count": len(input_records),
        "results": results,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the real NAVAREA geometry parser on local JSON files only."
    )
    parser.add_argument("--input", required=True, help="JSON array of canonical_id/raw_text records")
    parser.add_argument("--persisted", help="Optional JSON of persisted GeoJSON geometries")
    parser.add_argument("--output", help="Optional report path; stdout is used when omitted")
    args = parser.parse_args(argv)

    try:
        with open(args.input, encoding="utf-8") as handle:
            inputs = json.load(handle)
        persisted = None
        if args.persisted:
            with open(args.persisted, encoding="utf-8") as handle:
                persisted = json.load(handle)
        report = run_json_inputs(inputs, persisted)
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(rendered + "\n")
        else:
            print(rendered)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Dry run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
