#!/usr/bin/env python3
"""
shared/navarea_universal_text.py — Region-parameterized text primitives
for the universal NAVAREA parser (scripts/navarea_universal_parser.py).

The universal parser generalizes scripts/navarea_8_parser.py: the IMO
WWNWS bulletin header ('NAVAREA <NUMERAL> [-]nnn/yy') is the baseline
standard, but the live coordinator bulletins (corpus uploaded Oct 2026)
deviate per region, so this module now carries:

  * a tolerant default header regex (optional 'WARNING'/'MSG' word,
    2- OR 4-digit years as used by II / XVII / XVIII, and the optional
    '(.)' WWNWS prosign separator — the legacy form
    'NAVAREA IX (.) 376/23 (.)' lives in the paknavy 2023-era files,
    verified live 2026-10-28),
  * per-region extra header patterns for the known quirks:
      V    Brazil publishes bare '0648/26' lines (no NAVAREA numeral)
      VI   Argentina: 'NAVAREA - 0355-2026' (numeral omitted)
      VII  South Africa: 'NAVAREA VII 014 OF 2026:' (OF form, year may
           sit on the next line behind tabs)
      XV   Chile: 'NAVAREA XV 0142' (no year in the header)
      XIX  Norway: 'Number:125/26' anchors each warning (the embedded
           'NAVAREA XIX 125/261.' joined-line header defeats the
           standard year boundary)
  * matching per-region cancel-reference patterns (V: 'CANCEL NAVAREA
    0622/26' with no numeral; VII: '... OF 2025').

Region-specific quirk handling that needs a dedicated parser (NAVAREA
1 / IV / VIII / XI / XII, Baltic) stays in those parsers.
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
    "xiii": "XIII",
    "xiv": "XIV",
    "xv": "XV",
    "xvi": "XVI",
    "xvii": "XVII",
    "xviii": "XVIII",
    "xix": "XIX",
    "xx": "XX",
    "xxi": "XXI",
}

_ROMAN_TO_KEY = {roman: key for key, roman in UNIVERSAL_REGIONS.items()}

# AUSCOAST coastal warnings (Australia / AMSA): Australian NATIONAL
# warnings outside NAVAREA numbering, published per area letter A-H in
# Part 3 of the same RCC Australia MSI publication page as NAVAREA X
# (Part 2). They are ingested as area-scoped pseudo-regions
# ('auscoast-a' ... 'auscoast-h'): the same number AMSA lists under two
# areas (e.g. 231/26 under both C and D) stays TWO distinct warnings,
# and per-area in-force bookkeeping stays possible.
AUSCOAST_AREAS = {"auscoast-" + ch: ch.upper() for ch in "abcdefgh"}

# 'AUSCOAST WARNING 327/26' (the 'WARNING' word is optional for
# tolerance; live header shape verified 2026-10-28). Same group contract
# as the NAVAREA headers: group(1)=number, group(2)=year.
RE_AUSCOAST_HEADER = re.compile(
    r"AUS\s*COAST\s+(?:WARNING\s+)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE)

# 'CANCEL AUSCOAST WARNING 3xx/26' cross-reference inside a body.
RE_AUSCOAST_CANCEL = re.compile(
    r"CANCEL\s+AUS\s*COAST\s+(?:WARNING\s+)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE)


# Norwegian coastal warnings (Kystverket 'Navigasjonsvarsler'): national
# coastal warnings (kystvarsel) outside NAVAREA numbering, one numbered
# series per year, ingested as the 'coastal-no' pseudo-region (the same
# pattern as the AUSCOAST pseudo-regions above). The scraper
# (scripts/kystverket_coastal_scraper.py) synthesizes 'COASTAL NO
# WARNING nnn/yy' headers from the table's own 'Navco År'/'Nr' columns.
COASTAL_NO_REGION_KEY = "coastal-no"

# 'COASTAL NO WARNING 407/26' — synthesized header (same group contract
# as the NAVAREA headers: group(1)=number, group(2)=year).
RE_COASTAL_NO_HEADER = re.compile(
    r"COASTAL\s+NO\s+(?:WARNING\s+)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE)

# 'CANCEL COASTAL NO WARNING nnn/yy' cross-reference inside a body.
RE_COASTAL_NO_CANCEL = re.compile(
    r"CANCEL\s+COASTAL\s+NO\s+(?:WARNING\s+)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE)


# the AUSCOAST pseudo-regions have NO companion region, and the parser
# iterates cfg['companion_re'] unconditionally.
RE_NEVER_MATCHES = re.compile(r"(?!)")

# Display names for every NAVAREA / MET area (I–XXI + Baltic), for logs
# and the admin panel.
NAVAREA_NAMES = {
    "1": "UK / North Atlantic",
    "ii": "France / East Atlantic",
    "iii": "Spain / Mediterranean",
    "iv": "USA / West Atlantic",
    "v": "Brazil / SW Atlantic",
    "vi": "Argentina / SE Atlantic",
    "vii": "South Africa",
    "8": "Indian Ocean",
    "ix": "Red Sea / Persian Gulf",
    "x": "Australia",
    "xi": "East Asia",
    "xii": "USA / Eastern Pacific",
    "xiii": "Russia / NW Pacific",
    "xiv": "New Zealand / South Pacific",
    "xv": "Chile / SE Pacific",
    "xvi": "Peru / Eastern Pacific",
    "xvii": "Canada / Arctic West",
    "xviii": "Canada / Arctic East",
    "xix": "Norway / Arctic North",
    "xx": "Russia / Arctic West",
    "xxi": "Russia / Arctic East",
    "baltic": "Baltic",
    # AUSCOAST pseudo-regions (Australian national coastal warnings).
    "auscoast-a": "AUSCOAST Area A (Australia)",
    "auscoast-b": "AUSCOAST Area B (Australia)",
    "auscoast-c": "AUSCOAST Area C (Australia)",
    "auscoast-d": "AUSCOAST Area D (Australia)",
    "auscoast-e": "AUSCOAST Area E (Australia)",
    "auscoast-f": "AUSCOAST Area F (Australia)",
    "auscoast-g": "AUSCOAST Area G (Australia)",
    "auscoast-h": "AUSCOAST Area H (Australia)",
    # Norwegian coastal warnings pseudo-region (Kystverket kystvarsel).
    "coastal-no": "Norwegian Coastal Warnings (Kystverket)",
}

# All 21 NAVAREA / MET numerals, longest-first for safe alternation matching.
_ALL_NUMERALS = ("XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII"
                 "|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I")

# Any 'NAVAREA <numeral> [-]n/yy' header (or the VII 'n OF yyyy' variant),
# tolerant of 'NAV AREA' spacing and 2/4-digit years.
RE_ANY_REGION_HEADER = re.compile(
    r"NAV\s*AREA\s+(" + _ALL_NUMERALS + r")\b\s*[-\u2013]?\s*"
    r"(?:WARNING\s+|MSG\s+)?(?:\(\.\)\s*)?(\d{1,4})\s*(?:/\s*|OF\s+)(\d{4}|\d{2})(?!\d)",
    re.IGNORECASE,
)


def normalize_year(year):
    """Normalizes a matched header year to its 2-digit form.

    '2026' -> '26' (II / XVII / XVIII publish 4-digit years); 2-digit
    years and None pass through unchanged. WARNING: never fabricate a
    year — None stays None (the caller resolves it from a year hint).
    """
    if not year:
        return None
    y = str(year).strip()
    if len(y) == 4:
        return y[-2:]
    return y


def warning_header_re(roman: str):
    """Default 'NAVAREA <roman> [-]n/yy' header regex for one region.

    The trailing \\b after the numeral prevents II from matching inside
    III, V inside VI/VII, X inside XI/XII, XX inside XXI, etc. Tolerates
    the XIV 'NAVAREA XIV WARNING 287/26' word and 4-digit years. Every
    pattern MUST expose group(1)=number and group(2)=year so the parser
    can treat all header patterns uniformly.
    """
    return re.compile(
        r"NAV\s*AREA\s+" + roman + r"\b\s*[-\u2013]?\s*(?:WARNING\s+|MSG\s+)?"
        r"(?:\(\.\)\s*)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
        re.IGNORECASE,
    )


def cancel_ref_re(roman: str):
    """'CANCEL NAVAREA <roman> [MSG|WARNING] [-]n/yy' cross-ref regex."""
    return re.compile(
        r"CANCEL\s+NAV\s*AREA\s+" + roman
        + r"\b\s*(?:WARNING\s+|MSG\s*)?[-\u2013]?\s*(?:\(\.\)\s*)?(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)",
        re.IGNORECASE,
    )


# --- Per-region header quirks (live coordinator corpus, Oct 2026) -----------
# Extra warning-header patterns for regions whose bulletins deviate from
# the WWNWS baseline. Every pattern exposes group(1)=number, group(2)=year
# (group(2) may be None for regions that omit the year, e.g. XV).
_EXTRA_HEADER_PATTERNS = {
    # Brazil publishes bare '0648/26' lines with no NAVAREA numeral. The
    # strict line anchors keep the in-force index lines
    # ('0646/26; 0645/26; ...') from matching.
    "v": [
        re.compile(r"^(\d{1,4})/(\d{2})[ \t]*$", re.MULTILINE | re.IGNORECASE),
    ],
    # Argentina: 'NAVAREA - 0355-2026' (numeral omitted from header).
    "vi": [
        re.compile(r"NAV\s*AREA\s*-\s*(\d{3,4})-(\d{4})(?!\d)", re.IGNORECASE),
    ],
    # South Africa: 'NAVAREA VII 014 OF 2026:' — year may sit on the
    # next line behind tabs; the rest of the header line (': (12 JAN
    # 26)' issue-date suffix) is consumed so it never leaks into the
    # warning title.
    "vii": [
        re.compile(r"NAV\s*AREA\s+VII\b\s*(\d{1,4})\s+OF\s*(\d{4}|\d{2})(?!\d)[^\n]*",
                   re.IGNORECASE),
    ],
    # Chile: 'NAVAREA XV 0142' — no year in the header (resolved from
    # the bulletin's 'YEAR 2026' / 'DATE: .../2026' hint).
    "xv": [
        re.compile(r"NAV\s*AREA\s+XV\b[.\s]*(\d{3,4})\s*(?:/(\d{4}|\d{2}))?(?![\d/])",
                   re.IGNORECASE),
    ],
    # Norway: 'Number:125/26' precedes each warning; the embedded joined
    # 'NAVAREA XIX 125/261.' header defeats the standard year boundary.
    "xix": [
        re.compile(r"Number:\s*(\d{1,4})/(\d{2})(?!\d)", re.IGNORECASE),
    ],
}

# Extra cancel-reference patterns per region.
_EXTRA_CANCEL_PATTERNS = {
    # Brazil: 'CANCEL NAVAREA 0622/26' (no numeral in the reference).
    "v": [
        re.compile(r"CANCEL\s+NAVAREA\s+(\d{3,4})/(\d{2})(?!\d)", re.IGNORECASE),
    ],
    # South Africa: 'CANCEL NAVAREA VII 374 OF 2025'.
    "vii": [
        re.compile(r"CANCEL\s+NAV\s*AREA\s+VII\b\s*(\d{1,4})\s+OF\s*(\d{4}|\d{2})(?!\d)",
                   re.IGNORECASE),
    ],
}


def region_header_patterns(region_key: str, roman: str):
    """Returns the full ordered list of header regexes for a region:
    the default pattern first, then any region-specific extras. A match
    from ANY pattern starts a warning block."""
    pats = [warning_header_re(roman)]
    pats.extend(_EXTRA_HEADER_PATTERNS.get(region_key, []))
    return pats


def region_cancel_patterns(region_key: str, roman: str):
    """Returns the full ordered list of cancel-reference regexes for a
    region: the default pattern plus any region-specific extras."""
    pats = [cancel_ref_re(roman)]
    pats.extend(_EXTRA_CANCEL_PATTERNS.get(region_key, []))
    return pats


# Bulletin-level year hint for regions whose headers omit the year
# (NAVAREA XV): 'YEAR 2026:' or 'DATE: OCT/16/2026'.
RE_YEAR_HINT = re.compile(r"\bYEAR\s+(\d{4})\b|DATE:.*?(\d{4})\b", re.IGNORECASE)

# Regions whose bulletins may carry non-English titles that may be
# machine-translated (fail-closed) for display: Chile / Peru (Spanish
# titles) and Norway XIX (English series, individual items occasionally
# Norwegian — detection decides per title, shared/translation.py).
TITLE_TRANSLATION_REGIONS = {"xv", "xvi", "xix"}


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
