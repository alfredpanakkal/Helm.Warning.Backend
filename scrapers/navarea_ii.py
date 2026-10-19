#!/usr/bin/env python3
"""
scrapers/navarea_ii.py — NAVAREA II S-124 SECOM Ingestion Pipeline
Ingests S-124 (Ed. 2.0) nautical datasets packaged inside S-100 Exchange Sets
via IEC 63173-2 (SECOM) REST API, using local XML extraction with Gemini 2.5 Flash-Lite
backup for robust geometry recovery, and adapts notices into Supabase nav_warnings.
"""

import os
import io
import sys
import json
import base64
import zipfile
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import xml.etree.ElementTree as ET

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from pydantic import BaseModel, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        @classmethod
        def model_validate_json(cls, json_str):
            data = json.loads(json_str)
            return cls(**data)
    def Field(*args, **kwargs):
        return kwargs.get("default", None)

# Ensure root directory is on Python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Configure output encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Attempt Google GenAI import
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Attempt Supabase client import
try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

# Attempt shared helper import
try:
    from shared.utils import classify_hazard
except ImportError:
    def classify_hazard(text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["cable", "pipe", "submarine", "subsea", "diver"]):
            return "subsea"
        if any(w in t for w in ["drifting", "derelict", "hazard", "mine"]):
            return "drifting"
        if any(w in t for w in ["firing", "gunnery", "exercise", "military", "torpedo", "rocket"]):
            return "military"
        if any(w in t for w in ["light", "buoy", "beacon", "aton", "unlit", "damaged"]):
            return "aton"
        if any(w in t for w in ["rig", "platform", "drill", "survey", "seismic"]):
            return "offshore"
        if any(w in t for w in ["gps", "dgps", "ais", "navtex", "radar"]):
            return "electronic"
        return "general"


# --- Environment Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SERVICE_INSTANCE = "navarea_ii_en"
PING_OBJECT_URL = f"https://services.ping-info-nautique.fr/secom/{SERVICE_INSTANCE}/v1/object"
SOURCE_ID = "shom-navarea-2"

# --- Client Initializations ---
supabase: Optional[Any] = None
if HAS_SUPABASE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"⚠️ Supabase client initialization warning: {e}")

ai_client: Optional[Any] = None
if HAS_GENAI and GEMINI_API_KEY:
    try:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"⚠️ Google AI Studio client initialization warning: {e}")


# --- Gemini Structured Output Schema ---
class S124BackupSchema(BaseModel):
    warning_number: Optional[str] = Field(default=None, description="Notice number/year, e.g., '359/26'")
    warning_type: Optional[str] = Field(default=None, description="Category or nature of the maritime hazard")
    general_area: Optional[str] = Field(default=None, description="Broad geographic locality, e.g., 'BAY OF BISCAY'")
    publication_time: Optional[str] = Field(default=None, description="ISO 8601 publication or start timestamp")
    cancellation_date: Optional[str] = Field(default=None, description="ISO 8601 cancellation timestamp or null")
    warning_text: str = Field(default="", description="Full plain body text of the navigational warning")
    geojson_geometry: Optional[Dict[str, Any]] = Field(
        default=None,
        description="GeoJSON geometry object with coordinates in strictly [longitude, latitude] format"
    )


