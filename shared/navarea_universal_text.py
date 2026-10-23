#!/usr/bin/env python3
"""
shared/navarea_universal_text.py — Region-parameterized text primitives
for the universal NAVAREA parser (scripts/navarea_universal_parser.py).

The universal parser generalizes scripts/navarea_8_parser.py: the IMO
WWNWS bulletin header ('NAVAREA <NUMERAL> [-]nnn/yy') is a global
standard, so only the numeral is parameterized. Region-specific quirk
handling stays in the dedicated per-region parsers (NAVAREA 1 / IV /
VIII / XI / XII, Baltic).
"""
import re

# region key -> roman numeral, for regions WITHOUT a dedicated parser.
# Regions 1 / 8 / iv / xi / xii / baltic keep their own parser + sync.
UNIVERSAL_REGIONS = {
    "ii": "II",
    "iii": "III",
    "v": "V",
    "vi": "VI",
    "vii": "VII",
    "ix": "IX",
    "x": "X",
}

_ROMAN_TO_KEY = {roman: key for key, roman in UNIVERSAL_REGIONS.items()}

# All 12 NAVAREA numerals, longest-first for safe alternation matching.
_ALL_NUMERALS = "XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I"

# Any 'NAVAREA <numeral> [-]n/yy' header, tolerant of 'NAV AREA' spacing.
RE_ANY_REGION_HEADER = re.compile(
    r"NAV\s*AREA\s+(" + _ALL_NUMERALS + r")\b\s*[-\u2013]?\s*(\d{1,4})\s*/\s*(\d{2})",
    re.IGNORECASE,
)


def warning_header_re(roman: str):
    """'NAVAREA <roman> [-]n/yy' header regex for one region.

    The trailing \\b after the numeral prevents II from matching inside
    III, V inside VI/VII, X inside XI/XII, etc.
    """
    return re.compile(
        r"NAV\s*AREA\s+" + roman + r"\b\s*[-\u2013]?\s*(\d{1,4})\s*/\s*(\d{2})",
        re.IGNORECASE,
    )


def cancel_ref_re(roman: str):
    """'CANCEL NAVAREA <roman> [MSG] [-]n/yy' cross-ref regex for one region."""
    return re.compile(
        r"CANCEL\s+NAV\s*AREA\s+" + roman
        + r"\b\s*(?:MSG\s*)?[-\u2013]?\s*(\d{1,4})\s*/\s*(\d{2})",
        re.IGNORECASE,
    )


def regions_in_text(text: str) -> set:
    """Returns the set of roman numerals (uppercase) found in warning headers.

    Occurrences inside 'CANCEL ...' cross-references are excluded: a
    cross-region cancel ref does not make a paste mixed-region.
    """
    if not text:
        return set()
    romans = set()
    for m in RE_ANY_REGION_HEADER.finditer(text):
        prefix = text[max(0, m.start() - 8):m.start()].upper()
        if "CANCEL" in prefix:
            continue
        romans.add(m.group(1).upper())
    return romans


def roman_to_key(roman: str):
    """Maps a roman numeral to its region key, or None for dedicated-parser
    regions (I, IV, VIII, XI, XII)."""
    return _ROMAN_TO_KEY.get((roman or "").upper())
