#!/usr/bin/env python3
"""test_navarea_ii.py — Unit & Integration Tests for NAVAREA II S-124 Pipeline"""

import sys
import os
import io
import json
import base64
import zipfile
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scrapers.navarea_ii import (
    strip_ns,
    local_s124_extractor,
    adapt_to_nav_warnings,
    S124BackupSchema,
    run_navarea_ii_pipeline,
    NW_MESSAGES_URL,
    parse_nw_datasets,
)


class TestNavareaIIExtractor(unittest.TestCase):
    def test_strip_ns(self):
        self.assertEqual(strip_ns("{http://www.iho.int/S124/gml/cs0/2.0}warningNumber"), "warningNumber")
        self.assertEqual(strip_ns("warningNumber"), "warningNumber")

    def test_local_s124_point_extraction(self):
        sample_gml = """<?xml version="1.0" encoding="utf-8"?>
<S124:S124_NavigationalWarning xmlns:S124="http://www.iho.int/S124/gml/cs0/2.0" xmlns:gml="http://www.opengis.net/gml/3.2">
  <S124:warningIdentifier>359/26</S124:warningIdentifier>
  <S124:generalArea>BAY OF BISCAY</S124:generalArea>
  <S124:warningType>Hydrographic Survey</S124:warningType>
  <S124:publicationTime>2026-10-18T10:00:00Z</S124:publicationTime>
  <S124:textDescription>SURVEY OPERATIONS IN PROGRESS BY M/V OCEAN EXPLORER. 0.5 NM BERTH REQUESTED.</S124:textDescription>
  <S124:geometry>
    <gml:Point>
      <!-- GML standard is lat lon -->
      <gml:pos>46.5000 -4.2500</gml:pos>
    </gml:Point>
  </S124:geometry>
</S124:S124_NavigationalWarning>"""

        data = local_s124_extractor(sample_gml, "124FR00N035926E.gml")
        self.assertEqual(data["dataset_id"], "124FR00N035926E")
        self.assertEqual(data["warning_number"], "359/26")
        self.assertEqual(data["general_area"], "BAY OF BISCAY")
        self.assertEqual(data["publication_time"], "2026-10-18T10:00:00Z")
        self.assertIn("SURVEY OPERATIONS", data["warning_text"])

        # Check GeoJSON coordinate inversion: [lon, lat]
        geom = data["geojson_geometry"]
        self.assertIsNotNone(geom)
        self.assertEqual(geom["type"], "Point")
        self.assertEqual(geom["coordinates"], [-4.2500, 46.5000])

    def test_local_s124_polygon_extraction(self):
        sample_gml = """<?xml version="1.0" encoding="utf-8"?>
<S124_NavigationalWarning>
  <warningIdentifier>402/26</warningIdentifier>
  <generalArea>CELTIC SEA</generalArea>
  <warningType>Military Firing Exercise</warningType>
  <text>GUNNERY EXERCISE IN RESTRICTED ZONE A.</text>
  <geometry>
    <Polygon>
      <!-- Lat Lon pairs -->
      <posList>48.0 -5.0 48.5 -5.0 48.5 -4.0 48.0 -4.0 48.0 -5.0</posList>
    </Polygon>
  </geometry>
</S124_NavigationalWarning>"""

        data = local_s124_extractor(sample_gml, "124FR00N040226E.gml")
        self.assertEqual(data["warning_number"], "402/26")
        geom = data["geojson_geometry"]
        self.assertIsNotNone(geom)
        self.assertEqual(geom["type"], "Polygon")
        coords = geom["coordinates"][0]
        # Inverted to [lon, lat]
        self.assertEqual(coords[0], [-5.0, 48.0])
        self.assertEqual(coords[1], [-5.0, 48.5])
        self.assertEqual(coords[-1], [-5.0, 48.0])

    def test_adapt_to_nav_warnings(self):
        row = adapt_to_nav_warnings(
            dataset_id="124FR00N035926E",
            warning_number="NAVAREA II 359/26",
            warning_type="Military Exercise",
            general_area="BAY OF BISCAY",
            publication_time="2026-10-18T12:00:00Z",
            cancellation_date=None,
            warning_text="FIRING PRACTICE IN PROGRESS",
            geojson_geometry={"type": "Point", "coordinates": [-4.5, 47.2]},
            raw_payload="<xml>...</xml>",
            used_ai=False,
        )

        self.assertEqual(row["warning_id"], "359/26")
        self.assertEqual(row["source_id"], "shom-navarea-2")
        self.assertEqual(row["navarea"], "NAVAREA II")
        self.assertEqual(row["coordinates"], "47.2000N 004.5000W")
        self.assertIn("NAVAREA II 359/26", row["title"])
        self.assertEqual(row["status"], "active")
        # Schema 20261019/20: flat "category"/"severity" were replaced by the "categories" array
        self.assertIn("military", row["categories"])
        self.assertNotIn("category", row)
        self.assertNotIn("severity", row)
        self.assertEqual(row["latitude"], 47.2)
        self.assertEqual(row["longitude"], -4.5)
        # severity was removed from the schema; ensure it is not resurrected
        # Ensure unmigrated triage columns are strictly stripped to prevent PostgREST PGRST204
        self.assertNotIn("data_quality", row)
        self.assertNotIn("triage_tier", row)
        self.assertNotIn("parsing_method", row)
        self.assertNotIn("qa_flags", row)
        self.assertNotIn("unplotted_reason", row)

    def test_backup_schema_validation(self):
        raw_json = json.dumps({
            "warning_number": "512/26",
            "warning_type": "Drifting Hazard",
            "general_area": "ATLANTIC OCEAN",
            "publication_time": "2026-10-18T14:30:00Z",
            "cancellation_date": None,
            "warning_text": "CONTAINER REPORTED ADRIFT IN VICINITY OF 45-20N 008-10W.",
            "geometry_type": "Point",
            "coordinates": [
                {"longitude": -8.1667, "latitude": 45.3333}
            ]
        })
        parsed = S124BackupSchema.model_validate_json(raw_json)
        self.assertEqual(parsed.warning_number, "512/26")
        self.assertEqual(parsed.geometry_type, "Point")
        self.assertEqual(parsed.coordinates[0].longitude, -8.1667)
        self.assertEqual(parsed.coordinates[0].latitude, 45.3333)

    def test_nw_messages_url_is_filtered_english_series(self):
        # The public ExchangeSet endpoint must request the NAVAREA II series in English
        self.assertIn("Get_NW_Messages", NW_MESSAGES_URL)
        self.assertIn("nameOfSeries=NAVAREA%20II", NW_MESSAGES_URL)
        self.assertIn("lang=en", NW_MESSAGES_URL)

    def test_parse_nw_datasets_filters_navarea_ii(self):
        xml_text = (
            '<S124:ExchangeSet xmlns:S124="http://www.iho.int/S124/gml/2.0" xmlns:gml="http://www.opengis.net/gml/3.2">'
            '<S124:Dataset gml:id="NW.NAVAREA_II.360.2026.eng"><S124:members></S124:members></S124:Dataset>'
            '<S124:Dataset gml:id="NW.NAVAREA_I.12.2026.eng"><S124:members></S124:members></S124:Dataset>'
            '<S124:Dataset gml:id="NW.NAVAREA_II.358.2026.eng"><S124:members></S124:members></S124:Dataset>'
            '</S124:ExchangeSet>'
        )
        datasets, err = parse_nw_datasets(xml_text)
        self.assertEqual(err, "")
        self.assertEqual(len(datasets), 2)
        gml_ids = [gml_id for gml_id, _ in datasets]
        self.assertIn("NW.NAVAREA_II.360.2026.eng", gml_ids)
        self.assertNotIn("NW.NAVAREA_I.12.2026.eng", gml_ids)

    def test_pipeline_dry_run_with_mock_exchange_set(self):
        # Create an in-memory ZIP containing a sample S-124 GML
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            gml_str = """<S124><warningNumber>777/26</warningNumber><generalArea>ENGLISH CHANNEL</generalArea><text>UNLIT BUOY REPORTED</text><posList>49.5 -2.0</posList></S124>"""
            zf.writestr("124FR00N077726E.gml", gml_str)

        b64_zip = base64.b64encode(zip_buf.getvalue()).decode("ascii")

        mock_payload = {
            "dataResponseObject": [
                {"data": b64_zip}
            ],
            "pagination": {"totalItems": 1},
            "responseText": ""
        }

        summary = run_navarea_ii_pipeline(mock_payload=mock_payload, dry_run=True)
        self.assertEqual(summary["total_items"], 1)
        self.assertEqual(summary["harvested"], 1)
        self.assertEqual(summary["synced"], 1)


if __name__ == "__main__":
    unittest.main()