def strip_ns(tag: str) -> str:
    """Removes XML namespace prefix from tag if present."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def local_s124_extractor(gml_content: str, filename: str = "dataset.gml") -> Dict[str, Any]:
    """
    Primary local zero-latency extractor for S-124 GML XML datasets.
    Extracts text descriptions, warning attributes, and parses vector geometry,
    inverting GML lat-lon coordinate ordering to GeoJSON standard [lon, lat].
    """
    dataset_id = os.path.splitext(os.path.basename(filename))[0]
    warning_text_parts: List[str] = []
    coordinates: List[List[float]] = []
    geom_type: Optional[str] = None
    warning_number: Optional[str] = None
    warning_type: Optional[str] = None
    general_area: Optional[str] = None
    pub_time: Optional[str] = None
    cancel_time: Optional[str] = None

    try:
        root = ET.fromstring(gml_content)
    except Exception as e:
        return {
            "dataset_id": dataset_id,
            "warning_number": None,
            "warning_type": None,
            "general_area": None,
            "publication_time": None,
            "cancellation_date": None,
            "warning_text": "",
            "geojson_geometry": None,
            "parse_error": str(e),
        }

    for elem in root.iter():
        tag = strip_ns(elem.tag)
        val = elem.text.strip() if elem.text else ""

        if tag in ("text", "textDescription", "information", "warningText"):
            if val and val not in warning_text_parts:
                warning_text_parts.append(val)
        elif tag in ("warningNumber", "warningIdentifier", "identifier") and not warning_number:
            if val:
                warning_number = val
        elif tag in ("warningType", "typeOfWarning", "hazardType") and not warning_type:
            if val:
                warning_type = val
        elif tag in ("generalArea", "locationName", "geographicalArea") and not general_area:
            if val:
                general_area = val
        elif tag in ("publicationTime", "issueDate", "dateTime") and not pub_time:
            if val:
                pub_time = val
        elif tag in ("cancellationDate", "fixedDateRangeEnd", "dateEnd") and not cancel_time:
            if val:
                cancel_time = val
        elif tag in ("posList", "pos", "coordinates"):
            if val:
                coords = [float(x) for x in val.split() if x.replace("-", "").replace(".", "").isdigit()]
                it = iter(coords)
                # GML pos/posList coordinate pairs are 'latitude longitude'
                # Invert to GeoJSON standard '[longitude, latitude]'
                for lat, lon in zip(it, it):
                    coordinates.append([lon, lat])

        if tag in ("Polygon", "Surface", "PolygonPatch"):
            geom_type = "Polygon"
        elif tag in ("Point", "DirectPosition") and not geom_type:
            geom_type = "Point"
        elif tag in ("LineString", "Curve", "LineStringSegment") and geom_type != "Polygon":
            geom_type = "LineString"

    geojson_geom: Optional[Dict[str, Any]] = None
    if coordinates:
        if geom_type == "Polygon":
            # Ensure closed ring
            ring = list(coordinates)
            if len(ring) >= 3 and ring[0] != ring[-1]:
                ring.append(ring[0])
            geojson_geom = {"type": "Polygon", "coordinates": [ring]}
        elif geom_type == "Point" or len(coordinates) == 1:
            geojson_geom = {"type": "Point", "coordinates": coordinates[0]}
        else:
            geojson_geom = {"type": "LineString", "coordinates": coordinates}

    # If warning_number was not explicitly tagged, attempt regex search in text
    full_text = "\n\n".join(warning_text_parts).strip()
    if not warning_number and full_text:
        import re
        match = re.search(r"\b(\d{1,4}/\d{2,4})\b", full_text)
        if match:
            warning_number = match.group(1)

    return {
        "dataset_id": dataset_id,
        "warning_number": warning_number,
        "warning_type": warning_type,
        "general_area": general_area,
        "publication_time": pub_time,
        "cancellation_date": cancel_time,
        "warning_text": full_text,
        "geojson_geometry": geojson_geom,
    }


def gemini_flash_lite_backup(gml_content: str) -> Optional[S124BackupSchema]:
    """
    Intelligent backup parser using Gemini 2.5 Flash-Lite when local extraction
    lacks geometry, encounters complex GML nesting, or fails on irregular formatting.
    """
    if not ai_client:
        return None

    try:
        print("    [!] Local parser lacked geometry; invoking Gemini 2.5 Flash-Lite fallback...")
        system_instruction = (
            "You are an expert IHO S-124 hydrographic data parser. Extract warning details "
            "and hazard boundary geometry from GML datasets into structured JSON. "
            "CRITICAL: In GML, coordinate pairs are given as 'latitude longitude'. "
            "Strictly invert them to GeoJSON format '[longitude, latitude]'."
        )
        prompt = (
            "Extract the navigational warning attributes and maritime boundary geometry from this S-124 GML XML:\n\n"
            + gml_content[:15000]
        )

        response = ai_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=S124BackupSchema,
                temperature=0.0,
            ),
        )
        if response.text:
            return S124BackupSchema.model_validate_json(response.text)
        return None
    except Exception as e:
        print(f"    [!] Gemini Flash-Lite fallback error: {e}")
        return None


def adapt_to_nav_warnings(
    dataset_id: str,
    warning_number: Optional[str],
    warning_type: Optional[str],
    general_area: Optional[str],
    publication_time: Optional[str],
    cancellation_date: Optional[str],
    warning_text: str,
    geojson_geometry: Optional[Dict[str, Any]],
    raw_payload: str,
    used_ai: bool = False,
) -> Dict[str, Any]:
    """
    Adapts S-124 extracted notice into standard schema for public.nav_warnings.
    Computes coordinates, centroids, hazard category, and triage metadata.
    """
    wid = warning_number or dataset_id
    full_wid = f"NAVAREA II {wid}" if not wid.startswith("NAVAREA") else wid

    # Determine representative latitude and longitude
    lat: Optional[float] = None
    lon: Optional[float] = None
    coords_text: Optional[str] = None

    if geojson_geometry:
        gtype = geojson_geometry.get("type")
        coords = geojson_geometry.get("coordinates")
        if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])
            coords_text = f"{abs(lat):.4f}{'N' if lat >= 0 else 'S'} {abs(lon):.4f}{'E' if lon >= 0 else 'W'}"
        elif gtype in ("Polygon", "LineString") and coords:
            # Centroid approximation
            pts = coords[0] if gtype == "Polygon" else coords
            if pts and isinstance(pts, list):
                valid_pts = [p for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                if valid_pts:
                    avg_lon = sum(float(p[0]) for p in valid_pts) / len(valid_pts)
                    avg_lat = sum(float(p[1]) for p in valid_pts) / len(valid_pts)
                    lon, lat = round(avg_lon, 5), round(avg_lat, 5)
                    coords_text = f"{abs(lat):.4f}{'N' if lat >= 0 else 'S'} {abs(lon):.4f}{'E' if lon >= 0 else 'W'}"

    # Determine hazard category
    category = classify_hazard(f"{warning_type or ''} {warning_text}")

    # Build title
    title_parts = [full_wid]
    if general_area:
        title_parts.append(general_area)
    if warning_type and warning_type not in (general_area or ""):
        title_parts.append(warning_type)
    title = " - ".join(title_parts)

    return {
        "warning_id": wid,
        "source_id": SOURCE_ID,
        "navarea": "NAVAREA II",
        "title": title,
        "issued_text": publication_time,
        "coordinates": coords_text,
        "latitude": lat,
        "longitude": lon,
        "category": category,
        "status": "active" if not cancellation_date else "cancelled",
        "raw_text": warning_text or raw_payload[:500],
        "spatial": geojson_geometry,
        "data_quality": "EXPLICIT" if geojson_geometry else "INFERRED",
        "parsing_method": "AI" if used_ai else "RULE",
        "triage_tier": "A" if (geojson_geometry and lat is not None) else "B",
        "qa_flags": [] if geojson_geometry else ["NO_GEOMETRY_DETECTED"],
        "unplotted_reason": None if geojson_geometry else "no_coordinates",
    }


def run_navarea_ii_pipeline(
    mock_payload: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Executes the NAVAREA II ingestion pipeline:
    1. Fetches or accepts PING SECOM /object responses
    2. Decodes Base64 S-100 Exchange Sets and unzips in-memory GML
    3. Runs local extractor, falling back to Gemini Flash-Lite if geometry is missing
    4. Upserts normalized records into Supabase nav_warnings
    """
    print("=" * 70)
    print("⚓ NAVAREA II S-124 SECOM Ingestion Pipeline")
    print(f"📡 Endpoint: {PING_OBJECT_URL}")
    print("=" * 70)

    summary = {
        "total_items": 0,
        "harvested": 0,
        "synced": 0,
        "fallback_used": 0,
        "server_errors": "",
        "dry_run": dry_run or (supabase is None),
    }

    payload = mock_payload
    if payload is None:
        if not HAS_REQUESTS:
            print("❌ 'requests' library is not installed. Please run: pip install -r requirements.txt")
            summary["server_errors"] = "requests library missing"
            return summary
        try:
            print("[1/4] Querying PING SECOM REST API for active notices...")
            resp = requests.get(
                PING_OBJECT_URL,
                headers={"accept": "application/json"},
                timeout=45,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            print(f"❌ Failed to reach PING SECOM endpoint: {e}")
            summary["server_errors"] = str(e)
            return summary

    warning_objects = payload.get("dataResponseObject", [])
    pagination_info = payload.get("pagination", {})
    total_items = pagination_info.get("totalItems", len(warning_objects))
    server_errors = payload.get("responseText", "")
    summary["total_items"] = total_items
    summary["server_errors"] = server_errors

    print(f"[2/4] Retrieved {len(warning_objects)} Exchange Sets (Total reported: {total_items})")

    # Audit sync execution if sync log table exists
    if supabase and not dry_run:
        try:
            supabase.table("navarea_sync_logs").insert({
                "navarea": "NAVAREA II",
                "total_items": total_items,
                "server_errors": server_errors or None,
            }).execute()
        except Exception as e:
            # Table might not exist; safe to continue
            pass

    print("[3/4] Processing S-100 Exchange Sets...")
    for item in warning_objects:
        raw_b64 = item.get("data")
        if not raw_b64:
            continue

        try:
            zip_bytes = base64.b64decode(raw_b64)
        except Exception as e:
            print(f"  ⚠️ Base64 decode failed: {e}")
            continue

        try:
            archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except Exception as e:
            print(f"  ⚠️ Corrupt ZIP archive: {e}")
            continue

        with archive:
            for file_path in archive.namelist():
                if not file_path.lower().endswith(".gml"):
                    continue

                summary["harvested"] += 1
                try:
                    raw_gml = archive.read(file_path).decode("utf-8", errors="replace")
                except Exception as e:
                    print(f"  ⚠️ Could not read GML file {file_path}: {e}")
                    continue

                # 1. Primary: Extract locally
                local_data = local_s124_extractor(raw_gml, file_path)
                final_geometry = local_data.get("geojson_geometry")
                final_text = local_data.get("warning_text") or ""
                warning_no = local_data.get("warning_number")
                general_area = local_data.get("general_area")
                warning_type = local_data.get("warning_type")
                pub_time = local_data.get("publication_time")
                cancel_time = local_data.get("cancellation_date")
                dataset_id = local_data.get("dataset_id")

                used_ai = False
                # 2. Backup Trigger: If no coordinates or critical text found, invoke Gemini Flash-Lite
                if (not final_geometry or not final_text) and ai_client:
                    summary["fallback_used"] += 1
                    used_ai = True
                    ai_backup = gemini_flash_lite_backup(raw_gml)
                    if ai_backup:
                        if not final_geometry and ai_backup.geojson_geometry:
                            final_geometry = ai_backup.geojson_geometry
                        if not final_text and ai_backup.warning_text:
                            final_text = ai_backup.warning_text
                        if not warning_no and ai_backup.warning_number:
                            warning_no = ai_backup.warning_number
                        if not general_area and ai_backup.general_area:
                            general_area = ai_backup.general_area
                        if not warning_type and ai_backup.warning_type:
                            warning_type = ai_backup.warning_type
                        if not pub_time and ai_backup.publication_time:
                            pub_time = ai_backup.publication_time
                        if not cancel_time and ai_backup.cancellation_date:
                            cancel_time = ai_backup.cancellation_date

                # 3. Format adapted record for nav_warnings
                adapted_warn = adapt_to_nav_warnings(
                    dataset_id=dataset_id,
                    warning_number=warning_no,
                    warning_type=warning_type,
                    general_area=general_area,
                    publication_time=pub_time,
                    cancellation_date=cancel_time,
                    warning_text=final_text,
                    geojson_geometry=final_geometry,
                    raw_payload=raw_gml,
                    used_ai=used_ai,
                )

                # 4. Upsert to Supabase
                if supabase and not dry_run:
                    try:
                        # Primary target: nav_warnings
                        supabase.table("nav_warnings").upsert(
                            adapted_warn, on_conflict="warning_id,source_id"
                        ).execute()
                        summary["synced"] += 1
                        print(f"  ✨ Synced to nav_warnings: {adapted_warn['warning_id']} (Geo: {bool(final_geometry)})")
                    except Exception as e:
                        print(f"  ❌ Error syncing {adapted_warn['warning_id']} to nav_warnings: {e}")

                    # Optional dual-write to navarea_warnings if table exists
                    try:
                        legacy_record = {
                            "dataset_id": dataset_id,
                            "navarea": "NAVAREA II",
                            "service_instance": SERVICE_INSTANCE,
                            "warning_number": warning_no,
                            "warning_type": warning_type,
                            "general_area": general_area,
                            "publication_time": pub_time,
                            "cancellation_date": cancel_time,
                            "warning_text": final_text,
                            "geojson_geometry": final_geometry,
                            "raw_payload": raw_gml,
                            "source_method": "SECOM_S124_HYBRID",
                        }
                        supabase.table("navarea_warnings").upsert(
                            legacy_record, on_conflict="dataset_id"
                        ).execute()
                    except Exception:
                        pass
                else:
                    summary["synced"] += 1
                    status_note = "[DRY-RUN]" if dry_run else "[NO-DB]"
                    print(f"  🔍 {status_note} Processed {adapted_warn['warning_id']} (Type: {warning_type}, Geom: {bool(final_geometry)})")

    if server_errors:
        print(f"⚠️ Server reported response notices: {server_errors}")

    print("\n" + "=" * 70)
    print(f"📊 Summary: Harvested {summary['harvested']} S-124 files | Synced: {summary['synced']} | Gemini Fallbacks: {summary['fallback_used']}")
    print("=" * 70)
    return summary


if __name__ == "__main__":
    res = run_navarea_ii_pipeline()
    sys.exit(0)
