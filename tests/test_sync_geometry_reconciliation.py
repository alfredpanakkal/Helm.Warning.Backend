import unittest

from shared.sync_engine import _stored_geometry_matches_parse


class StoredGeometryReconciliationTests(unittest.TestCase):
    def test_same_feature_type_is_unchanged(self):
        parsed = [{"feature_type": "POLYGON"}]
        self.assertTrue(_stored_geometry_matches_parse({"POLYGON"}, parsed))

    def test_parser_geometry_type_change_requires_repair(self):
        parsed = [{"feature_type": "POLYGON"}]
        self.assertFalse(_stored_geometry_matches_parse({"POINT"}, parsed))
        self.assertFalse(_stored_geometry_matches_parse({"LINE"}, parsed))

    def test_missing_or_empty_geometry_requires_repair(self):
        parsed = [{"feature_type": "POLYGON"}]
        self.assertFalse(_stored_geometry_matches_parse(set(), parsed))
        self.assertFalse(_stored_geometry_matches_parse({"POLYGON"}, []))

    def test_multiple_geometry_types_are_compared_as_a_set(self):
        parsed = [
            {"feature_type": "POLYGON"},
            {"feature_type": "POINT"},
        ]
        self.assertTrue(
            _stored_geometry_matches_parse({"POINT", "POLYGON"}, parsed)
        )
        self.assertFalse(
            _stored_geometry_matches_parse({"POINT"}, parsed)
        )


if __name__ == "__main__":
    unittest.main()
