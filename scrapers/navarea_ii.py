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
            inst = cls()
            for k, v in data.items():
                if k == "coordinates" and isinstance(v, list):
                    v = [CoordinatePair(**item) if isinstance(item, dict) else item for item in v]
                setattr(inst, k, v)
            return inst
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
import hashlib
from shared.models import build_master_payload, build_geometry_payloads, parse_safe_iso_timestamp
from shared.sync_engine import upsert_warning_atomic

try:
    from shared.utils import classify_hazard, classify_hazard_categories

except ImportError:
    def classify_hazard_categories(text: str) -> list[str]:
        t = text.lower()
        cats = []
        if any(w in t for w in ["gps", "dgps", "ais", "navtex", "radar"]):
            cats.append("electronic")
        if any(w in t for w in ["firing", "gunnery", "exercise", "military", "torpedo", "rocket"]):
            cats.append("military")
        if any(w in t for w in ["light", "buoy", "beacon", "aton", "unlit", "damaged"]):
            cats.append("aton")
        if any(w in t for w in ["cable", "pipe", "submarine", "subsea", "diver"]):
            cats.append("subsea")
        if any(w in t for w in ["drifting", "derelict", "hazard", "mine"]):
            cats.append("drifting")
        if any(w in t for w in ["rig", "platform", "drill", "survey", "seismic"]):
            cats.append("offshore")
        return cats if cats else ["general"]

    def classify_hazard(text: str) -> str:
        return classify_hazard_categories(text)[0]


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
class CoordinatePair(BaseModel):
    longitude: float = Field(description="Longitude in decimal degrees")
    latitude: float = Field(description="Latitude in decimal degrees")


class S124BackupSchema(BaseModel):
    warning_number: Optional[str] = Field(default=None, description="Notice number, e.g., '359/26'")
    general_area: Optional[str] = Field(default=None, description="Broad geographic locality, e.g., 'BAY OF BISCAY'")
    warning_type: Optional[str] = Field(default=None, description="Category or nature of the maritime hazard")
    publication_time: Optional[str] = Field(default=None, description="ISO 8601 publication or start timestamp")
    cancellation_date: Optional[str] = Field(default=None, description="ISO 8601 cancellation timestamp or null")
    warning_text: str = Field(default="", description="Full plain body text of the navigational warning")
    geometry_type: Optional[str] = Field(default=None, description="'Point', 'LineString', or 'Polygon'")
    coordinates: Optional[List[CoordinatePair]] = Field(
        default=None,
        description="List of point coordinates in decimal degrees (longitude, latitude)",
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


def gemini_flash_lite_backup(gml_content: str) -> Optional[Dict[str, Any]]:
    """
    Intelligent backup parser using Gemini 2.5 Flash-Lite when local extraction
    lacks geometry, encounters complex GML nesting, or fails on irregular formatting.
    Uses explicit Pydantic schema to avoid additional_properties error.
    """
    if not ai_client:
        return None

    try:
        print("    [!] Local parser lacked geometry; invoking Gemini 2.5 Flash-Lite fallback...")
        prompt = (
            "Extract the warning details and boundary geometry coordinates from this GML XML:\n\n"
            + gml_content[:15000]
        )

        response = ai_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=S124BackupSchema,
                temperature=0.0,
            ),
        )
        if not response.text:
            return None

        data = S124BackupSchema.model_validate_json(response.text)

        # Reconstruct GeoJSON geometry safely
        geojson_geom = None
        if data.coordinates and data.geometry_type:
            raw_pts = []
            for pt in data.coordinates:
                if hasattr(pt, "longitude") and hasattr(pt, "latitude"):
                    raw_pts.append([pt.longitude, pt.latitude])
                elif isinstance(pt, dict):
                    raw_pts.append([pt.get("longitude"), pt.get("latitude")])
                elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    raw_pts.append([pt[0], pt[1]])

            gtype = (data.geometry_type or "").strip().lower()
            if gtype == "point" and raw_pts:
                geojson_geom = {"type": "Point", "coordinates": raw_pts[0]}
            elif gtype == "polygon" and raw_pts:
                # Close the polygon ring if not closed
                if raw_pts[0] != raw_pts[-1]:
                    raw_pts.append(raw_pts[0])
                geojson_geom = {"type": "Polygon", "coordinates": [raw_pts]}
            elif gtype in ("linestring", "curve") and raw_pts:
                geojson_geom = {"type": "LineString", "coordinates": raw_pts}

        return {
            "warning_number": data.warning_number,
            "general_area": data.general_area,
            "warning_type": data.warning_type,
            "publication_time": data.publication_time,
            "cancellation_date": data.cancellation_date,
            "warning_text": data.warning_text,
            "geojson_geometry": geojson_geom,
        }
    except Exception as e:
        print(f"    [!] Gemini Flash-Lite fallback error: {e}")
        return None


