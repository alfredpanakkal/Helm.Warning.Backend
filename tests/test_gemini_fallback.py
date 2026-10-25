#!/usr/bin/env python3
"""
tests/test_gemini_fallback.py — Gemini-first wrapper regression tests.

Covers: missing API key fallback, timeout fallback, malformed-JSON
fallback, schema-rejection fallback, grounding rejection, NAVAREA II
rule-first, and Tier B provenance stamping on acceptance. The 'valid'
model payload is derived from the real rule parser output so fixtures
always match the repo's deterministic contract.
"""
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared import gemini_navarea_parser as gem
from scripts.navarea_universal_parser import parse_bulletin_text

SAMPLE_III = (
    "WARNINGS IN FORCE AS ON 23 OCT 2026\n"
    "\n"
    "NAVAREA III 004/26\n"
    " 1. HYDROGRAPHIC SURVEY IN AREA BOUNDED BY 36-10.0N 005-30.0W, "
    "36-20.0N 005-30.0W, 36-20.0N 005-40.0W, 36-10.0N 005-40.0W\n"
    " 2. CANCEL NAVAREA III 002/26\n"
    "\n"
    "NAVAREA III 005/26\n"
    " GIBRALTAR STRAIT (.) FIRING PRACTICE IN AREA BOUNDED WITHIN "
    "35-50.0N TO 35-55.0N AND 005-30.0W TO 005-35.0W (.) WIDE BERTH "
    "REQUESTED\n"
)

ENV_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL_NAME")


class GeminiFallbackTest(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k) for k in ENV_KEYS if k in os.environ}
        os.environ["GEMINI_API_KEY"] = "test-key"
        self.rule_parsed = parse_bulletin_text(SAMPLE_III, "iii")
        self.assertTrue(self.rule_parsed["nav_warnings"])

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ[k] = v
        for k in ENV_KEYS:
            if k not in self._saved and k in os.environ:
                del os.environ[k]

    def _fake_model_payload(self):
        return copy.deepcopy(self.rule_parsed)

    def test_missing_key_falls_back_without_model_call(self):
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)
        with mock.patch.object(gem, "try_gemini_parse",
                               side_effect=AssertionError("model must not be called")):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")
        self.assertEqual(out["nav_warnings"], self.rule_parsed["nav_warnings"])

    def test_timeout_falls_back(self):
        with mock.patch.object(gem, "try_gemini_parse", side_effect=TimeoutError("t")):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_malformed_json_falls_back(self):
        with mock.patch.object(gem, "try_gemini_parse", side_effect=ValueError("bad json")):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_schema_violation_falls_back(self):
        bad = self._fake_model_payload()
        bad["nav_warnings"][0].pop("canonical_id")
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_wrong_region_payload_falls_back(self):
        bad = self._fake_model_payload()
        bad["nav_warnings"][0]["navarea"] = "XXI"
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_invented_status_falls_back(self):
        bad = self._fake_model_payload()
        bad["nav_warnings"][0]["status"] = "cancelled"
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_ungrounded_coordinate_falls_back(self):
        bad = self._fake_model_payload()
        first = next(w for w in bad["nav_warnings"] if w.get("spatial"))
        first["latitude"] = first["latitude"] + 5.0
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_paraphrased_raw_text_falls_back(self):
        bad = self._fake_model_payload()
        bad["nav_warnings"][0]["raw_text"] = "NOT IN THE SOURCE BULLETIN"
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_empty_warning_list_falls_back(self):
        bad = self._fake_model_payload()
        bad["nav_warnings"] = []
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_invalid_geometry_falls_back(self):
        bad = self._fake_model_payload()
        first = next(w for w in bad["nav_warnings"] if w.get("spatial"))
        first["spatial"]["features"][0]["geometry"] = {"type": "Polygon"}
        with mock.patch.object(gem, "try_gemini_parse", return_value=bad):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_valid_payload_accepted_as_tier_b(self):
        good = self._fake_model_payload()
        with mock.patch.object(gem, "try_gemini_parse", return_value=good):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "iii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "gemini")
        self.assertEqual(out["memo"]["ai_parse"]["tier"], "B_INFERRED")
        self.assertEqual(out["nav_warnings"], self.rule_parsed["nav_warnings"])

    def test_navarea_ii_is_rule_first(self):
        with mock.patch.object(gem, "try_gemini_parse",
                               side_effect=AssertionError("NAVAREA II must never call the model")):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "ii", parse_bulletin_text)
        self.assertEqual(out["memo"]["parse_provenance"], "rule")

    def test_unknown_region_rule_only(self):
        with mock.patch.object(gem, "try_gemini_parse",
                               side_effect=AssertionError("unknown region must not call the model")):
            out = gem.parse_bulletin_with_fallback(SAMPLE_III, "does-not-exist",
                                                   lambda t, k: {"memo": {}, "nav_warnings": []})
        self.assertEqual(out["memo"]["parse_provenance"], "rule")
        self.assertEqual(out["nav_warnings"], [])


class ValidatePayloadTest(unittest.TestCase):

    def _base(self):
        return copy.deepcopy(parse_bulletin_text(SAMPLE_III, "iii"))

    def test_valid_payload_passes(self):
        ok, reason = gem.validate_llm_payload(self._base(), "iii")
        self.assertTrue(ok, reason)

    def test_missing_lists_rejected(self):
        p = self._base(); del p["nav_warnings"]
        self.assertFalse(gem.validate_llm_payload(p, "iii")[0])
        p = self._base(); p["spatial_features"] = "nope"
        self.assertFalse(gem.validate_llm_payload(p, "iii")[0])

    def test_missing_memo_rejected(self):
        p = self._base(); p["memo"] = None
        self.assertFalse(gem.validate_llm_payload(p, "iii")[0])

    def test_missing_required_field_rejected(self):
        for field in ("warning_id", "canonical_id", "source_id", "navarea", "status"):
            p = self._base(); p["nav_warnings"][0].pop(field)
            self.assertFalse(gem.validate_llm_payload(p, "iii")[0], field)

    def test_non_dict_payload_rejected(self):
        self.assertFalse(gem.validate_llm_payload(["not", "a", "dict"], "iii")[0])
        self.assertFalse(gem.validate_llm_payload(None, "iii")[0])


if __name__ == "__main__":
    unittest.main()
