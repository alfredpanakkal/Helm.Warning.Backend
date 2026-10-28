#!/usr/bin/env python3
"""TEMPORARY diagnostic (delete before merge): prints the VII 258/26
clause/geometry breakdown to the CI log tail to pin the failing
MultiPoint contract."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class Diag(unittest.TestCase):
    def test_vii_258_breakdown(self):
        from scripts.navarea_universal_parser import (
            parse_bulletin_text, _segment_clauses, _region_config,
            split_into_warnings,
        )
        from shared.utils import parse_coordinates_detailed
        text = open(os.path.join(FIX, "navarea_vii_sample.txt"), encoding="utf-8").read()
        cfg = _region_config("vii")
        for block in split_into_warnings(text, cfg):
            if "258" not in block["warning_id"]:
                continue
            body = block["raw_text"].replace(block["header_text"], "", 1).strip()
            print("DIAG header:", repr(block["header_text"]))
            clauses = _segment_clauses(body)
            print("DIAG n_clauses:", len(clauses))
            geoms = []
            for c in clauses:
                _, lat, lon, spatial, rep = parse_coordinates_detailed(c["text"])
                print("DIAG clause", repr(c["label"]), "geom:",
                      None if not spatial else spatial.get("type"),
                      "pairs:", len(rep.get("accepted") or []),
                      "flags:", rep.get("flags"), "basis:", rep.get("basis"))
                if spatial:
                    geoms.append(spatial.get("type"))
            print("DIAG geom types:", geoms)
        parsed = parse_bulletin_text(text, "vii")
        for w in parsed["nav_warnings"]:
            if "258" in w["warning_id"]:
                print("DIAG final spatial:",
                      w["spatial"]["features"][0]["geometry"]["type"] if w["spatial"] else None)
                print("DIAG sub_areas:", w.get("geometry_sub_areas"))
                self.assertEqual(
                    w["spatial"]["features"][0]["geometry"]["type"], "MultiPoint")


if __name__ == '__main__':
    unittest.main()
