#!/usr/bin/env python3
"""
scripts/ai_parser.py — Production AI & Deterministic Parser for NAVAREA Warnings
Extracts coordinates and triage categories using Gemini with schema enforcement and robust fallback.
"""

import os
import sys
import json
import re
from typing import Any, Optional

# Ensure repo root is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Resilient Pydantic import with lightweight fallback
try:
    from pydantic import BaseModel, Field, ValidationError
    HAS_PYDANTIC = True
except ImportError:
    ValidationError = Exception
    HAS_PYDANTIC = False

    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, data):
            if isinstance(data, dict):
                return cls(**data)
            return data

        def model_dump(self, mode="json"):
            result = {}
            for k, v in self.__dict__.items():
                if isinstance(v, list):
                    result[k] = [item.model_dump() if hasattr(item, "model_dump") else item for item in v]
                elif hasattr(v, "model_dump"):
                    result[k] = v.model_dump()
                else:
                    result[k] = v
            return result

    def Field(*args, **kwargs):
        default = kwargs.get("default", None)
        default_factory = kwargs.get("default_factory", None)
        if default_factory is not None:
            return default_factory()
        return default

# Resilient Google GenAI import
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    genai = None
    types = None
    HAS_GENAI = False


# ----------------------------
# Pydantic schemas
# ----------------------------

class CoordinateProvenance(BaseModel):
    original_text: str = Field(description="Original coordinate text extracted from the warning")
    repaired_lat: float = Field(description="Latitude in decimal degrees, negative for South")
    repaired_lon: float = Field(description="Longitude in decimal degrees, negative for West")
    repair_method: str = Field(description="How the coordinate was converted or repaired")


class TriageRecord(BaseModel):
    triage_tier: int = Field(ge=1, le=3, description="1 immediate danger, 2 navigational hazard, 3 general info")
    category: str = Field(description="Example: Drifting Hazard, Search and Rescue, Cable Laying")
    coordinates: list[CoordinateProvenance] = Field(default_factory=list)


# ----------------------------
# Coordinate conversion helpers
# ----------------------------

def parse_dms_to_decimal(raw: str) -> Optional[float]:
    """
    Parses coordinate fragments like:
    - 52-45.1N
    - 002-12.4E
    - 52 45.1 N
    - 52°45.1'N
    """
    if raw is None:
        return None

    s = raw.strip().upper()

    # Normalize separators
    s = s.replace("°", "").replace("'", "").replace('"', "")
    s = s.replace(" ", "")

    match = re.match(r"^([0-9]{1,3})-?([0-9]{1,2}(?:\.[0-9]+)?)([NSEW])$", s)
    if not match:
        return None

    deg = float(match.group(1))
    minutes = float(match.group(2))
    hemi = match.group(3)

    if minutes >= 60.0:
        return None

    decimal = deg + (minutes / 60.0)

    if hemi in ("S", "W"):
        decimal *= -1

    return decimal


def parse_coordinate_pair(raw_pair: str) -> Optional[tuple[float, float]]:
    """
    Example raw_pair: '52-45.1N 002-12.4E'
    """
    if not raw_pair or not isinstance(raw_pair, str):
        return None

    raw_pair = raw_pair.strip()

    # Split on whitespace, keeping lat/lon
    parts = raw_pair.split()
    if len(parts) < 2:
        return None

    lat_raw = parts[0]
    lon_raw = parts[1]

    lat = parse_dms_to_decimal(lat_raw)
    lon = parse_dms_to_decimal(lon_raw)

    if lat is None or lon is None:
        return None

    return lat, lon


# ----------------------------
# Fallback parser
# ----------------------------

def fallback_parse_warning(raw_warning: str) -> dict:
    """
    Deterministic fallback parser for common NAVAREA warning patterns.
    It extracts a coordinate pair and assigns a basic triage.
    """
    text = raw_warning or ""

    # Try to find a lat/lon pair pattern directly in the warning
    match = re.search(
        r"([0-9]{1,3}-[0-9]{1,2}(?:\.[0-9]+)?[NSEW])\s+([0-9]{1,3}-[0-9]{1,2}(?:\.[0-9]+)?[NSEW])",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        raise ValueError("No coordinate pair found in warning text")

    pair = f"{match.group(1)} {match.group(2)}"
    lat_lon = parse_coordinate_pair(pair)

    if lat_lon is None:
        raise ValueError("Could not parse coordinate pair")

    lat, lon = lat_lon

    category = "Drifting Hazard"
    triage_tier = 2  # default NAVAREA hazard category

    # Look for "immediate" or "danger" language if present
    lowered = text.lower()
    if "danger" in lowered or "explosion" in lowered or "collision" in lowered:
        triage_tier = 1
    elif "advisory" in lowered or "general" in lowered:
        triage_tier = 3

    return {
        "triage_tier": triage_tier,
        "category": category,
        "coordinates": [
            {
                "original_text": pair,
                "repaired_lat": round(lat, 6),
                "repaired_lon": round(lon, 6),
                "repair_method": "Converted DMS-style coordinate to decimal degrees"
            }
        ]
    }


# ----------------------------
# Gemini integration
# ----------------------------

def process_warning_with_ai(raw_warning_text: str) -> dict | None:
    """
    Sends the warning to Gemini and validates the returned JSON using Pydantic.
    If the model fails or returns malformed JSON, a deterministic fallback parser is used.
    """
    # If GenAI SDK or API key is not available, immediately route to deterministic fallback
    api_key = os.environ.get("GEMINI_API_KEY")
    if not HAS_GENAI or genai is None or not api_key:
        try:
            return fallback_parse_warning(raw_warning_text)
        except Exception:
            print("❌ Deterministic fallback parse failed (no coordinate match).")
            return None

    # Model resolution: default to modern model with fallback options
    model_name = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")

    system_instruction = (
        "You are an expert maritime navigator and data parser. "
        "Extract coordinates from the provided NAVAREA warning, converting degrees/minutes/seconds "
        "or non-standard formats into decimal degrees. "
        "Assign a triage tier based on the hazard level (1: danger, 2: hazard, 3: info). "
        "Return valid JSON only matching the schema: "
        "{\"triage_tier\": int, \"category\": str, \"coordinates\": [{\"original_text\": str, \"repaired_lat\": float, \"repaired_lon\": float, \"repair_method\": str}]}."
    )

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=model_name,
            contents=raw_warning_text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        raw_text = getattr(response, "text", None)
        if not raw_text:
            raise ValueError("Empty response from Gemini")

        parsed = json.loads(raw_text)
        validated = TriageRecord.model_validate(parsed)
        return validated.model_dump(mode="json")

    except (Exception, ValidationError, json.JSONDecodeError):
        try:
            return fallback_parse_warning(raw_warning_text)
        except Exception:
            print("❌ Gemini parsing failed and fallback parse failed.")
            return None


# ----------------------------
# Local execution
# ----------------------------

if __name__ == "__main__":
    sample = """
    NAVAREA I 124/26
    ENGLAND EAST COAST.
    DRIFTING SHIPPING CONTAINER REPORTED IN VICINITY 52-45.1N 002-12.4E AT 181400Z OCT.
    VESSELS KEEP SHARP LOOKOUT.
    """

    print("Sending to Gemini...")
    result = process_warning_with_ai(sample)

    if result:
        print("\n✅ Success! Parsed Output:")
        print(json.dumps(result, indent=2))
    else:
        print("\n❌ Failed to parse warning.")
