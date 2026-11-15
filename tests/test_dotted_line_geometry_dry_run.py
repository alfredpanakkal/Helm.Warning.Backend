import unittest

from scripts.dry_run_dotted_line_geometry import TARGETS, validate_result


class TestDottedLineDryRunValidation(unittest.TestCase):
    def test_0169_requires_two_labelled_lines_with_exact_source_counts(self):
        result = {
            "parsed_triage_tier": "B",
            "parsed_data_quality": "INFERRED",
            "parsed_qa_flags": ["DOTTED_LINE_ROUTE_REVIEW"],
            "features": [
                {"geometry_type": "LineString", "sub_area": "A", "coordinate_count": 7},
                {"geometry_type": "LineString", "sub_area": "B", "coordinate_count": 22},
            ],
        }
        self.assertEqual(validate_result(result, TARGETS["NAVAREA III 0169/26"]), [])

    def test_0171_requires_one_open_line_and_review_flag(self):
        result = {
            "parsed_triage_tier": "B",
            "parsed_data_quality": "INFERRED",
            "parsed_qa_flags": ["DOTTED_LINE_ROUTE_REVIEW"],
            "features": [
                {"geometry_type": "LineString", "sub_area": None, "coordinate_count": 21},
            ],
        }
        self.assertEqual(validate_result(result, TARGETS["NAVAREA III 0171/26"]), [])

    def test_ix_440_rejects_line_or_polygon_promotion(self):
        result = {
            "parsed_triage_tier": "B",
            "parsed_data_quality": "AMBIGUOUS",
            "parsed_qa_flags": ["AMBIGUOUS_FALLBACK"],
            "features": [
                {"geometry_type": "MultiPoint", "sub_area": None, "coordinate_count": 4},
            ],
        }
        self.assertEqual(validate_result(result, TARGETS["NAVAREA IX 440/26"]), [])

    def test_ix_440_fails_if_parser_promotes_to_polygon(self):
        result = {
            "parsed_triage_tier": "B",
            "parsed_data_quality": "AMBIGUOUS",
            "parsed_qa_flags": ["AMBIGUOUS_FALLBACK"],
            "features": [
                {"geometry_type": "Polygon", "sub_area": None, "coordinate_count": 4},
            ],
        }
        errors = validate_result(result, TARGETS["NAVAREA IX 440/26"])
        self.assertTrue(any("promoted" in error for error in errors))

    def test_dotted_line_route_fails_if_review_flag_is_missing(self):
        result = {
            "parsed_triage_tier": "A",
            "parsed_data_quality": "EXPLICIT",
            "parsed_qa_flags": [],
            "features": [
                {"geometry_type": "LineString", "sub_area": None, "coordinate_count": 21},
            ],
        }
        errors = validate_result(result, TARGETS["NAVAREA III 0171/26"])
        self.assertTrue(any("Tier B" in error for error in errors))
        self.assertTrue(any("flag mismatch" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
