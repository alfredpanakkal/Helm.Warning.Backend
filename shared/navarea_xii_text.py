#!/usr/bin/env python3
"""
shared/navarea_xii_text.py — NAVAREA XII (NGA Daily Memo) text preprocessing.

Thin configuration wrapper over the generalized shared/nga_memo_text.py
preprocessor (see that module for the full contract). The public API is
identical to the original standalone module, so existing importers
(scraper, parser, tests) are unaffected.
"""

from shared.nga_memo_text import NgaMemoPreprocessor, ring_to_trackline

NAVAREA_ID = "XII"

_impl = NgaMemoPreprocessor(
    navarea_id=NAVAREA_ID,
    ref_zfill=3,
    max_subarea_label_len=1,
    require_coords_in_subarea=False,
)

rejoin_wrapped_coords = _impl.rejoin_wrapped_coords
get_in_force_dtg = _impl.get_in_force_dtg
split_into_warnings = _impl.split_into_warnings
extract_cross_refs = _impl.extract_cross_refs
split_sub_areas = _impl.split_sub_areas
extract_geometry_clauses = _impl.extract_geometry_clauses
normalize_memo = _impl.normalize_memo

# Regex attributes re-exported for backward compatibility with tests.
RE_SPLIT_TOKEN = _impl._WRAP_SPECS[0][0]
RE_COORD_TOKEN = _impl.RE_COORD_TOKEN
RE_DTG_LINE = _impl.RE_DTG_LINE
RE_HEADER_LINE = _impl.re_header_line
RE_CANCEL_REF = _impl.re_cancel_refs
RE_IN_FORCE = _impl.RE_IN_FORCE
RE_SUBAREA_MARKER = _impl.re_subarea_marker
RE_ITEM_LINE = _impl.RE_ITEM_LINE
