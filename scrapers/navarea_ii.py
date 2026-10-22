#!/usr/bin/env python3
"""
scrapers/navarea_ii.py — NAVAREA II S-124 SECOM Ingestion Pipeline
Ingests S-124 (Ed. 2.0) nautical datasets packaged inside S-100 Exchange Sets
via IEC 63173-2 (SECOM) REST API or the public Get_NW_Messages XML endpoint,
using rule-first local XML extraction (no AI fallback — geometry-less warnings
triage to Tier C) and adapts notices into Supabase nav_warnings.
"""

import os
import io
import re
import sys
import base64
import zipfile
import hashlib
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

# Ensure root directory is on Python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Configure output encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Attempt Supabase client import
try:
    from supabase import create_client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

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
PING_SECOM_API_KEY = os.environ.get("PING_SECOM_API_KEY", "")

SERVICE_INSTANCE = "navarea_ii_en"
PING_OBJECT_URL = f"https://services.ping-info-nautique.fr/secom/{SERVICE_INSTANCE}/v1/object"
SOURCE_ID = "shom-navarea-2"  # NAVAREA II (Metarea II / SHOM PING service)
MAX_PAGES = 20  # safety cap for pagination following

# Public (unauthenticated) NAVAREA II S-124 Exchange Set endpoint (English series).
# Serves the same S-124 GML warnings as the keyed SECOM API, as a single XML document.
NW_MESSAGES_URL = "https://services.ping-info-nautique.fr/nw/v2/Get_NW_Messages?nameOfSeries=NAVAREA%20II&lang=en"
NW_SERIES_FILTER = "NAVAREA_II"  # keep only NAVAREA II datasets from the exchange set
NW_BROWSER_HEADERS = {
    "accept": "text/xml,application/xml;q=0.9,*/*;q=0.8",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "referer": "https://portail.ping-info-nautique.fr/",
    "accept-language": "en,fr;q=0.8",
}

# --- Client Initializations ---
supabase: Optional[Any] = None
if HAS_SUPABASE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"⚠️ Supabase client initialization warning: {e}")


# --- PING SECOM request helpers ---

def build_ping_headers() -> Dict[str, str]:
    """
    Builds request headers for the PING SECOM REST API.
    Sends the API key defensively as both an X-API-Key and an Authorization Bearer
    header, since PING gateway deployments vary in which scheme they accept.
    """
    headers = {
        "accept": "application/json",
        "user-agent": "Helm.Warning.Backend/1.0 (NAVAREA II S-124 ingestion)",
    }
    if PING_SECOM_API_KEY:
        headers["x-api-key"] = PING_SECOM_API_KEY
        headers["authorization"] = f"Bearer {PING_SECOM_API_KEY}"
    return headers


def extract_next_link(payload: Dict[str, Any]) -> Optional[str]:
    """Extracts the 'next' pagination href from a SECOM responseLink entry."""
    links = payload.get("responseLink")
    if isinstance(links, dict):
        links = [links]
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        href = link.get("href")
        rel = str(link.get("rel") or "").lower()
        if href and rel == "next":
            return href
    return None


def fetch_ping_payloads() -> Tuple[List[Dict[str, Any]], str]:
    """
    Fetches all pages of the PING SECOM /object response, following
    responseLink rel="next" pagination links when present.
    Returns (list_of_payloads, server_notice_text).
    On a hard failure, returns ([], error_description).
    """
    payloads: List[Dict[str, Any]] = []
    server_notice = ""
    next_url: Optional[str] = PING_OBJECT_URL
    pages = 0

    while next_url and pages < MAX_PAGES:
        try:
            resp = requests.get(next_url, headers=build_ping_headers(), timeout=45)
        except Exception as e:
            print(f"❌ Request to PING SECOM failed: {e}")
            return payloads, f"request failed: {e}"

        if resp.status_code != 200:
            body_snippet = (resp.text or "")[:300].replace("\n", " ")
            print(f"❌ PING SECOM returned HTTP {resp.status_code} for {next_url}")
            print(f"   Response body (first 300 chars): {body_snippet}")
            return payloads, f"HTTP {resp.status_code}: {body_snippet}"

        try:
            payload = resp.json()
        except Exception as e:
            print(f"❌ PING SECOM returned non-JSON body: {e}")
            print(f"   Response body (first 300 chars): {(resp.text or '')[:300]}")
            return payloads, f"invalid JSON response: {e}"

        pages += 1
        payloads.append(payload)
        items = payload.get("dataResponseObject") or []
        notice = payload.get("responseText") or ""
        if notice:
            server_notice = notice
        print(f"  ↳ Page {pages}: {len(items)} Exchange Set(s){' (server: ' + notice + ')' if notice else ''}")

        next_url = extract_next_link(payload)

    if pages >= MAX_PAGES and next_url:
        print(f"⚠️ Stopped after {MAX_PAGES} pages; more pages remain ({next_url})")

    return payloads, server_notice


