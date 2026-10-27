#!/usr/bin/env python3
"""
scripts/audit_supabase_parsing.py — Supabase Parsing Audit & AI Correction Engine

Reads the eligible nav_warnings dataset from Supabase using keyset pagination (id > last_id),
validates records and geometries deterministically, compares parsed fields with raw text,
evaluates ambiguous cases with Gemini (grounded in source text), produces structured
correction proposals, and safely applies explicitly approved proposals under atomic optimistic concurrency.

Modes:
  1. audit_only: Scan records & geometries, flag issues, generate audit report.
     Zero database writes of ANY kind (no run-ledger row is created).
  2. propose_corrections: Deterministic audit + Gemini analysis, persists pending proposals in
     parsing_correction_proposals (zero writes to nav_warnings).
  3. apply_approved: Safely apply approved, validated, non-stale proposals to nav_warnings
     through the admin_save_nav_warning RPC (atomic row update + nav_warning_audits audit row,
     optimistic lock, edited_by_admin flag so the scraper freeze guard keeps the correction).

Safety invariants:
  - The Gemini model identifier is verified against the Gemini API before use; an invalid or
    unavailable model fails the run closed (exit 3) and is never silently substituted.
  - The AI-correctable field set is whitelist-only and must stay a subset of the columns the
    admin_save_nav_warning RPC accepts in p_update. Titles, dates and status are never AI-edited.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.validation import validate_lat_lon, validate_warning_id
from shared.utils import parse_coordinates, repair_coordinate_token

DEFAULT_MODEL = "gemini-3.8-flash"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

EXIT_MODEL_UNAVAILABLE = 3  # fail-closed: the Gemini model could not be verified

# Allowlisted fields that can be corrected on nav_warnings via approved proposals.
# This must remain a subset of the columns accepted by admin_save_nav_warning(p_update).
# title / area_text / valid_from / valid_to are deliberately EXCLUDED: they are
# lifecycle-authoritative fields owned by the sync engine and human admins.
ALLOWED_PROPOSAL_FIELDS = {
    "categories",
    "triage_tier",
    "data_quality",
    "unplotted_reason",
}

# Regex for ungrounded coordinate patterns with missing hemispheres (e.g. 54-12.0 011-14.5 without N/S/E/W)
RE_MISSING_HEM = re.compile(
    r"\b(\d{1,2}-\d{2}(?:\.\d+)?)\s*(?![\d\.\-NSEWnsew])\b"
)


def get_supabase_client(url: Optional[str] = None, key: Optional[str] = None) -> Any:
    """Initialize and validate the Supabase client.
    Prefers passed credentials, falling back to SUPABASE_URL and SUPABASE_KEY/SERVICE_ROLE_KEY.
    """
    sb_url = (url or os.getenv("SUPABASE_URL") or "").strip()
    sb_key = (
        key
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    ).strip()

    if not sb_url:
        raise ValueError("SUPABASE_URL environment variable is required.")
    if not sb_key:
        raise ValueError("SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) is required.")

    try:
        from supabase import create_client
        return create_client(sb_url, sb_key)
    except ImportError as exc:
        raise RuntimeError(
            "The 'supabase' Python package is required. Install via pip install supabase."
        ) from exc


def fetch_all_warnings(
    client: Any,
    navarea: Optional[str] = None,
    batch_size: int = 500
) -> Tuple[List[Dict[str, Any]], bool, Optional[str]]:
    """Fetch warnings with explicit keyset pagination (id > last_id).
    Returns (records, is_complete, error_message).
    Ensures that partial or failed scans are explicitly flagged.
    """
    rows: List[Dict[str, Any]] = []
    last_id: Optional[str] = None
    is_complete = False
    error_msg: Optional[str] = None

    try:
        while True:
            query = (
                client.table("nav_warnings")
                .select("*")
                .order("id")
                .limit(batch_size)
            )

            if last_id is not None:
                query = query.gt("id", last_id)

            if navarea:
                query = query.eq("navarea", navarea)

            res = query.execute()
            page = res.data or []
            rows.extend(page)

            if len(page) < batch_size:
                is_complete = True
                break

            last_id = page[-1].get("id")
    except Exception as exc:
        error_msg = f"Pagination halted after id '{last_id}': {type(exc).__name__}: {str(exc)}"
        is_complete = False

    return rows, is_complete, error_msg


def fetch_geometries_for_warnings(
    client: Any,
    warning_ids: List[str],
    batch_size: int = 200
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch child geometries from nav_warning_geometries for the audited warnings."""
    if not warning_ids:
        return {}

    geoms_by_wid: Dict[str, List[Dict[str, Any]]] = {wid: [] for wid in warning_ids}

    for i in range(0, len(warning_ids), batch_size):
        chunk = warning_ids[i:i + batch_size]
        try:
            res = (
                client.table("nav_warning_geometries")
                .select("*")
                .in_("warning_id", chunk)
                .execute()
            )
            for g in (res.data or []):
                wid = g.get("warning_id")
                if wid in geoms_by_wid:
                    geoms_by_wid[wid].append(g)
        except Exception as exc:
            print(f"[warning] Failed to fetch geometries for batch {i}: {exc}", file=sys.stderr)

    return geoms_by_wid


