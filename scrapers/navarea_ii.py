#!/usr/bin/env python3
"""
scrapers/navarea_ii.py — NAVAREA II S-124 NW v2 Ingestion Pipeline
Ingests raw S-124 (Ed. 2.0) Exchange Set GML from the PING 'Get_NW_Messages' v2
REST API (English NAVAREA II series), using local XML extraction with a
Gemini 2.5 Flash-Lite backup for robust geometry recovery, and adapts
notices into Supabase nav_warnings.

Source endpoint:
  https://services.ping-info-nautique.fr/nw/v2/Get_NW_Messages?nameOfSeries=NAVAREA%20II&lang=en
"""

import os
import sys
import json
import hashlib
import re
from typing import Optional, Dict, Any, List, Tuple
import xml.etree.ElementTree as ET

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Scrapling Fetcher: stealthy HTTP client with retries/impersonation (https://github.com/D4Vinci/Scrapling)
try:
    from scrapling.fetchers import Fetcher
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False

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

# Shared helpers
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

NW_MESSAGES_URL = (
    "https://services.ping-info-nautique.fr/nw/v2/Get_NW_Messages"
    "?nameOfSeries=NAVAREA%20II&lang=en"
)
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


def fetch_nw_messages_gml() -> str:
    """
    Fetches the raw S-124 Exchange Set GML from the PING NW v2 API.

    Primary path uses Scrapling's Fetcher (https://github.com/D4Vinci/Scrapling),
    a stealthy HTTP client with built-in retries, TLS impersonation and adaptive
    header generation. Falls back to plain `requests` if Scrapling is unavailable.
    """
    headers = {"accept": "application/xml, text/xml, */*"}

    if HAS_SCRAPLING:
        try:
            print("[1/4] Querying PING NW v2 API via Scrapling Fetcher...")
            page = Fetcher.get(
                NW_MESSAGES_URL,
                headers=headers,
                timeout=60,
                retries=3,
                stealthy_headers=True,
            )
            if getattr(page, "status", None) != 200:
                raise RuntimeError(f"HTTP {page.status} from PING NW v2 endpoint")
            body = page.body
            if isinstance(body, bytes):
                return body.decode("utf-8", errors="replace")
            return str(body)
        except Exception as e:
            print(f"⚠️ Scrapling fetch failed ({e}); falling back to requests...")

    if not HAS_REQUESTS:
        raise RuntimeError("Neither Scrapling nor 'requests' is installed. Run: pip install -r requirements.txt")

    print("[1/4] Querying PING NW v2 API (requests fallback)...")
    resp = requests.get(NW_MESSAGES_URL, headers=headers, timeout=60)
    resp.raise_for_status()
    if isinstance(resp.content, bytes):
        return resp.content.decode("utf-8", errors="replace")
    return resp.text


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


def find_text(elem: ET.Element, tag_name: str) -> Optional[str]:
    """Finds first descendant element (namespace-agnostic) with the given local tag and returns stripped text."""
    for node in elem.iter():
        if strip_ns(node.tag) == tag_name:
            if node.text and node.text.strip():
                return node.text.strip()
    return None


def find_all_texts(elem: ET.Element, tag_name: str) -> List[str]:
    texts = []
    for node in elem.iter():
        if strip_ns(node.tag) == tag_name:
            if node.text and node.text.strip():
                texts.append(node.text.strip())
    return texts


def parse_geometry_from_dataset(dataset_elem: ET.Element) -> Optional[Dict[str, Any]]:
    """
    Parses S-124/S-100 geometry (Point, Curve, or Surface) from a dataset element.
    GML pos/posList pairs are 'latitude longitude' — inverted to GeoJSON '[lon, lat]'.
    """
    geom_type: Optional[str] = None
    pos_values: List[float] = []

    for node in dataset_elem.iter():
        tag = strip_ns(node.tag)
        if tag in ("Surface", "PolygonPatch"):
            geom_type = "Polygon"
        elif tag in ("Point",) and geom_type is None:
            geom_type = "Point"
        elif tag in ("Curve", "LineString", "LineStringSegment") and geom_type not in ("Polygon",):
            geom_type = "LineString"
        elif tag in ("posList", "pos", "coordinates"):
            if node.text:
                # Robust against arbitrary whitespace/newlines inside the list
                pos_values = [float(x) for x in re.split(r"\s+", node.text.strip()) if x]
            break  # geometry found; stop scanning

    if not pos_values or len(pos_values) < 2:
        return None

    if len(pos_values) % 2 != 0:
        pos_values = pos_values[:-1]  # drop trailing unpaired value

    coordinates: List[List[float]] = []
    it = iter(pos_values)
    for lat, lon in zip(it, it):
        coordinates.append([lon, lat])

    if geom_type == "Polygon" and len(coordinates) >= 3:
        ring = list(coordinates)
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}
    if (geom_type == "Point" or len(coordinates) == 1) and coordinates:
        return {"type": "Point", "coordinates": coordinates[0]}
    if coordinates:
        return {"type": "LineString", "coordinates": coordinates}
    return None