def compute_centroid(geojson_geometry: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Calculates center latitude, longitude, and formatted coordinate string (e.g. 46.5000N 004.2500W)."""
    if not geojson_geometry:
        return None, None, None

    gtype = geojson_geometry.get("type")
    coords = geojson_geometry.get("coordinates")
    lat: Optional[float] = None
    lon: Optional[float] = None

    if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        lon, lat = round(float(coords[0]), 4), round(float(coords[1]), 4)
    elif gtype in ("Polygon", "LineString") and coords:
        pts = coords[0] if gtype == "Polygon" else coords
        if pts and isinstance(pts, list):
            valid_pts = [p for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
            if valid_pts:
                avg_lon = sum(float(p[0]) for p in valid_pts) / len(valid_pts)
                avg_lat = sum(float(p[1]) for p in valid_pts) / len(valid_pts)
                lon, lat = round(avg_lon, 4), round(avg_lat, 4)

    coord_str = None
    if lat is not None and lon is not None:
        coord_str = f"{abs(lat):.4f}{'N' if lat >= 0 else 'S'} {abs(lon):08.4f}{'E' if lon >= 0 else 'W'}"

    return lat, lon, coord_str


def adapt_to_nav_warnings(
    local_or_ai_data: Any = None,
    raw_gml_text: str = "",
    used_ai: bool = False,
    **kwargs
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Adapts S-124 extracted notice into schema-compliant master payload and child geometries.
    Conforms to the 20261019/20261020 PostgreSQL/Supabase schema.
    """
    import re
    if isinstance(local_or_ai_data, dict):
        raw_num = str(local_or_ai_data.get("warning_number") or "")
        dataset_id = local_or_ai_data.get("dataset_id", "")
        body_text = local_or_ai_data.get("warning_text") or ""
        general_area = local_or_ai_data.get("general_area") or "ATLANTIC"
        warning_type = local_or_ai_data.get("warning_type")
        pub_time = local_or_ai_data.get("publication_time")
        cancel_time = local_or_ai_data.get("cancellation_date")
        spatial = local_or_ai_data.get("geojson_geometry")
        raw_gml = raw_gml_text or local_or_ai_data.get("raw_payload", "")
    else:
        dataset_id = str(local_or_ai_data or kwargs.get("dataset_id", ""))
        raw_num = str(kwargs.get("warning_number") or "")
        warning_type = kwargs.get("warning_type")
        general_area = kwargs.get("general_area") or "ATLANTIC"
        pub_time = kwargs.get("publication_time")
        cancel_time = kwargs.get("cancellation_date")
        body_text = kwargs.get("warning_text") or ""
        spatial = kwargs.get("geojson_geometry")
        raw_gml = raw_gml_text or kwargs.get("raw_payload", "")

    num_match = re.search(r"(\d+/\d+)", raw_num)
    if num_match:
        warning_id = num_match.group(1)
    elif dataset_id:
        match = re.search(r"0*(\d{1,4})(\d{2})[A-Za-z]?$", dataset_id)
        warning_id = f"{int(match.group(1))}/{match.group(2)}" if match else dataset_id
    else:
        warning_id = raw_num or "UNKNOWN"

    title = f"NAVAREA II {warning_id} - {general_area}"
    if warning_type and warning_type not in general_area:
        title = f"{title} - {warning_type}"

    lat, lon, coord_str = compute_centroid(spatial)
    categories = classify_hazard_categories(f"{warning_type or ''} {body_text}")
    canonical_id = f"NAVAREA II {warning_id}"

    record = {
        "warning_id": warning_id,
        "canonical_id": canonical_id,
        "source_id": SOURCE_ID,
        "navarea": "NAVAREA II",
        "title": title[:255],
        # Human-readable coordinate string (falls back to title area)
        "coordinates": coord_str,
        # lat/lon/spatial are consumed by build_master_payload / build_geometry_payloads
        "latitude": lat,
        "longitude": lon,
        "categories": categories,
        "status": "cancelled" if cancel_time else "active",
        "valid_from": parse_safe_iso_timestamp(pub_time),
        "valid_to": parse_safe_iso_timestamp(cancel_time),
        "raw_text": body_text or raw_gml[:1000],
        "spatial": spatial,
    }

    master_payload = build_master_payload(record)
    geom_payloads = build_geometry_payloads(record)
    record["_master"] = master_payload
    record["_geoms"] = geom_payloads
    record["geometries"] = geom_payloads

    return record




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
        "sync_errors": 0,
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
                        if not final_geometry and ai_backup.get("geojson_geometry"):
                            final_geometry = ai_backup["geojson_geometry"]
                        if not final_text and ai_backup.get("warning_text"):
                            final_text = ai_backup["warning_text"]
                        if not warning_no and ai_backup.get("warning_number"):
                            warning_no = ai_backup["warning_number"]
                        if not general_area and ai_backup.get("general_area"):
                            general_area = ai_backup["general_area"]
                        if not warning_type and ai_backup.get("warning_type"):
                            warning_type = ai_backup["warning_type"]
                        if not pub_time and ai_backup.get("publication_time"):
                            pub_time = ai_backup["publication_time"]
                        if not cancel_time and ai_backup.get("cancellation_date"):
                            cancel_time = ai_backup["cancellation_date"]

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
                master = adapted_warn["_master"]
                geoms = adapted_warn["_geoms"]


                # 4. Upsert to Supabase
                if supabase and not dry_run:
                    try:
                        checksum = hashlib.sha256(raw_gml.encode("utf-8")).hexdigest()
                        supabase.table("raw_messages").insert({
                            "warning_id": warning_no or master["canonical_id"],
                            "source_id": SOURCE_ID,
                            "subject_header": master["title"][:100],
                            "full_raw_text": raw_gml,
                            "checksum_sha256": checksum,
                        }).execute()
                    except Exception as e:
                        if "duplicate key" not in str(e).lower():
                            print(f"  ⚠️ [raw_messages] {warning_no}: {e}")

                    success = upsert_warning_atomic(supabase, master, geoms)
                    if success:
                        summary["synced"] += 1
                        print(f"  ✨ Synced: {master['canonical_id']} (Triage: {master['triage_tier']}, Geoms: {len(geoms)})")
                    else:
                        print(f"  ❌ Error syncing {master['canonical_id']} via RPC")
                        summary["sync_errors"] += 1
                else:
                    summary["synced"] += 1
                    status_note = "[DRY-RUN]" if dry_run else "[NO-DB]"
                    print(f"  🔍 {status_note} Processed {master['canonical_id']} (Triage: {master['triage_tier']}, Geoms: {len(geoms)})")


    print("\n" + "=" * 70)
    print(f"📊 Summary: Harvested {summary['harvested']} S-124 files | Synced: {summary['synced']} | Gemini Fallbacks: {summary['fallback_used']}")
    print("=" * 70)

    # Write to GitHub Actions Step Summary if available
    step_summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_file:
        try:
            with open(step_summary_file, "a", encoding="utf-8") as sf:
                sf.write(f"""### ⚓ NAVAREA II S-124 SECOM Ingestion Summary
| Metric | Value |
| :--- | :--- |
| **Endpoint** | `{PING_OBJECT_URL}` |
| **Total Items Reported** | `{summary['total_items']}` |
| **S-124 GML Harvested** | `{summary['harvested']}` |
| **Notices Synced** | `{summary['synced']}` |
| **Gemini Flash-Lite Fallbacks** | `{summary['fallback_used']}` |
| **Execution Mode** | `{"Dry-Run / Offline" if summary['dry_run'] else "Supabase Live"}` |
""")
                if server_errors:
                    sf.write(f"\n> ⚠️ **Server Notice:** {server_errors}\n")
        except Exception:
            pass

    return summary


if __name__ == "__main__":
    res = run_navarea_ii_pipeline()
    if res.get("server_errors") or res.get("sync_errors"):
        sys.exit(1)  # regional failure
    if res.get("dry_run") and not res.get("harvested"):
        sys.exit(2)  # credentials/env missing and nothing processed
    sys.exit(0)