# --- Public Get_NW_Messages XML exchange set helpers ---

def fetch_nw_exchange_set() -> Tuple[Optional[str], str]:
    """
    Fetches the public NAVAREA II S-124 Exchange Set XML (Get_NW_Messages, English).
    Uses Scrapling's stealthy Fetcher when available, plain requests otherwise.
    Returns (xml_text, error). xml_text is None on failure.
    """
    text = ""

    if HAS_SCRAPLING:
        try:
            page = Fetcher.get(
                NW_MESSAGES_URL,
                headers=NW_BROWSER_HEADERS,
                timeout=45,
                retries=3,
                stealthy_headers=True,
            )
            status = getattr(page, "status", None)
            body = page.body
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            text = str(body or "")
            if status != 200:
                snippet = text[:200].replace("\n", " ")
                print(f"⚠️ Get_NW_Messages returned HTTP {status}: {snippet}")
                return None, f"HTTP {status}: {snippet}"
        except Exception as e:
            print(f"⚠️ Scrapling fetch failed ({e}); falling back to requests...")
            text = ""

    if not text:
        try:
            resp = requests.get(NW_MESSAGES_URL, headers=NW_BROWSER_HEADERS, timeout=45)
        except Exception as e:
            return None, f"request failed: {e}"

        if resp.status_code != 200:
            snippet = (resp.text or "")[:200].replace("\n", " ")
            print(f"⚠️ Get_NW_Messages returned HTTP {resp.status_code}: {snippet}")
            return None, f"HTTP {resp.status_code}: {snippet}"

        text = resp.text or ""

    if "ExchangeSet" not in text:
        print(f"⚠️ Get_NW_Messages response did not contain an S-124 ExchangeSet: {text[:200]}")
        return None, "response did not contain an S-124 ExchangeSet"

    return text, ""