def parse_nw_exchange_set(gml_content: str) -> List[Dict[str, Any]]:
    """
    Parses a PING NW v2 S-124 Exchange Set GML payload into per-warning records.
    The payload is a single <S124:ExchangeSet> containing multiple <S124:Dataset>
    elements (one per navigational warning).
    """
    results: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(gml_content)
    except ET.ParseError as e:
        print(f"⚠️ XML parse error on NW v2 payload: {e}")
        return results

    datasets = [node for node in root.iter() if strip_ns(node.tag) == "Dataset"]
    if not datasets:
        # Payload may be a single Dataset rather than an ExchangeSet wrapper
        if strip_ns(root.tag) == "Dataset":
            datasets = [root]
        else:
            return results

    for dataset in datasets:
        gml_id = dataset.attrib.get("{http://www.opengis.net/gml/3.2}id", "") or dataset.attrib.get("id", "")
        dataset_title = find_text(dataset, "datasetTitle") or ""

        warning_number = find_text(dataset, "warningNumber")
        year = find_text(dataset, "year")
        warning_type = find_text(dataset, "warningType")
        general_area = find_text(dataset, "locationName") or find_text(dataset, "text")
        # Prefer preamble locationName; avoid overwriting with information text below

        pub_time = find_text(dataset, "publicationTime")
        cancel_time = find_text(dataset, "cancellationDate")

        # Detailed type categories (e.g. 'Special Operations', 'Firing Exercise')
        detail_types = find_all_texts(dataset, "navwarnTypeDetails") + find_all_texts(dataset, "navwarnTypeGeneral")
        if detail_types:
            type_str = " / ".join(dict.fromkeys(detail_types))
            warning_type = f"{warning_type} - {type_str}" if warning_type else type_str

        # Body text: all <S124:text> under warning information blocks
        # (skip the language tags already consumed via locationName logic)
        text_parts: List[str] = []
        for info_node in dataset.iter():
            if strip_ns(info_node.tag) == "information":
                for node in info_node.iter():
                    if strip_ns(node.tag) == "text" and node.text and node.text.strip():
                        if node.text.strip() not in text_parts:
                            text_parts.append(node.text.strip())

        geometry = parse_geometry_from_dataset(dataset)

        # Canonical warning id: '360/26' from warningNumber + year (or dataset title)
        warning_id = None
        m = re.search(r"(\d{1,4})\s*/\s*(\d{2,4})", dataset_title or "")
        if m:
            warning_id = f"{int(m.group(1))}/{m.group(2)}"
        elif warning_number:
            warning_id = f"{warning_number}/{year[-2:]}" if year else warning_number

        results.append({
            "dataset_id": gml_id or dataset_title or warning_id or "",
            "warning_id": warning_id,
            "warning_number": warning_id,
            "warning_type": warning_type,
            "general_area": general_area,
            "publication_time": pub_time,
            "cancellation_date": cancel_time,
            "warning_text": "\n".join(text_parts).strip(),
            "geojson_geometry": geometry,
            "dataset_xml": ET.tostring(dataset, encoding="unicode"),
        })

    return results


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
    dataset_id: str = "",
    warning_number: Optional[str] = None,
    warning_type: Optional[str] = None,
    general_area: Optional[str] = None,
    publication_time: Optional[str] = None,
    cancellation_date: Optional[str] = None,
    warning_text: str = "",
    geojson_geometry: Optional[Dict[str, Any]] = None,
    raw_payload: str = "",
    used_ai: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Adapts an S-124 extracted notice into schema-compliant master payload and child geometries.
    Conforms to the 20261019/20261020 PostgreSQL/Supabase schema.
    """
    raw_num = str(warning_number or "")
    num_match = re.search(r"(\d+/\d+)", raw_num)
    if num_match:
        warning_id = num_match.group(1)
    elif dataset_id:
        match = re.search(r"0*(\d{1,4})(\d{2})[A-Za-z]?$", dataset_id)
        warning_id = f"{int(match.group(1))}/{match.group(2)}" if match else dataset_id
    else:
        warning_id = raw_num or "UNKNOWN"

    area = general_area or "ATLANTIC"
    title = f"NAVAREA II {warning_id} - {area}"
    if warning_type and warning_type not in area:
        title = f"{title} - {warning_type}"

    lat, lon, coord_str = compute_centroid(geojson_geometry)
    categories = classify_hazard_categories(f"{warning_type or ''} {warning_text}")
    canonical_id = f"NAVAREA II {warning_id}"

    record = {
        "warning_id": warning_id,
        "canonical_id": canonical_id,
        "source_id": SOURCE_ID,
        "navarea": "NAVAREA II",
        "title": title[:255],
        "coordinates": coord_str,
        "latitude": lat,
        "longitude": lon,
        "categories": categories,
        "status": "cancelled" if cancellation_date else "active",
        "valid_from": parse_safe_iso_timestamp(publication_time),
        "valid_to": parse_safe_iso_timestamp(cancellation_date),
        "raw_text": warning_text or raw_payload[:1000],
        "spatial": geojson_geometry,
    }

    master_payload = build_master_payload(record)
    geom_payloads = build_geometry_payloads(record)
    record["_master"] = master_payload
    record["_geoms"] = geom_payloads
    record["geometries"] = geom_payloads

    return record, geom_payloads


def run_navarea_ii_pipeline(
    mock_gml: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Executes the NAVAREA II ingestion pipeline:
    1. Fetches or accepts the PING NW v2 S-124 Exchange Set GML (Scrapling primary, requests fallback)
    2. Parses all <S124:Dataset> warning entries locally
    3. Falls back to Gemini Flash-Lite per-warning if geometry or text is missing
    4. Upserts normalized records into Supabase nav_warnings
    """
    print("=" * 70)
    print("⚓ NAVAREA II S-124 NW v2 Ingestion Pipeline")
    print(f"📡 Endpoint: {NW_MESSAGES_URL}")
    print(f"🔌 Fetcher: {'Scrapling' if HAS_SCRAPLING else ('requests' if HAS_REQUESTS else 'none')}")
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

    gml_content = mock_gml
    if gml_content is None:
        if not HAS_REQUESTS and not HAS_SCRAPLING:
            print("❌ No HTTP client available. Please run: pip install -r requirements.txt")
            summary["server_errors"] = "no HTTP client (requests/Scrapling) available"
            return summary
        try:
            gml_content = fetch_nw_messages_gml()
        except Exception as e:
            print(f"❌ Failed to reach PING NW v2 endpoint: {e}")
            summary["server_errors"] = str(e)
            return summary

    print("[2/4] Parsing S-124 Exchange Set...")
    warnings = parse_nw_exchange_set(gml_content)
    summary["total_items"] = len(warnings)
    summary["harvested"] = len(warnings)
    print(f"[2/4] Parsed {len(warnings)} NAVAREA II warning datasets")

    print("[3/4] Processing warnings...")
    for w in warnings:
        dataset_id = w.get("dataset_id", "")
        warning_no = w.get("warning_number")
        general_area = w.get("general_area")
        warning_type = w.get("warning_type")
        pub_time = w.get("publication_time")
        cancel_time = w.get("cancellation_date")
        final_text = w.get("warning_text") or ""
        final_geometry = w.get("geojson_geometry")
        dataset_xml = w.get("dataset_xml", "")

        used_ai = False
        # Backup Trigger: if no coordinates or critical text found, invoke Gemini Flash-Lite
        if (not final_geometry or not final_text) and ai_client:
            summary["fallback_used"] += 1
            used_ai = True
            ai_backup = gemini_flash_lite_backup(dataset_xml)
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

        # Format adapted record for nav_warnings
        adapted_warn, geoms = adapt_to_nav_warnings(
            dataset_id=dataset_id,
            warning_number=warning_no,
            warning_type=warning_type,
            general_area=general_area,
            publication_time=pub_time,
            cancellation_date=cancel_time,
            warning_text=final_text,
            geojson_geometry=final_geometry,
            raw_payload=dataset_xml,
            used_ai=used_ai,
        )
        master = adapted_warn["_master"]

        # Upsert to Supabase
        if supabase and not dry_run:
            try:
                checksum = hashlib.sha256(dataset_xml.encode("utf-8")).hexdigest()
                supabase.table("raw_messages").insert({
                    "warning_id": warning_no or master["canonical_id"],
                    "source_id": SOURCE_ID,
                    "subject_header": master["title"][:100],
                    "full_raw_text": dataset_xml,
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
    print(f"📊 Summary: Harvested {summary['harvested']} S-124 warnings | Synced: {summary['synced']} | Gemini Fallbacks: {summary['fallback_used']}")
    print("=" * 70)

    # Write to GitHub Actions Step Summary if available
    step_summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_file:
        try:
            with open(step_summary_file, "a", encoding="utf-8") as sf:
                sf.write(f"""### ⚓ NAVAREA II S-124 NW v2 Ingestion Summary
| Metric | Value |
| :--- | :--- |
| **Endpoint** | `{NW_MESSAGES_URL}` |
| **HTTP Fetcher** | `{'Scrapling' if HAS_SCRAPLING else 'requests'}` |
| **Warning Datasets Parsed** | `{summary['total_items']}` |
| **Notices Synced** | `{summary['synced']}` |
| **Gemini Flash-Lite Fallbacks** | `{summary['fallback_used']}` |
| **Execution Mode** | `{"Dry-Run / Offline" if summary['dry_run'] else "Supabase Live"}` |
""")
                if summary["server_errors"]:
                    sf.write(f"\n> ⚠️ **Server Notice:** {summary['server_errors']}\n")
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
