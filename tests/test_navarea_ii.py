#!/usr/bin/env python3
"""test_navarea_ii.py — Unit & Integration Tests for NAVAREA II S-124 NW v2 Pipeline"""

import sys
import os
import json
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scrapers.navarea_ii import (
    strip_ns,
    parse_nw_exchange_set,
    parse_geometry_from_dataset,
    adapt_to_nav_warnings,
    S124BackupSchema,
    run_navarea_ii_pipeline,
)


def _dataset_gml(number="360", year="2026", area="CANARIAS",
                 text="NAVIGATE WITH CAUTION.", pos_list="46.5 -4.25 46.6 -4.25 46.6 -4.1 46.5 -4.1 46.5 -4.25",
                 pub="2026-10-20T01:23:00Z", cancel="2026-10-23T01:00:00Z"):
    """Builds a minimal S-124 dataset element mirroring the real NW v2 payload shape."""
    return f"""<S124:Dataset xmlns:S124="http://www.iho.int/S124/gml/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:S100="http://www.iho.int/s100gml/5.0" gml:id="NW.NAVAREA_II.{number}.{year}.eng">
  <S100:DatasetIdentificationInformation>
    <S100:datasetTitle>NAVAREA II {number}/{year[2:]} - eng</S100:datasetTitle>
  </S100:DatasetIdentificationInformation>
  <S124:members>
    <S124:NavwarnPreamble>
      <S124:generalArea><S124:locationName><S124:language>eng</S124:language><S124:text>{area}</S124:text></S124:locationName></S124:generalArea>
      <S124:messageSeriesIdentifier>
        <S124:agencyResponsibleForProduction>FR00</S124:agencyResponsibleForProduction>
        <S124:nameOfSeries>NAVAREA II</S124:nameOfSeries>
        <S124:warningNumber>{number}</S124:warningNumber>
        <S124:year>{year}</S124:year>
      </S124:messageSeriesIdentifier>
      <S124:publicationTime>{pub}</S124:publicationTime>
      <S124:cancellationDate>{cancel}</S124:cancellationDate>
    </S124:NavwarnPreamble>
    <S124:NavwarnPart>
      <S124:warningInformation>
        <S124:information><S124:language>eng</S124:language><S124:text>{text}</S124:text></S124:information>
      </S124:warningInformation>
      <S124:geometry>
        <S100:surfaceProperty><S100:Surface><gml:patches><gml:PolygonPatch><gml:exterior><gml:LinearRing><gml:posList>{pos_list}</gml:posList></gml:LinearRing></gml:exterior></gml:PolygonPatch></gml:patches></S100:Surface></S100:surfaceProperty>
      </S124:geometry>
    </S124:NavwarnPart>
  </S124:members>
</S124:Dataset>"""


def _point_dataset_gml():
    return f"""<S124:Dataset xmlns:S124="http://www.iho.int/S124/gml/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:S100="http://www.iho.int/s100gml/5.0" gml:id="NW.NAVAREA_II.359.2026.eng">
  <S100:DatasetIdentificationInformation>
    <S100:datasetTitle>NAVAREA II 359/26 - eng</S100:datasetTitle>
  </S100:DatasetIdentificationInformation>
  <S124:members>
    <S124:NavwarnPreamble>
      <S124:generalArea><S124:locationName><S124:language>eng</S124:language><S124:text>BAY OF BISCAY</S124:text></S124:locationName></S124:generalArea>
      <S124:messageSeriesIdentifier>
        <S124:nameOfSeries>NAVAREA II</S124:nameOfSeries>
        <S124:warningNumber>359</S124:warningNumber>
        <S124:year>2026</S124:year>
      </S124:messageSeriesIdentifier>
      <S124:publicationTime>2026-10-18T10:00:00Z</S124:publicationTime>
    </S124:NavwarnPreamble>
    <S124:NavwarnPart>
      <S124:warningInformation>
        <S124:information><S124:language>eng</S124:language><S124:text>SURVEY OPERATIONS IN PROGRESS BY M/V OCEAN EXPLORER.</S124:text></S124:information>
      </S124:warningInformation>
      <S124:geometry>
        <S100:pointProperty><S100:Point><gml:pos>46.5000 -4.2500</gml:pos></S100:Point></S100:pointProperty>
      </S124:geometry>
    </S124:NavwarnPart>
  </S124:members>
</S124:Dataset>"""


