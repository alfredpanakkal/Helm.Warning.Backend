#!/usr/bin/env python3
"""
shared/gemini_navarea_parser.py — Gemini-first bulletin parsing with the
deterministic rule parser as the final authority.

Public contract (fail closed everywhere):

    parse_bulletin_with_fallback(bulletin_text, region_key, rule_parser)

      1. Regions in RULE_FIRST_ONLY_REGIONS never touch the model
         (2026-10-22 decision: NAVAREA II is rule-first only).
      2. No API key -> deterministic rule parser, logged.
      3. Model output is accepted ONLY if it passes validate_llm_payload()
         AND the grounding check. Any failure (missing key, timeout,
         invalid JSON, schema violation, ungrounded coordinate) falls
         back to the rule parser, logged.
      4. AI-accepted output is always Tier B / INFERRED, never Tier A —
         memo carries 'ai_parse' provenance for downstream triage.
      5. This module never flips warning status. S-124 cancellationDate
         is a planned date; supersede transitions belong to a dedicated
         supersede pass, not the parser.

Safety rules:
  - API key only from env (GEMINI_API_KEY or GOOGLE_API_KEY), sent in the
    x-goog-api-key header — never in URL, argv, or logs. Errors are
    logged by exception class name only (no request URLs / bodies).
  - Model id from GEMINI_MODEL_NAME (default gemini-3.5-flash-lite).
    Never assume a model id remains available — verify against the API
    before relying on it.
  - Grounding (no second parser): a model coordinate is accepted only if
    shared.utils.parse_coordinates independently reproduces it on the same
    raw_text (tolerance GROUNDING_TOLERANCE_DEG). Geometry must be
    GeoJSON-valid; if uncertain, the model must omit geometry — invented
    polygons are rejected, the parse fails closed to the rule parser.
"""
import json
import os
import re

from shared.utils import parse_coordinates
from shared.navarea_universal_text import UNIVERSAL_REGIONS, warning_header_re

TIMEOUT_SECONDS = 30
GROUNDING_TOLERANCE_DEG = 1e-5
DEFAULT_MODEL_FALLBACK = "gemini-3.5-flash-lite"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Region keys that must stay rule-first, regardless of key availability.
RULE_FIRST_ONLY_REGIONS = {"ii"}

REQUIRED_LIST_KEYS = ("raw_messages", "nav_warnings", "spatial_features")
REQUIRED_WARNING_FIELDS = ("warning_id", "canonical_id", "source_id",
                            "navarea", "status")
_ALLOWED_GEOMETRY_TYPES = ("Point", "MultiPoint", "LineString",
                            "MultiLineString", "Polygon", "MultiPolygon")


def _log(message):
    print("[gemini] " + message)


def _model_name():
    return os.environ.get("GEMINI_MODEL_NAME") or DEFAULT_MODEL_FALLBACK


def get_api_key():
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _prompt(bulletin_text, region_key):
    roman = UNIVERSAL_REGIONS[region_key]
    return (
        "You parse a maritime NAVAREA warning bulletin for NAVAREA " + roman + ".\n"
        "STRICT RULES:\n"
        "1. Warning header pattern: NAVAREA " + roman + " [-]nnn/yy (one region per "
        "bulletin; reject anything else).\n"
        "2. Segment the bulletin into individual numbered warnings on those headers.\n"
        "3. The warning body may contain numbered items (1. 2. ...) — each item is a "
        "geometry clause (area description / coordinates).\n"
        "4. Coordinates are in maritime notation like 48-30.0N 006-15.0W "
        "(degrees-minutes.decimal). Extract geometry ONLY from coordinate tokens "
        "literally present in the text. NEVER invent, extrapolate or close polygons "
        "you are uncertain about.\n"
        "5. If geometry is ambiguous or absent for a warning, set its 'spatial' to "
        "null, 'latitude'/'longitude' to null — fail closed.\n"
        "6. Cross-references like CANCEL NAVAREA " + roman + " n/yy go into "
        "'cross_refs' as [{'number': str, 'year': str}].\n"
        "7. 'status' is always 'active'. Never infer cancellations.\n"
        "8. Each nav_warning MUST include a 'raw_text' field with the exact, "
        "verbatim text of that warning block from the bulletin (no paraphrasing).\n"
        "9. memo MUST be {'region': '" + region_key + "', 'navarea': '" + roman
        + "', 'source_id': 'manual-navarea-" + region_key + "', "
        "'in_force_as_on': null-or-ISO-date}.\n\n"
        "OUTPUT: a single JSON object, no markdown fences, no commentary, with "
        "exactly these keys:\n"
        "{\n"
        "  \"raw_messages\": [{\"warning_id\": str, \"source_id\": str, "
        "\"subject_header\": str, \"full_raw_text\": str, "
        "\"received_timestamp\": str, \"checksum_sha256\": str}],\n"
        "  \"nav_warnings\": [{\"warning_id\": str, \"canonical_id\": str, "
        "\"source_id\": str, \"navarea\": str, \"title\": str, "
        "\"issued_text\": null, \"coordinates\": null, "
        "\"latitude\": number-or-null, \"longitude\": number-or-null, "
        "\"category\": str, \"categories\": [str], \"status\": 'active', "
        "\"raw_text\": str, \"spatial\": GeoJSON-FeatureCollection-or-null, "
        "\"sub_areas\": [str], \"geometry_sub_areas\": [str], "
        "\"cross_refs\": [{}]}],\n"
        "  \"spatial_features\": [{\"warning_id\": str, \"category\": str, "
        "\"geometry\": FeatureCollection}],\n"
        "  \"memo\": {}\n"
        "}\n\n"
        "BULLETIN:\n" + bulletin_text
    )