def validate_warning_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministically validates a single nav_warning row.
    Returns structured validation issues without mutating data.
    """
    issues: List[Dict[str, Any]] = []
    wid = record.get("id")
    canonical_id = (record.get("canonical_id") or "").strip()
    raw_text = record.get("raw_text") or ""
    tier = record.get("triage_tier")
    quality = record.get("data_quality")
    method = record.get("parsing_method")
    unplotted = record.get("unplotted_reason")
    status = record.get("status")

    # 1. Canonical ID validation
    if not canonical_id:
        issues.append({
            "code": "MISSING_CANONICAL_ID",
            "field": "canonical_id",
            "severity": "ERROR",
            "message": "Warning record lacks canonical_id.",
            "current_value": canonical_id,
        })
    else:
        try:
            validate_warning_id(canonical_id)
        except Exception as exc:
            issues.append({
                "code": "INVALID_CANONICAL_ID",
                "field": "canonical_id",
                "severity": "ERROR",
                "message": f"Canonical ID failed syntax check: {exc}",
                "current_value": canonical_id,
            })

    # 2. Raw text availability (Rule 125)
    if not raw_text or not raw_text.strip():
        issues.append({
            "code": "MISSING_RAW_TEXT",
            "field": "raw_text",
            "severity": "WARNING",
            "message": "Raw source text is unavailable; verification is inconclusive.",
            "current_value": None,
        })

    # 3. Status validity
    allowed_statuses = {"active", "cancelled", "expired", "superseded", "unverified"}
    if status and status not in allowed_statuses:
        issues.append({
            "code": "INVALID_STATUS",
            "field": "status",
            "severity": "ERROR",
            "message": f"Status '{status}' not in allowed set {allowed_statuses}.",
            "current_value": status,
        })

    # 4. Triage Tier Invariants (chk_tier_a_invariants)
    if tier == "A":
        if quality != "EXPLICIT":
            issues.append({
                "code": "TIER_A_INVARIANT_VIOLATION",
                "field": "data_quality",
                "severity": "ERROR",
                "message": f"Tier A record must have data_quality='EXPLICIT' (found '{quality}').",
                "current_value": quality,
            })
        if unplotted is not None:
            issues.append({
                "code": "TIER_A_INVARIANT_VIOLATION",
                "field": "unplotted_reason",
                "severity": "ERROR",
                "message": f"Tier A record cannot have unplotted_reason (found '{unplotted}').",
                "current_value": unplotted,
            })
        if method != "RULE":
            issues.append({
                "code": "TIER_A_INVARIANT_VIOLATION",
                "field": "parsing_method",
                "severity": "ERROR",
                "message": f"Tier A record must have parsing_method='RULE' (found '{method}').",
                "current_value": method,
            })

    # 5. Date validation
    valid_from = record.get("valid_from")
    valid_to = record.get("valid_to")
    dt_from = None
    dt_to = None

    if valid_from:
        try:
            dt_from = datetime.fromisoformat(str(valid_from).replace("Z", "+00:00"))
        except Exception:
            issues.append({
                "code": "INVALID_DATE_FORMAT",
                "field": "valid_from",
                "severity": "WARNING",
                "message": f"valid_from '{valid_from}' is not valid ISO 8601.",
                "current_value": valid_from,
            })

    if valid_to:
        try:
            dt_to = datetime.fromisoformat(str(valid_to).replace("Z", "+00:00"))
        except Exception:
            issues.append({
                "code": "INVALID_DATE_FORMAT",
                "field": "valid_to",
                "severity": "WARNING",
                "message": f"valid_to '{valid_to}' is not valid ISO 8601.",
                "current_value": valid_to,
            })

    if dt_from and dt_to and dt_to < dt_from:
        issues.append({
            "code": "DATE_RANGE_INVERTED",
            "field": "valid_to",
            "severity": "ERROR",
            "message": f"valid_to ({valid_to}) is earlier than valid_from ({valid_from}).",
            "current_value": valid_to,
        })

    # 6. Bathymetry Sentinel checks (Rule 31)
    shoal_depth = record.get("shoal_depth_m")
    if shoal_depth is not None:
        try:
            depth_f = float(shoal_depth)
            if depth_f == -9999.0 or depth_f <= -50.0 or depth_f >= 12000.0:
                issues.append({
                    "code": "INVALID_BATHYMETRY_SENTINEL",
                    "field": "shoal_depth_m",
                    "severity": "ERROR",
                    "message": f"shoal_depth_m contains sentinel or out-of-range value: {depth_f}",
                    "current_value": shoal_depth,
                })
        except (ValueError, TypeError):
            issues.append({
                "code": "INVALID_BATHYMETRY_TYPE",
                "field": "shoal_depth_m",
                "severity": "ERROR",
                "message": f"shoal_depth_m is not a valid numeric float: {shoal_depth}",
                "current_value": shoal_depth,
            })

    # 7. Coordinate parsing check against raw source text
    if raw_text:
        coords, _, _, _ = parse_coordinates(raw_text)
        has_coords = len(coords) > 0

        # Check for ambiguous missing hemisphere in raw text
        if not has_coords and RE_MISSING_HEM.search(raw_text):
            issues.append({
                "code": "MISSING_HEMISPHERE_UNRESOLVED",
                "field": "unplotted_reason",
                "severity": "WARNING",
                "message": "Potential coordinate tokens detected lacking hemisphere; must remain unresolved, do not guess.",
                "current_value": unplotted,
            })

        # Discrepancy: coordinates extractable from text, but marked unplotted 'no_coordinates'
        if has_coords and unplotted == "no_coordinates":
            issues.append({
                "code": "DISCREPANCY_UNPLOTTED_WITH_COORDINATES",
                "field": "unplotted_reason",
                "severity": "WARNING",
                "message": f"raw_text contains {len(coords)} coordinates, but record has unplotted_reason='no_coordinates'.",
                "current_value": unplotted,
            })

    return issues


def validate_warning_geometry(
    record: Dict[str, Any],
    geometry_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validates geometry child records against coordinate bounds, GeoJSON standards,
    and schema constraints.
    """
    issues: List[Dict[str, Any]] = []
    tier = record.get("triage_tier")
    allowed_types = {"POINT", "LINE", "POLYGON", "CORRIDOR", "SWEEP_ARC", "BOUNDING_BOX"}

    # Tier A record must have at least one valid geometry row
    if tier == "A" and (not geometry_data or len(geometry_data) == 0):
        issues.append({
            "code": "TIER_A_ZERO_GEOMETRIES",
            "field": "geometries",
            "severity": "ERROR",
            "message": "Tier A warning has zero associated child geometries in nav_warning_geometries.",
            "current_value": 0,
        })

    for idx, geom in enumerate(geometry_data):
        ftype = (geom.get("feature_type") or "").strip().upper()
        if ftype not in allowed_types:
            issues.append({
                "code": "INVALID_FEATURE_TYPE",
                "field": f"geometries[{idx}].feature_type",
                "severity": "ERROR",
                "message": f"Geometry feature_type '{ftype}' violates CHECK constraint {allowed_types}.",
                "current_value": ftype,
            })

        # Inspect geojson payload if available in raw representation or json
        geojson_blob = geom.get("geojson") or geom.get("geom_geojson")
        if isinstance(geojson_blob, str):
            try:
                geojson_blob = json.loads(geojson_blob)
            except Exception:
                geojson_blob = None

        if isinstance(geojson_blob, dict):
            gtype = geojson_blob.get("type")
            coords = geojson_blob.get("coordinates")

            if not gtype or coords is None:
                issues.append({
                    "code": "MALFORMED_GEOJSON",
                    "field": f"geometries[{idx}].geojson",
                    "severity": "ERROR",
                    "message": "GeoJSON missing required 'type' or 'coordinates'.",
                    "current_value": geojson_blob,
                })
                continue

            # Validate coordinate bounds and ring closures
            if gtype == "Point":
                if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                    issues.append({
                        "code": "MALFORMED_POINT",
                        "field": f"geometries[{idx}].coordinates",
                        "severity": "ERROR",
                        "message": f"Point coordinates must be [lon, lat], got: {coords}",
                        "current_value": coords,
                    })
                else:
                    lon, lat = coords[0], coords[1]
                    if not validate_lat_lon(lat, lon):
                        issues.append({
                            "code": "COORDINATE_OUT_OF_BOUNDS",
                            "field": f"geometries[{idx}].coordinates",
                            "severity": "ERROR",
                            "message": f"Point coordinates out of bounds: lon={lon}, lat={lat}",
                            "current_value": coords,
                        })

            elif gtype == "Polygon":
                if not isinstance(coords, list) or len(coords) == 0:
                    issues.append({
                        "code": "MALFORMED_POLYGON",
                        "field": f"geometries[{idx}].coordinates",
                        "severity": "ERROR",
                        "message": "Polygon coordinates must be list of rings.",
                        "current_value": coords,
                    })
                else:
                    outer_ring = coords[0]
                    if not isinstance(outer_ring, list) or len(outer_ring) < 4:
                        issues.append({
                            "code": "POLYGON_UNDERSIZED_RING",
                            "field": f"geometries[{idx}].coordinates",
                            "severity": "ERROR",
                            "message": f"Polygon exterior ring must have >= 4 coordinates, got {len(outer_ring) if isinstance(outer_ring, list) else 0}",
                            "current_value": outer_ring,
                        })
                    else:
                        first_pt, last_pt = outer_ring[0], outer_ring[-1]
                        if first_pt != last_pt:
                            issues.append({
                                "code": "POLYGON_UNCLOSED_RING",
                                "field": f"geometries[{idx}].coordinates",
                                "severity": "ERROR",
                                "message": "Polygon ring is unclosed: first coordinate != last coordinate.",
                                "current_value": [first_pt, last_pt],
                            })

    return issues