class TestNavareaIIParser(unittest.TestCase):
    def test_strip_ns(self):
        self.assertEqual(strip_ns("{http://www.iho.int/S124/gml/cs0/2.0}warningNumber"), "warningNumber")
        self.assertEqual(strip_ns("warningNumber"), "warningNumber")

    def test_parse_point_dataset(self):
        results = parse_nw_exchange_set(_point_dataset_gml())
        self.assertEqual(len(results), 1)
        data = results[0]
        self.assertEqual(data["warning_id"], "359/26")
        self.assertEqual(data["general_area"], "BAY OF BISCAY")
        self.assertEqual(data["publication_time"], "2026-10-18T10:00:00Z")
        self.assertIn("SURVEY OPERATIONS", data["warning_text"])

        # GeoJSON coordinate inversion: GML is 'lat lon', GeoJSON is '[lon, lat]'
        geom = data["geojson_geometry"]
        self.assertIsNotNone(geom)
        self.assertEqual(geom["type"], "Point")
        self.assertEqual(geom["coordinates"], [-4.2500, 46.5000])

    def test_parse_polygon_dataset(self):
        gml = _dataset_gml()
        results = parse_nw_exchange_set(gml)
        self.assertEqual(len(results), 1)
        data = results[0]
        self.assertEqual(data["warning_id"], "360/26")
        self.assertIn("CANARIAS", data["general_area"])
        self.assertIn("NAVIGATE WITH CAUTION", data["warning_text"])

        geom = data["geojson_geometry"]
        self.assertIsNotNone(geom)
        self.assertEqual(geom["type"], "Polygon")
        coords = geom["coordinates"][0]
        # Inverted to [lon, lat]; ring auto-closed
        self.assertEqual(coords[0], [-4.25, 46.5])
        self.assertEqual(coords[-1], coords[0])

    def test_parse_multiple_datasets_in_exchange_set(self):
        exchange_set = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<S124:ExchangeSet xmlns:S124="http://www.iho.int/S124/gml/2.0">'
            + _dataset_gml(number="360", area="CANARIAS")
            + _dataset_gml(number="358", area="BAY OF BISCAY", cancel=None, pos_list="46.1 -4.0 46.2 -4.0 46.2 -3.9 46.1 -3.9 46.1 -4.0")
            + "</S124:ExchangeSet>"
        )
        results = parse_nw_exchange_set(exchange_set)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["warning_id"], "360/26")
        self.assertEqual(results[1]["warning_id"], "358/26")

    def test_parse_geometry_handles_whitespace_noise(self):
        # Real endpoint embeds newlines inside posList values
        import xml.etree.ElementTree as ET
        elem = ET.fromstring(
            "<Dataset><Surface><posList>27.1181 -13.9999\n27.1660 -14.0005 27.1665\n-14.0221</posList></Surface></Dataset>"
        )
        geom = parse_geometry_from_dataset(elem)
        self.assertIsNotNone(geom)
        self.assertEqual(geom["type"], "LineString")
        self.assertEqual(geom["coordinates"][0], [-13.9999, 27.1181])

    def test_adapt_to_nav_warnings(self):
        record, geoms = adapt_to_nav_warnings(
            dataset_id="NW.NAVAREA_II.359.2026.eng",
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

        self.assertEqual(record["warning_id"], "359/26")
        self.assertEqual(record["source_id"], "shom-navarea-2")
        self.assertEqual(record["navarea"], "NAVAREA II")
        self.assertEqual(record["coordinates"], "47.2000N 004.5000W")
        self.assertIn("NAVAREA II 359/26", record["title"])
        self.assertEqual(record["status"], "active")
        # Schema 20261019/20: flat "category"/"severity" were replaced by the "categories" array
        self.assertIn("military", record["categories"])
        self.assertNotIn("category", record)
        self.assertNotIn("severity", record)
        self.assertEqual(record["latitude"], 47.2)
        self.assertEqual(record["longitude"], -4.5)
        # Ensure unmigrated triage columns are strictly stripped from the record
        self.assertNotIn("data_quality", record)
        self.assertNotIn("triage_tier", record)
        self.assertNotIn("parsing_method", record)
        self.assertNotIn("qa_flags", record)
        self.assertNotIn("unplotted_reason", record)
        self.assertIsInstance(geoms, list)

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

    def test_pipeline_dry_run_with_mock_exchange_set(self):
        mock_gml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<S124:ExchangeSet xmlns:S124="http://www.iho.int/S124/gml/2.0">'
            + _dataset_gml(number="777", area="ENGLISH CHANNEL", text="UNLIT BUOY REPORTED.",
                           pos_list="49.5 -2.0 49.6 -2.0 49.6 -1.9 49.5 -1.9 49.5 -2.0")
            + "</S124:ExchangeSet>"
        )

        summary = run_navarea_ii_pipeline(mock_gml=mock_gml, dry_run=True)
        self.assertEqual(summary["total_items"], 1)
        self.assertEqual(summary["harvested"], 1)
        self.assertEqual(summary["synced"], 1)


if __name__ == "__main__":
    unittest.main()
