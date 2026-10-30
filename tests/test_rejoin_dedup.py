#!/usr/bin/env python3
"""tests/test_rejoin_dedup.py - one rejoin implementation for every path.

NgaMemoPreprocessor.rejoin_wrapped_coords now delegates to the canonical
shared/utils.py rejoin_wrapped_coords (no-second-parser rule). Guards:
  - identical output on the four confirmed wrap shapes (XII 148/26,
    IV 206/26, IV 204/26, IV 466/25)
  - idempotency
  - CRLF wraps: the old memo-local specs matched LF only, so a
    CRLF-wrapped token was NOT rejoined on the memo path (confirmed
    capability gap; the shared _WRAP is CRLF-tolerant)
  - invalid merged tokens (minutes >= 60, out-of-range degrees) are
    never merged
  - prose word-wraps are left untouched
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.nga_memo_text import NgaMemoPreprocessor
from shared.utils import rejoin_wrapped_coords as shared_rejoin

LF = chr(10)
CRLF = chr(13) + chr(10)

IV = NgaMemoPreprocessor(navarea_id="IV", ref_zfill=None,
                         max_subarea_label_len=4, require_coords_in_subarea=True)


class TestDelegation(unittest.TestCase):
    def test_method_delegates_to_shared(self):
        text = "AREA BOUND BY " + "12-" + LF + "28.85N 081-43.83W"
        self.assertEqual(IV.rejoin_wrapped_coords(text), shared_rejoin(text))
        self.assertIn("12-28.85N", IV.rejoin_wrapped_coords(text))

    def test_all_four_wrap_shapes_rejoined(self):
        cases = [
            ("34-27." + LF + "00N", "34-27.00N"),
            ("57" + LF + "-00N", "57-00N"),
            ("27-09" + LF + ".1N", "27-09.1N"),
            ("12-" + LF + "28.85N", "12-28.85N"),
        ]
        for raw, merged in cases:
            self.assertEqual(IV.rejoin_wrapped_coords(raw), merged)
            self.assertEqual(shared_rejoin(raw), merged)

    def test_idempotent(self):
        text = "12-" + LF + "28.85N 081-43.83W"
        once = IV.rejoin_wrapped_coords(text)
        self.assertEqual(IV.rejoin_wrapped_coords(once), once)

    def test_crlf_wrap_rejoined_on_memo_path(self):
        # The old memo-local specs matched LF only; a CRLF-wrapped token
        # stayed split on the memo path. The shared _WRAP is CRLF-
        # tolerant, so delegation rejoins it too.
        text = "12-" + CRLF + "28.85N"
        self.assertEqual(IV.rejoin_wrapped_coords(text), "12-28.85N")

    def test_invalid_minutes_never_merged(self):
        text = "12-" + LF + "99.5N"
        self.assertEqual(IV.rejoin_wrapped_coords(text), text)

    def test_out_of_range_degrees_never_merged(self):
        text = "95-" + LF + "00.0N"
        self.assertEqual(IV.rejoin_wrapped_coords(text), text)

    def test_prose_word_wrap_untouched(self):
        text = "IN AREA BO" + LF + "UND BY 12-28.85N 081-43.83W"
        self.assertEqual(IV.rejoin_wrapped_coords(text), text)


if __name__ == '__main__':
    unittest.main()
