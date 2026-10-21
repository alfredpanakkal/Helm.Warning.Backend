#!/usr/bin/env python3
"""
shared/navarea_iv_text.py — NAVAREA IV (NGA Daily Memo) text preprocessing.

Configuration wrapper over the generalized shared/nga_memo_text.py
preprocessor. NAVAREA IV specifics (see that module for the full contract):

  - ref_zfill=None: IV memo headers use unpadded numbers ("7/26", "12/25")
    and cross-reference ids must match the stored canonical_id verbatim.
  - max_subarea_label_len=4: MODU position lists use multi-letter sub-area
    labels (A..Z, AA..AZ, AAA..AAZ, AAAA..AAAQ — 204/26).
  - require_coords_in_subarea=True: rejects title-line false positives
    ("ST. KITTS AND NEVIS." in 1524/24) while keeping all legitimate markers.
"""

from shared.nga_memo_text import NgaMemoPreprocessor

NAVAREA_ID = "IV"

_impl = NgaMemoPreprocessor(
    navarea_id=NAVAREA_ID,
    ref_zfill=None,
    max_subarea_label_len=4,
    require_coords_in_subarea=True,
)

rejoin_wrapped_coords = _impl.rejoin_wrapped_coords
get_in_force_dtg = _impl.get_in_force_dtg
split_into_warnings = _impl.split_into_warnings
extract_cross_refs = _impl.extract_cross_refs
split_sub_areas = _impl.split_sub_areas
normalize_memo = _impl.normalize_memo