def _extract_json(text):
    """Parses strict JSON, tolerating stray markdown fences."""
    cleaned = re.sub(r"^```[a-zA-Z]*|^```|```$", "", (text or "").strip()).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response contains no JSON object")
    return json.loads(cleaned[start:end + 1])


def try_gemini_parse(bulletin_text, region_key, timeout=TIMEOUT_SECONDS):
    """Calls Gemini and returns the raw parsed JSON payload (unvalidated).

    Raises TimeoutError on timeout, ValueError on unparseable output,
    RuntimeError on API errors. Never logs URLs or response bodies.
    """
    api_key = get_api_key()
    if not api_key:
        _log("GEMINI_API_KEY not found — cannot attempt model parse.")
        return None

    try:
        import requests  # lazy: the CI unittest runner installs no requirements
    except ImportError as exc:
        raise RuntimeError("requests library not available") from exc

    url = API_ROOT + "/" + _model_name() + ":generateContent"
    body = {
        "contents": [{"parts": [{"text": _prompt(bulletin_text, region_key)}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    try:
        resp = requests.post(url, json=body,
                             headers={"x-goog-api-key": api_key,
                                      "Content-Type": "application/json"},
                             timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("gemini request timed out after " + str(timeout) + "s") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("gemini request failed: " + type(exc).__name__) from exc

    if resp.status_code != 200:
        raise RuntimeError("gemini API returned HTTP " + str(resp.status_code))

    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("gemini response missing candidate text") from exc

    return _extract_json(text)


def _coords_ok(node):
    """GeoJSON coordinate structure check: [lon, lat] pairs within range."""
    if (isinstance(node, (list, tuple)) and len(node) >= 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in node[:2])):
        return len(node) in (2, 3) and -180.0 <= node[0] <= 180.0 and -90.0 <= node[1] <= 90.0
    if isinstance(node, (list, tuple)) and node:
        return all(_coords_ok(child) for child in node)
    return False


def _geometry_ok(geometry):
    if not isinstance(geometry, dict):
        return False
    if geometry.get("type") not in _ALLOWED_GEOMETRY_TYPES:
        return False
    return _coords_ok(geometry.get("coordinates"))


def _spatial_ok(spatial):
    if spatial is None:
        return True
    if not isinstance(spatial, dict) or spatial.get("type") != "FeatureCollection":
        return False
    features = spatial.get("features")
    if not isinstance(features, list) or not features:
        return False
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            return False
        if not _geometry_ok(feature.get("geometry")):
            return False
    return True


def validate_llm_payload(payload, region_key):
    """Strict schema validation of the model output.

    Returns (ok, reason). reason is None when ok.
    """
    if not isinstance(payload, dict):
        return False, "payload is not a JSON object"
    for key in REQUIRED_LIST_KEYS:
        if not isinstance(payload.get(key), list):
            return False, "missing or non-list '" + key + "'"
    if not payload["nav_warnings"]:
        return False, "payload contains zero warnings"
    memo = payload.get("memo")
    if not isinstance(memo, dict):
        return False, "missing memo object"

    roman = UNIVERSAL_REGIONS[region_key]
    source_id = "manual-navarea-" + region_key
    header_re = warning_header_re(roman)

    if memo.get("source_id") != source_id or memo.get("navarea") != roman:
        return False, "memo region/source_id mismatch"
    for msg in payload["raw_messages"]:
        if not isinstance(msg, dict) or not msg.get("warning_id"):
            return False, "raw_messages entry malformed"
    for w in payload["nav_warnings"]:
        if not isinstance(w, dict):
            return False, "nav_warnings entry is not an object"
        for field in REQUIRED_WARNING_FIELDS:
            if w.get(field) in (None, ""):
                return False, "warning missing required field '" + field + "'"
        if w["navarea"] != roman:
            return False, "warning navarea mismatch"
        if w["source_id"] != source_id:
            return False, "warning source_id mismatch"
        if not header_re.search(w["warning_id"]) or not header_re.search(w["canonical_id"]):
            return False, "warning_id/canonical_id not a valid NAVAREA " + roman + " header"
        if w.get("status") != "active":
            return False, "model must not invent status transitions (status must be 'active')"
        if not isinstance(w.get("raw_text"), str) or not w["raw_text"].strip():
            return False, "warning missing verbatim raw_text"
        if not _spatial_ok(w.get("spatial")):
            return False, "invalid GeoJSON spatial block"
    for sf in payload["spatial_features"]:
        if not isinstance(sf, dict) or not sf.get("warning_id") or not _spatial_ok(sf.get("geometry")):
            return False, "spatial_features entry malformed"
    return True, None


def _grounding_ok(payload, bulletin_text):
    """The model's coordinates must be an exact substring of the source AND
    independently reproduced by the deterministic coordinate parser."""
    for w in payload["nav_warnings"]:
        raw = (w.get("raw_text") or "").strip()
        if not raw or raw not in (bulletin_text or ""):
            return False
        if w.get("spatial") is not None:
            _, lat, lon, spatial = parse_coordinates(raw)
            if spatial is None or lat is None or lon is None:
                return False  # ungrounded geometry: invented polygons fail closed
            m_lat, m_lon = w.get("latitude"), w.get("longitude")
            if not isinstance(m_lat, (int, float)) or not isinstance(m_lon, (int, float)):
                return False
            if abs(m_lat - lat) > GROUNDING_TOLERANCE_DEG or abs(m_lon - lon) > GROUNDING_TOLERANCE_DEG:
                return False
    return True


def parse_bulletin_with_fallback(bulletin_text, region_key, rule_parser):
    """Gemini-first with deterministic fallback. Always returns a payload.

    The rule parser remains the final authority: any model failure, schema
    violation, or ungrounded coordinate falls back to rule_parser(text,
    region_key). Accepted AI output is marked Tier B / INFERRED in memo.
    """
    def _rule_parse():
        parsed = rule_parser(bulletin_text, region_key)
        if isinstance(parsed.get("memo"), dict):
            parsed["memo"]["parse_provenance"] = "rule"
        return parsed

    if region_key not in UNIVERSAL_REGIONS:
        _log("Unknown region key '" + str(region_key) + "' — rule parser only.")
        return rule_parser(bulletin_text, region_key)
    roman = UNIVERSAL_REGIONS[region_key]

    if region_key in RULE_FIRST_ONLY_REGIONS:
        _log("NAVAREA " + roman + " is rule-first only — model not attempted.")
        return _rule_parse()

    if not get_api_key():
        _log("GEMINI_API_KEY not found — falling back to deterministic parser.")
        return _rule_parse()

    if not bulletin_text or not bulletin_text.strip():
        return _rule_parse()

    _log("Gemini parse attempted for NAVAREA " + roman
         + " (model=" + _model_name() + ").")
    try:
        payload = try_gemini_parse(bulletin_text, region_key)
    except TimeoutError:
        _log("Gemini timed out after " + str(TIMEOUT_SECONDS)
             + "s — falling back to rule parser.")
        return _rule_parse()
    except ValueError:
        _log("Gemini output was not valid JSON — falling back to rule parser.")
        return _rule_parse()
    except Exception as exc:
        _log("Gemini call failed (" + type(exc).__name__
             + ") — falling back to rule parser.")
        return _rule_parse()

    if payload is None:
        _log("Gemini unavailable — falling back to rule parser.")
        return _rule_parse()

    ok, reason = validate_llm_payload(payload, region_key)
    if not ok:
        _log("Gemini output failed schema validation (" + str(reason)
             + ") — falling back to rule parser.")
        return _rule_parse()

    if not _grounding_ok(payload, bulletin_text):
        _log("Gemini output failed grounding check — falling back to rule parser.")
        return _rule_parse()

    memo = payload.get("memo")
    if isinstance(memo, dict):
        memo["parse_provenance"] = "gemini"
        memo["ai_parse"] = {"used": True, "model": _model_name(),
                            "tier": "B_INFERRED"}
    _log("Gemini payload accepted (Tier B / INFERRED) for NAVAREA " + roman + ".")
    return payload