def gemini_verify_model(model: str, api_key: str, timeout: float = 15.0) -> Tuple[bool, Optional[str]]:
    """Verify the model identifier exists on the Gemini API before use.

    Fail-closed: returns (False, reason) on 404/403/network failure. The caller
    must abort the run; never silently substitute another model.
    """
    import urllib.error
    import urllib.request

    url = f"{API_ROOT}/{model}"
    req = urllib.request.Request(url, headers={"x-goog-api-key": api_key}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # The response names the model it describes; a mismatch means the API
        # silently resolved a different model, which we must not accept.
        name = (data.get("name") or "").rsplit("/", 1)[-1]
        if name and name != model:
            return False, f"API resolved model '{name}' instead of requested '{model}'"
        return True, None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, f"model '{model}' does not exist on the Gemini API (404)"
        if exc.code == 403:
            return False, f"API key rejected for model '{model}' (403)"
        return False, f"model verification failed: HTTP {exc.code}"
    except Exception as exc:
        return False, f"model verification failed: {type(exc).__name__}: {exc}"


def verify_model_fail_closed(model: str) -> None:
    """Verify the configured Gemini model or abort with EXIT_MODEL_UNAVAILABLE."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print(
            f"[error] GEMINI_API_KEY is not set; cannot verify model '{model}'. "
            f"Aborting without any database access (exit {EXIT_MODEL_UNAVAILABLE}).",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_MODEL_UNAVAILABLE)
    ok, err = gemini_verify_model(model, api_key)
    if not ok:
        print(
            f"[error] Gemini model '{model}' could not be verified: {err}. "
            f"Refusing to substitute a different model (exit {EXIT_MODEL_UNAVAILABLE}).",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_MODEL_UNAVAILABLE)
    print(f"[audit] Gemini model verified: {model}")


def assess_warning_with_gemini(
    record: Dict[str, Any],
    model_name: Optional[str] = None,
    issues: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Assess ambiguous or erroneous parsed fields against raw source text using Gemini.
    Strict fail-closed rules:
      - Requires GEMINI_API_KEY.
      - Grounding check: Proposed raw_evidence must be a verbatim substring of raw_text.
      - Disallowed to modify canonical_id, raw_text, source_id, or database UUIDs.
      - High confidence score alone is never sufficient authorization.
      - Returns a list of proposal dictionaries matching parsing_correction_proposals schema.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return []

    model = model_name or os.getenv("GEMINI_MODEL_NAME") or DEFAULT_MODEL
    raw_text = record.get("raw_text") or ""
    canonical_id = record.get("canonical_id") or "UNKNOWN"

    if not raw_text.strip():
        # Inconclusive without raw text
        return []

    prompt = (
        f"You are a maritime safety MSI data auditor inspecting a NAVAREA navigational warning record.\n"
        f"Compare the stored record with the verbatim bulletin text.\n\n"
        f"CANONICAL_ID: {canonical_id}\n"
        f"RAW SOURCE BULLETIN TEXT:\n\"\"\"\n{raw_text}\n\"\"\"\n\n"
        f"CURRENT PARSED ATTRIBUTES:\n"
        f"- title: {record.get('title')}\n"
        f"- area_text: {record.get('area_text')}\n"
        f"- categories: {record.get('categories')}\n"
        f"- triage_tier: {record.get('triage_tier')}\n"
        f"- data_quality: {record.get('data_quality')}\n"
        f"- unplotted_reason: {record.get('unplotted_reason')}\n"
        f"- valid_from: {record.get('valid_from')}\n"
        f"- valid_to: {record.get('valid_to')}\n"
        f"- shoal_depth_m: {record.get('shoal_depth_m')}\n\n"
        f"IDENTIFIED ISSUES:\n{json.dumps(issues or [], indent=2)}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Only propose corrections for fields that are unambiguously supported by the raw text.\n"
        f"2. Never invent or extrapolate coordinates. If coordinates lack a hemisphere, set proposed_value to null "
        f"   and unplotted_reason to 'missing_hemisphere' (requires_review=true).\n"
        f"3. Every proposal MUST have an exact 'raw_evidence' snippet verbatim from the source text.\n"
        f"4. Allowed fields to correct: {sorted(list(ALLOWED_PROPOSAL_FIELDS))}.\n"
        f"5. Return a JSON array of proposal objects. If no corrections are warranted, return [].\n"
        f"Schema for each item:\n"
        f"{{\n"
        f"  \"canonical_id\": \"{canonical_id}\",\n"
        f"  \"field_name\": \"<field>\",\n"
        f"  \"original_value\": <current_val>,\n"
        f"  \"proposed_value\": <new_val>,\n"
        f"  \"raw_evidence\": \"<exact quote from raw text>\",\n"
        f"  \"explanation\": \"<short justification>\",\n"
        f"  \"confidence\": 0.0 to 1.0,\n"
        f"  \"requires_review\": true\n"
        f"}}\n"
        f"OUTPUT ONLY RAW JSON, NO MARKDOWN FENCES."
    )

    response_text = ""
    try:
        # Prefer google-genai SDK if available, else urllib REST call
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            # Gemini 3.x removed temperature/top_p/top_k sampling controls.
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            response_text = resp.text or ""
        except ImportError:
            import urllib.request
            url = f"{API_ROOT}/{model}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"}
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as http_resp:
                res_data = json.loads(http_resp.read().decode("utf-8"))
                candidates = res_data.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    response_text = parts[0].get("text", "") if parts else ""
    except Exception as exc:
        print(f"[warning] Gemini API assessment failed for {canonical_id}: {type(exc).__name__}", file=sys.stderr)
        return []

    # Clean markdown fences if model returned them
    cleaned = re.sub(r"^```[a-zA-Z]*|^```|```$", "", response_text.strip()).strip()
    if not cleaned:
        return []

    try:
        data = json.loads(cleaned)
    except Exception:
        # Try finding array bounds
        s = cleaned.find("[")
        e = cleaned.rfind("]")
        if s >= 0 and e > s:
            try:
                data = json.loads(cleaned[s:e + 1])
            except Exception:
                return []
        else:
            return []

    if not isinstance(data, list):
        return []

    validated_proposals: List[Dict[str, Any]] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        field_name = str(item.get("field_name") or "").strip()
        raw_evidence = str(item.get("raw_evidence") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        confidence = item.get("confidence")

        # 1. Field allowlist check
        if field_name not in ALLOWED_PROPOSAL_FIELDS:
            continue

        # 2. Strict Grounding: raw_evidence must be present in raw_text
        if not raw_evidence or raw_evidence not in raw_text:
            continue

        # 3. Confidence range check
        conf_val = None
        if confidence is not None:
            try:
                conf_val = max(0.0, min(1.0, float(confidence)))
            except (ValueError, TypeError):
                conf_val = None

        validated_proposals.append({
            "warning_record_id": record.get("id"),
            "canonical_id": canonical_id,
            "navarea": record.get("navarea"),
            "field_name": field_name,
            "original_value": item.get("original_value", record.get(field_name)),
            "proposed_value": item.get("proposed_value"),
            "raw_evidence": raw_evidence,
            "explanation": explanation,
            "confidence": conf_val,
            "validation": {
                "grounded": True,
                "model_name": model,
                "assessed_at": datetime.now(timezone.utc).isoformat(),
            },
            "status": "pending",
        })

    return validated_proposals


def create_correction_proposals(
    client: Any,
    run_id: str,
    proposals: List[Dict[str, Any]]
) -> int:
    """Persist validated proposals without changing nav_warnings."""
    if not proposals:
        return 0

    inserted_count = 0
    batch_size = 50

    for i in range(0, len(proposals), batch_size):
        chunk = proposals[i:i + batch_size]
        rows_to_insert = []
        for p in chunk:
            row = dict(p)
            row["audit_run_id"] = run_id
            rows_to_insert.append(row)

        try:
            res = client.table("parsing_correction_proposals").insert(rows_to_insert).execute()
            inserted_count += len(res.data or rows_to_insert)
        except Exception as exc:
            print(f"[error] Failed to insert correction proposals batch: {exc}", file=sys.stderr)

    return inserted_count


def validate_proposed_field_value(
    field_name: str,
    proposed_val: Any,
    raw_evidence: Optional[str],
    raw_text: str
) -> Tuple[bool, Optional[str]]:
    """Strictly validates a proposed correction against raw bulletin text and maritime domain field rules."""
    # 1. Field allowlist check
    if field_name not in ALLOWED_PROPOSAL_FIELDS:
        return False, f"Field '{field_name}' is not in allowlist {sorted(list(ALLOWED_PROPOSAL_FIELDS))}."

    # 2. Raw text grounding check: raw_evidence must be present in raw_text if provided
    if raw_evidence:
        if raw_evidence not in raw_text:
            return False, f"Evidence '{raw_evidence}' is not present in raw_text."

    # 3. Field-specific maritime domain validation
    if field_name == "triage_tier":
        if proposed_val not in ("A", "B", "C"):
            return False, f"Invalid triage_tier '{proposed_val}'; must be 'A', 'B', or 'C'."

    elif field_name == "data_quality":
        if proposed_val not in ("EXPLICIT", "INFERRED", "AMBIGUOUS", "INVALID"):
            return False, f"Invalid data_quality '{proposed_val}'."

    elif field_name == "unplotted_reason":
        allowed_unplotted = {
            None, "", "no_coordinates", "parse_failure", "meta_list", "text_unavailable",
            "empty_stub", "cancellation_only", "truncated_clause", "missing_hemisphere",
            "duplicate_of", "validation_failed", "no_valid_geometry"
        }
        if proposed_val not in allowed_unplotted:
            return False, f"Invalid unplotted_reason '{proposed_val}'."

    elif field_name == "categories":
        if not isinstance(proposed_val, list):
            return False, f"categories must be a list of strings, got {type(proposed_val).__name__}."

    return True, None


def apply_approved_corrections(
    client: Any,
    proposal_ids: List[str]
) -> Dict[str, Any]:
    """Apply only approved, validated, non-stale proposals safely.
    Strict safety guarantees:
      - Validates every proposal ID with uuid.UUID() before any DB query.
      - Verifies proposal status is 'approved'.
      - Reloads current warning by stable UUID.
      - Revalidates proposed value against raw_text and domain rules.
      - Applies through the admin_save_nav_warning RPC: atomic row update +
        nav_warning_audits audit row in one transaction, optimistic lock via
        p_expected_updated_at, appended edited_by_admin freeze flag.
      - Skips proposals whose field already equals the proposed value (idempotent)
        or whose original value has diverged (stale).
      - Marks proposal applied ONLY after the RPC (update + audit row) succeeds.
    """
    summary = {
        "applied": [],
        "stale": [],
        "failed": [],
        "rejected": [],
    }

    if not proposal_ids:
        return summary

    now_iso = datetime.now(timezone.utc).isoformat()

    for raw_pid in proposal_ids:
        if raw_pid is None:
            continue
        pid_str = str(raw_pid).strip()
        if not pid_str:
            continue

        # Step 1: Validate proposal ID is a valid UUID before any database query
        try:
            clean_uuid = str(uuid.UUID(pid_str))
        except (ValueError, TypeError, AttributeError):
            summary["failed"].append({
                "proposal_id": pid_str,
                "reason": f"Invalid proposal ID format '{pid_str}': must be a valid UUID."
            })
            continue

        try:
            # Step 2: Fetch proposal
            prop_res = (
                client.table("parsing_correction_proposals")
                .select("*")
                .eq("id", clean_uuid)
                .execute()
            )
            props = prop_res.data or []
            if not props:
                summary["failed"].append({
                    "proposal_id": clean_uuid,
                    "reason": "Proposal record not found."
                })
                continue

            prop = props[0]
            current_status = prop.get("status")

            # Step 3: Check approval state
            if current_status != "approved":
                summary["rejected"].append({
                    "proposal_id": clean_uuid,
                    "canonical_id": prop.get("canonical_id"),
                    "status": current_status,
                    "reason": f"Proposal is in '{current_status}' state; only 'approved' proposals can be applied."
                })
                continue

            wid = prop.get("warning_record_id")
            field_name = prop.get("field_name")
            original_val = prop.get("original_value")
            proposed_val = prop.get("proposed_value")
            raw_evidence = prop.get("raw_evidence")

            # Step 4: Fetch current warning record from database
            warn_res = client.table("nav_warnings").select("*").eq("id", wid).execute()
            warnings = warn_res.data or []
            if not warnings:
                client.table("parsing_correction_proposals").update({
                    "status": "failed",
                    "error_message": f"Associated warning {wid} does not exist."
                }).eq("id", clean_uuid).execute()
                summary["failed"].append({
                    "proposal_id": clean_uuid,
                    "reason": "Associated warning record not found."
                })
                continue

            current_warning = warnings[0]
            raw_text = current_warning.get("raw_text") or ""

            # Step 5: Re-validate proposed value against warning raw_text and domain field rules
            valid_ok, valid_err = validate_proposed_field_value(
                field_name=field_name,
                proposed_val=proposed_val,
                raw_evidence=raw_evidence,
                raw_text=raw_text
            )
            if not valid_ok:
                client.table("parsing_correction_proposals").update({
                    "status": "failed",
                    "error_message": valid_err
                }).eq("id", clean_uuid).execute()
                summary["failed"].append({
                    "proposal_id": clean_uuid,
                    "reason": valid_err
                })
                continue

            # Step 6: Idempotency + optimistic concurrency pre-check on the just-read row
            cur_val = current_warning.get(field_name)
            if cur_val == proposed_val:
                # Idempotent no-op: the row already carries the proposed value.
                if current_status == "approved":
                    client.table("parsing_correction_proposals").update({
                        "status": "applied",
                        "applied_at": now_iso,
                    }).eq("id", clean_uuid).execute()
                summary["applied"].append({
                    "proposal_id": clean_uuid,
                    "canonical_id": prop.get("canonical_id"),
                    "field_name": field_name,
                    "new_value": proposed_val,
                    "reason": "already_applied",
                })
                continue
            if original_val is not None and cur_val != original_val:
                client.table("parsing_correction_proposals").update({
                    "status": "stale",
                    "error_message": (
                        f"Field value changed since the audit. Expected {json.dumps(original_val)}, "
                        f"found {json.dumps(cur_val)} in database."
                    )
                }).eq("id", clean_uuid).execute()
                summary["stale"].append({
                    "proposal_id": clean_uuid,
                    "canonical_id": prop.get("canonical_id"),
                    "field_name": field_name,
                    "expected": original_val,
                    "actual": cur_val,
                })
                continue

            # Step 7: Append freeze flags so the scraper overwrite guard keeps the
            # correction, matching the qa_flags semantics of the admin save path.
            qf = current_warning.get("qa_flags") or []
            if not isinstance(qf, list):
                qf = list(qf)
            new_flags = qf + [f for f in ("ai_correction_applied", "edited_by_admin") if f not in qf]

            prev_tier = current_warning.get("triage_tier") or "B"
            new_tier = (
                proposed_val
                if (field_name == "triage_tier" and proposed_val in ("A", "B", "C"))
                else prev_tier
            )

            # Step 8: Apply through the admin_save_nav_warning RPC — atomic row
            # update + nav_warning_audits audit row in ONE transaction. The
            # RPC re-checks p_expected_updated_at under FOR UPDATE, closing the
            # race between the read above and this write. Direct table updates
            # that bypass the audit trail are forbidden.
            client.rpc("admin_save_nav_warning", {
                "p_warning_id": wid,
                "p_update": {"qa_flags": new_flags, field_name: proposed_val},
                "p_geometries": None,
                "p_expected_updated_at": current_warning.get("updated_at"),
                "p_operator": "supabase-parsing-audit",
                "p_action": "AI_CORRECTION_APPLIED",
                "p_reason": (prop.get("explanation") or "parsing audit correction")[:500],
                "p_previous_tier": prev_tier,
                "p_new_tier": new_tier,
                "p_diff_patch": {
                    "proposal_id": clean_uuid,
                    "audit_run_id": prop.get("audit_run_id"),
                    "field": field_name,
                    "before": original_val,
                    "after": proposed_val,
                    "raw_evidence": raw_evidence,
                    "confidence": prop.get("confidence"),
                },
            }).execute()

            # Step 9: Mark proposal applied ONLY AFTER the RPC (update + audit row) succeeds
            client.table("parsing_correction_proposals").update({
                "status": "applied",
                "applied_at": now_iso,
            }).eq("id", clean_uuid).execute()

            summary["applied"].append({
                "proposal_id": clean_uuid,
                "canonical_id": prop.get("canonical_id"),
                "field_name": field_name,
                "new_value": proposed_val,
            })

        except Exception as exc:
            msg = str(exc)
            print(f"[error] Failed to apply proposal {clean_uuid}: {msg}", file=sys.stderr)
            try:
                if "STALE_UPDATED_AT" in msg:
                    # The record changed between our read and the RPC write.
                    client.table("parsing_correction_proposals").update({
                        "status": "stale",
                        "error_message": "Record changed since the audit (RPC optimistic lock).",
                    }).eq("id", clean_uuid).execute()
                    summary["stale"].append({
                        "proposal_id": clean_uuid,
                        "canonical_id": prop.get("canonical_id") if isinstance(prop, dict) else None,
                        "reason": "record changed since the audit (RPC optimistic lock)",
                    })
                else:
                    client.table("parsing_correction_proposals").update({
                        "status": "failed",
                        "error_message": msg,
                    }).eq("id", clean_uuid).execute()
                    summary["failed"].append({
                        "proposal_id": clean_uuid,
                        "reason": msg,
                    })
            except Exception:
                pass
            continue

    return summary


def run_audit(
    mode: str = "audit_only",
    navarea: Optional[str] = None,
    proposal_ids: Optional[List[str]] = None,
    report_dir: str = "audit-report",
    batch_size: int = 500,
    client: Optional[Any] = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Orchestrate parsing audit, proposal generation, or approved correction application.
    Generates a full report; propose/apply modes record results in public.parsing_audit_runs
    (audit_only is fully read-only and persists nothing to the database).
    """
    if mode not in ("audit_only", "propose_corrections", "apply_approved"):
        raise ValueError(f"Invalid mode '{mode}'. Choose from 'audit_only', 'propose_corrections', 'apply_approved'.")

    supabase_client = client or get_supabase_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    selected_model = model_name or os.getenv("GEMINI_MODEL_NAME") or DEFAULT_MODEL

    # Fail-closed model verification before ANY database access: an invalid or
    # unavailable model aborts the run (never silently substituted).
    if mode == "propose_corrections":
        verify_model_fail_closed(selected_model)

    # audit_only is strictly read-only: no run-ledger row is created at all.
    # propose/apply modes persist a ledger row; failure there is fail-closed
    # (proposals could not otherwise be tracked, approved, or applied).
    run_id = None
    if mode != "audit_only":
        try:
            run_record = {
                "mode": mode,
                "navarea_filter": navarea,
                "model_name": selected_model if mode == "propose_corrections" else None,
                "status": "running",
                "started_at": now_iso,
            }
            res = supabase_client.table("parsing_audit_runs").insert(run_record).execute()
            run_id = (res.data or [{}])[0].get("id")
            if not run_id:
                raise RuntimeError("parsing_audit_runs insert returned no row id")
        except Exception as exc:
            raise RuntimeError(
                f"Could not initialize parsing_audit_runs row (mode={mode}): {exc}. "
                "Failing closed — has migrations/20261026_parsing_audit.sql been applied to Supabase?"
            ) from exc

    report: Dict[str, Any] = {
        "audit_run_id": run_id,
        "mode": mode,
        "navarea_filter": navarea,
        "model_name": selected_model if mode == "propose_corrections" else None,
        "started_at": now_iso,
        "scan_complete": False,
        "examined_count": 0,
        "issue_count": 0,
        "proposal_count": 0,
        "applied_count": 0,
        "failed_count": 0,
        "issues": [],
        "proposals": [],
        "apply_summary": {},
    }

    try:
        if mode == "apply_approved":
            # Apply approved proposals
            ids_to_apply = proposal_ids or []
            apply_res = apply_approved_corrections(supabase_client, ids_to_apply)
            report["apply_summary"] = apply_res
            report["applied_count"] = len(apply_res.get("applied", []))
            report["failed_count"] = len(apply_res.get("failed", [])) + len(apply_res.get("rejected", []))
            report["scan_complete"] = True
            report["status"] = "succeeded"

        else:
            # 1. Fetch all warnings with complete keyset pagination
            warnings, is_complete, fetch_err = fetch_all_warnings(
                supabase_client, navarea=navarea, batch_size=batch_size
            )
            report["examined_count"] = len(warnings)
            report["scan_complete"] = is_complete

            if fetch_err:
                report["fetch_error"] = fetch_err

            # 2. Fetch geometries for the examined warnings
            wids = [w.get("id") for w in warnings if w.get("id")]
            geoms_by_wid = fetch_geometries_for_warnings(supabase_client, wids)

            # 3. Deterministic Validation
            all_issues: List[Dict[str, Any]] = []
            records_with_issues: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []

            for w in warnings:
                w_issues = validate_warning_record(w)
                g_issues = validate_warning_geometry(w, geoms_by_wid.get(w.get("id"), []))
                combined = w_issues + g_issues
                if combined:
                    for iss in combined:
                        iss["warning_id"] = w.get("id")
                        iss["canonical_id"] = w.get("canonical_id")
                        iss["navarea"] = w.get("navarea")
                        all_issues.append(iss)
                    records_with_issues.append((w, combined))

            report["issues"] = all_issues
            report["issue_count"] = len(all_issues)

            # 4. Gemini Propose Corrections (if mode is propose_corrections)
            all_proposals: List[Dict[str, Any]] = []
            if mode == "propose_corrections":
                for rec, rec_issues in records_with_issues:
                    proposals = assess_warning_with_gemini(
                        record=rec,
                        model_name=selected_model,
                        issues=rec_issues
                    )
                    all_proposals.extend(proposals)

                if run_id and all_proposals:
                    inserted_proposals = create_correction_proposals(
                        supabase_client, run_id, all_proposals
                    )
                    report["proposal_count"] = inserted_proposals
                else:
                    report["proposal_count"] = len(all_proposals)

            report["proposals"] = all_proposals
            report["status"] = "succeeded" if is_complete else "partial"

    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        print(f"[error] Audit run encountered fatal error: {exc}", file=sys.stderr)

    report["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Update database audit run record
    if run_id:
        try:
            update_data = {
                "completed_at": report["completed_at"],
                "status": report.get("status", "failed"),
                "examined_count": report.get("examined_count", 0),
                "issue_count": report.get("issue_count", 0),
                "proposal_count": report.get("proposal_count", 0),
                "applied_count": report.get("applied_count", 0),
                "failed_count": report.get("failed_count", 0),
                "scan_complete": report.get("scan_complete", False),
                "report": {
                    "issue_summary": {
                        "total": report.get("issue_count", 0),
                        "codes": [iss.get("code") for iss in report.get("issues", [])][:100],
                    },
                    "apply_summary": report.get("apply_summary", {}),
                },
            }
            supabase_client.table("parsing_audit_runs").update(update_data).eq("id", run_id).execute()
        except Exception as exc:
            print(f"[warning] Failed to finalize parsing_audit_runs row: {exc}", file=sys.stderr)

    # Write report files
    try:
        os.makedirs(report_dir, exist_ok=True)
        report_filename = f"audit_report_{run_id or 'local'}_{int(datetime.now().timestamp())}.json"
        report_path = os.path.join(report_dir, report_filename)
        summary_path = os.path.join(report_dir, "summary.json")

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        with open(summary_path, "w", encoding="utf-8") as f:
            summary = {
                "audit_run_id": report.get("audit_run_id"),
                "status": report.get("status"),
                "mode": report.get("mode"),
                "examined_count": report.get("examined_count"),
                "issue_count": report.get("issue_count"),
                "proposal_count": report.get("proposal_count"),
                "applied_count": report.get("applied_count"),
                "scan_complete": report.get("scan_complete"),
                "completed_at": report.get("completed_at"),
            }
            json.dump(summary, f, indent=2)

        print(f"[audit] Report successfully written to {report_path}")
    except Exception as exc:
        print(f"[warning] Could not save audit report files: {exc}", file=sys.stderr)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit, propose corrections, or apply approved fixes to Supabase nav_warnings."
    )
    parser.add_argument(
        "--mode",
        choices=["audit_only", "propose_corrections", "apply_approved"],
        default="audit_only",
        help="Execution mode (default: audit_only).",
    )
    parser.add_argument(
        "--navarea",
        type=str,
        default=None,
        help="Optional NAVAREA filter (e.g. 'Baltic', 'NA I', 'IV').",
    )
    parser.add_argument(
        "--proposal-ids",
        type=str,
        default=None,
        help="Comma-separated or JSON list of proposal UUIDs for apply_approved mode.",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="audit-report",
        help="Directory to save JSON audit artifacts (default: audit-report).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for pagination (default: 500).",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Gemini model name to use for AI proposals.",
    )

    args = parser.parse_args()

    proposal_ids = []
    if args.proposal_ids:
        raw_ids = args.proposal_ids.strip()
        if raw_ids.startswith("["):
            try:
                proposal_ids = json.loads(raw_ids)
            except Exception:
                proposal_ids = [p.strip() for p in raw_ids.strip("[]").split(",") if p.strip()]
        else:
            proposal_ids = [p.strip() for p in raw_ids.split(",") if p.strip()]

    if args.mode == "apply_approved" and not proposal_ids:
        print("[error] apply_approved mode requires at least one proposal ID in --proposal-ids.", file=sys.stderr)
        return 1

    try:
        res = run_audit(
            mode=args.mode,
            navarea=args.navarea,
            proposal_ids=proposal_ids,
            report_dir=args.report_dir,
            batch_size=args.batch_size,
            model_name=args.model_name,
        )
        status = res.get("status")
        print(f"[audit] Run completed with status='{status}'. Examined={res.get('examined_count')}, Issues={res.get('issue_count')}, Proposals={res.get('proposal_count')}, Applied={res.get('applied_count')}")
        return 0 if status in ("succeeded", "partial") else 1
    except Exception as exc:
        print(f"[error] Fatal execution failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