def parse_nw_datasets(xml_text: str) -> Tuple[List[Tuple[str, str]], str]:
    """
    Splits an S-124 ExchangeSet document into individual warning datasets,
    keeping only NAVAREA II ones.
    Returns (list_of_(gml_id, dataset_xml), error).
    """
    results: List[Tuple[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        return results, f"XML parse error: {e}"

    for child in root:
        if strip_ns(child.tag) != "Dataset":
            continue
        gml_id = child.attrib.get("{http://www.opengis.net/gml/3.2}id", "")
        if NW_SERIES_FILTER not in gml_id:
            continue  # skip other NAVAREA series if present
        dataset_xml = ET.tostring(child, encoding="unicode")
        results.append((gml_id or "NW.NAVAREA_II.DATASET", dataset_xml))

    return results, ""


def exchange_set_to_payload_items(datasets: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """
    Packages each parsed dataset as a base64-encoded, single-entry ZIP archive —
    the exact payload shape the SECOM /object endpoint delivers — so the
    downstream decode/unzip/extract pipeline is fully reused.
    """
    items: List[Dict[str, Any]] = []
    for gml_id, xml_text in datasets:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{gml_id.replace('/', '_')}.gml", xml_text)
        items.append({"data": base64.b64encode(buf.getvalue()).decode("ascii")})
    return items


def strip_ns(tag: str) -> str:
    """Removes XML namespace prefix from tag if present."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def local_s124_extractor(gml_content: str, filename: str = "dataset.gml") -> Dict[str, Any]:
    """
    Primary local zero-latency extractor for S-124 GML XML datasets.
    Extracts text descriptions, warning attributes, and parses vector geometry,
    inverting GML lat-lon coordinate ordering to GeoJSON standard [lon, lat].
    No AI fallback: warnings without geometry downstream-triage to Tier C.
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
        elif tag in ("Point",) and not geom_type:
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

    # If warning_number was not explicitly tagged, attempt regex search in text.
    # Guard: skip numbers that belong to CANCEL references ("CANCEL 215/26") so
    # the cancelled warning's number is never misattributed to this dataset.
    full_text = "\n\n".join(warning_text_parts).strip()
    if not warning_number and full_text:
        for m in re.finditer(r"\b(\d{1,4}/\d{2,4})\b", full_text):
            prefix = full_text[max(0, m.start() - 20):m.start()].upper()
            if "CANCEL" in prefix:
                continue
            warning_number = m.group(1)
            break

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


def derive_warning_number(warning_no: Optional[str], dataset_id: str) -> Optional[str]:
    """
    Normalizes warning numbers, preferring the authoritative ExchangeSet dataset id
    (NW.NAVAREA_II.<num>.<yyyy>.eng) over any locally parsed number:
      - tagged "360/26"           -> kept as-is
      - tagged "360" (no slash)    -> "360/26" derived from dataset id
      - None (tag missing)         -> derived from dataset id
    Falls back to the tagged value when the dataset id carries no number.
    """
    if warning_no and "/" in warning_no:
        return warning_no
    m = re.search(r"NW\.NAVAREA_II\.(\d+)\.(\d{4})", dataset_id or "")
    if m:
        return f"{int(m.group(1))}/{m.group(2)[-2:]}"
    return warning_no


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
        # S-124 cancellationDate is the PLANNED cancellation of an in-force
        # warning, not evidence of cancellation; keep status active and let
        # valid_to carry the planned date.
        "status": "active",
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
    1. Fetches the public Get_NW_Messages S-124 Exchange Set (primary, no key),
       falling back to the keyed PING SECOM /object REST API
    2. Decodes Base64 S-100 Exchange Sets and unzips in-memory GML
    3. Runs the rule-first local extractor (no AI fallback; geometry-less
       warnings triage to Tier C via build_master_payload)
    4. Upserts normalized records into Supabase nav_warnings
    """
    print("=" * 70)
    print("⚓ NAVAREA II S-124 SECOM Ingestion Pipeline")
    print(f"📡 Primary endpoint: {NW_MESSAGES_URL}")
    print(f"📡 Fallback endpoint: {PING_OBJECT_URL}")
    print("=" * 70)

    summary = {
        "total_items": 0,
        "harvested": 0,
        "synced": 0,
        "sync_errors": 0,
        "server_errors": "",
        "source_used": "",
        "dry_run": dry_run or (supabase is None),
    }

    payloads: List[Dict[str, Any]] = []
    if mock_payload is not None:
        payloads = [mock_payload]
        summary["source_used"] = "mock"
    else:
        if not HAS_REQUESTS and not HAS_SCRAPLING:
            print("❌ No HTTP client available. Please run: pip install -r requirements.txt")
            summary["server_errors"] = "no HTTP client (requests/Scrapling) available"
            return summary

        # --- Primary source: public Get_NW_Messages XML Exchange Set (no API key) ---
        print("[1/4] Fetching public NAVAREA S-124 Exchange Set (Get_NW_Messages)...")
        xml_text, nw_err = fetch_nw_exchange_set()
        if xml_text is not None:
            datasets, parse_err = parse_nw_datasets(xml_text)
            if parse_err:
                print(f"⚠️ ExchangeSet split failed: {parse_err}; falling back to SECOM API")
            else:
                print(f"  ↳ Parsed {len(datasets)} NAVAREA II dataset(s) from public ExchangeSet")
                payloads = [{
                    "dataResponseObject": exchange_set_to_payload_items(datasets),
                    "pagination": {"totalItems": len(datasets)},
                    "responseText": "",
                }]
                summary["source_used"] = "nw-xml"
        else:
            print(f"⚠️ Public ExchangeSet unavailable ({nw_err})")

        # --- Fallback source: keyed PING SECOM REST API ---
        if not payloads:
            print("[1/4] Falling back to PING SECOM REST API for active notices...")
            if not PING_SECOM_API_KEY:
                print("⚠️ PING_SECOM_API_KEY is not set. The PING SECOM API typically returns HTTP 200")
                print("   with an empty dataResponseObject for unauthenticated requests, which looks")
                print("   like 'no data available' but actually means 'not authorized'.")
            sec_payloads, server_notice = fetch_ping_payloads()
            if sec_payloads:
                payloads = sec_payloads
                summary["source_used"] = "secom-api"
                summary["server_errors"] = server_notice
            else:
                summary["server_errors"] = f"public ExchangeSet failed ({nw_err}); SECOM API failed ({server_notice})"
                return summary

    # Merge paginated responses
    warning_objects: List[Dict[str, Any]] = []
    server_errors = ""
    total_items = 0
    for page in payloads:
        warning_objects.extend(page.get("dataResponseObject") or [])
        pagination_info = page.get("pagination", {}) or {}
        total_items += pagination_info.get("totalItems", len(page.get("dataResponseObject") or []))
        notice = page.get("responseText") or ""
        if notice:
            server_errors = notice

    summary["total_items"] = total_items
    if server_errors and not summary["server_errors"]:
        summary["server_errors"] = server_errors

    print(f"[2/4] Retrieved {len(warning_objects)} Exchange Sets via '{summary['source_used']}' (Total reported: {total_items})")

    # Loudly flag live-but-empty harvests so the workflow fails visibly
    # instead of exiting 0 with zero data. Mock payloads bypass this check.
    if mock_payload is None and not warning_objects:
        reason = "both NAVAREA II sources returned 0 Exchange Sets"
        if not PING_SECOM_API_KEY:
            reason += " (PING_SECOM_API_KEY also not set for the SECOM fallback)"
        elif server_errors:
            reason += f" (server notice: {server_errors})"
        print(f"❌ {reason}")
        summary["server_errors"] = reason
        return summary


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

                # 1. Rule-first local extraction (no AI fallback)
                local_data = local_s124_extractor(raw_gml, file_path)
                final_geometry = local_data.get("geojson_geometry")
                final_text = local_data.get("warning_text") or ""
                dataset_id = local_data.get("dataset_id")

                # 2. Normalize warning number, preferring the authoritative
                #    ExchangeSet dataset id (also fills in a missing tag)
                warning_no = derive_warning_number(local_data.get("warning_number"), dataset_id)

                # 3. Format adapted record for nav_warnings
                adapted_warn = adapt_to_nav_warnings(
                    dataset_id=dataset_id,
                    warning_number=warning_no,
                    warning_type=local_data.get("warning_type"),
                    general_area=local_data.get("general_area"),
                    publication_time=local_data.get("publication_time"),
                    cancellation_date=local_data.get("cancellation_date"),
                    warning_text=final_text,
                    geojson_geometry=final_geometry,
                    raw_payload=raw_gml,
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
    print(f"📊 Summary: Harvested {summary['harvested']} S-124 files | Synced: {summary['synced']} | Errors: {summary['sync_errors']}")
    print("=" * 70)

    # Write to GitHub Actions Step Summary if available
    step_summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_file:
        try:
            with open(step_summary_file, "a", encoding="utf-8") as sf:
                sf.write(f"""### ⚓ NAVAREA II S-124 SECOM Ingestion Summary
| Metric | Value |
| :--- | :--- |
| **Source Used** | `{summary['source_used']}` |
| **Primary Endpoint** | `{NW_MESSAGES_URL}` |
| **HTTP Fetcher** | `{'Scrapling' if HAS_SCRAPLING else 'requests'}` |
| **Fallback Endpoint** | `{PING_OBJECT_URL}` |
| **API Key** | `{"Configured" if PING_SECOM_API_KEY or mock_payload is not None else "not set (public XML source used)"}` |
| **Total Items Reported** | `{summary['total_items']}` |
| **S-124 GML Harvested** | `{summary['harvested']}` |
| **Notices Synced** | `{summary['synced']}` |
| **Sync Errors** | `{summary['sync_errors']}` |
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
