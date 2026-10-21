#!/usr/bin/env python3
"""
shared/navarea_xii_text.py — NAVAREA XII (NGA Daily Memo) text preprocessing.

Pure text transforms applied BEFORE deterministic parsing and BEFORE any
AI-fallback grounding (H05):
  - rejoin_wrapped_coords(): repair coordinate tokens split across line wraps
  - split_into_warnings():   DTG-header segmentation of the daily memo
  - extract_cross_refs():    header-paren refs + body "CANCEL NAVAREA XII n/yy" refs
  - split_sub_areas():       A./B./C. sub-area split (one geometry record each)
  - normalize_memo():        rejoin + segmentation pipeline

No coordinate parsing or conversion happens here. Geometry always comes from
shared.utils.parse_coordinates (no-second-parser rule).
"""

import re

NAVAREA_ID = "XII"

# --- rejoin_wrapped_coords --------------------------------------------------
# A line that ends mid-token ("34-27.") followed by a next-line remainder
# ("00N 120-26.00W") — merged into "34-27.00N" (live 148/26 wrap case).
RE_SPLIT_TOKEN = re.compile(
    r"(\d{1,3}-\d{1,2}(?:\.\d{0,4})?)\n(\d{1,2}(?:\.\d{1,4})?)([NSEW])"
)
RE_COORD_TOKEN = re.compile(r"^(\d{1,3})-(\d{1,2}(?:\.\d{1,4})?)([NSEW])$")


def _is_valid_merged_token(token: str) -> bool:
    m = RE_COORD_TOKEN.match(token)
    if not m:
        return False
    deg = int(m.group(1))
    minutes = float(m.group(2))
    if minutes >= 60.0:
        return False
    if m.group(3) in ("N", "S"):
        return deg <= 90
    return deg <= 180


def rejoin_wrapped_coords(text: str) -> str:
    """Join DDM coordinate tokens split across line wraps (idempotent).

    Example (NAVAREA XII 148/26):
        "      34-27.\n00N 120-26.00W,"  ->  "34-27.00N 120-26.00W,"

    Only merges when the merged fragment forms a valid coordinate token;
    prose word-wraps ("IN AREA BO\nUND BY") are left untouched.
    """
    if not text:
        return text

    def _merge(m):
        merged = (m.group(1) or "") + (m.group(2) or "") + (m.group(3) or "")
        if _is_valid_merged_token(merged):
            return merged
        return m.group(0)

    previous = None
    while previous != text:
        previous = text
        text = RE_SPLIT_TOKEN.sub(_merge, text)
    return text


# --- segmentation ------------------------------------------------------------
RE_DTG_LINE = re.compile(r"^(\d{6}Z\s+[A-Z]{3}\s+\d{2})$")
RE_HEADER_LINE = re.compile(
    r"^NAVAREA\s+XII\s+(\d+)/(\d{2})(?:\(([^)]*)\))?\.?$", re.IGNORECASE
)
RE_CANCEL_REF = re.compile(
    r"\bCANCEL\s+NAVAREA\s+(?:XII\s+)?(\d+)/(\d{2})\b", re.IGNORECASE
)
RE_IN_FORCE = re.compile(r"IN\s+FORCE\s+AS\s+OF\s+(\d{6}Z\s+[A-Z]{3})", re.IGNORECASE)


def get_in_force_dtg(memo_text: str):
    """DTG of the memo's 'IN FORCE AS OF' line (scraper idempotency marker)."""
    if not memo_text:
        return None
    m = RE_IN_FORCE.search(memo_text)
    return m.group(1) if m else None


def split_into_warnings(memo_text: str, rejoin: bool = True):
    """Segment the daily memo into warning blocks at header lines.

    Primary anchor: a DTG line ("040124Z MAR 26") immediately above a
    "NAVAREA XII n/yy(refs)." header line. Legacy blocks without a DTG
    (MSGID/GENADMIN ... RMKS/ prefixed) start at the header line, and when the
    two preceding lines are MSGID/RMKS they are included in the block.

    Returns a list of dicts with keys:
      warning_id, dtg, number, year, header_refs, raw_text
    """
    if not memo_text:
        return []
    text = rejoin_wrapped_coords(memo_text) if rejoin else memo_text
    lines = text.split("\n")

    starts = []  # (start_line_index, dtg, header_match)
    for i, line in enumerate(lines):
        hm = RE_HEADER_LINE.match(line.strip())
        if not hm:
            continue
        dtg = None
        start = i
        if i >= 1:
            dm = RE_DTG_LINE.match(lines[i - 1].strip())
            if dm:
                dtg = dm.group(1)
                start = i - 1
            elif (
                i >= 2
                and lines[i - 1].strip() == "RMKS/"
                and lines[i - 2].strip().startswith("MSGID/")
            ):
                start = i - 2
        starts.append((start, dtg, hm))

    warnings = []
    for idx, (start, dtg, hm) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        raw_text = "\n".join(lines[start:end]).strip()
        if not raw_text:
            continue
        refs_raw = hm.group(3)
        header_refs = (
            [t.strip() for t in refs_raw.split(",") if t.strip()] if refs_raw else []
        )
        warnings.append({
            "warning_id": "NAVAREA XII %s/%s" % (hm.group(1), hm.group(2)),
            "dtg": dtg,
            "number": hm.group(1),
            "year": hm.group(2),
            "header_refs": header_refs,
            "raw_text": raw_text,
        })
    return warnings


# --- cross-references --------------------------------------------------------
def extract_cross_refs(warning: dict):
    """Structured cross-references for a block from split_into_warnings().

    Kinds:
      - "cancellation": body "CANCEL NAVAREA XII n/yy" — the referenced warning
        is superseded by this one. "CANCEL THIS MSG ..." self-cancels are NOT
        references and never match.
      - "header_ref": numeric tokens in the header parentheses, e.g.
        "NAVAREA XII 150/26(21,22)". CAUTION: NGA also uses parenthesised
        broadcast-category codes ("(18)" = rocket launching, "(GEN)", ...), so
        header refs are recorded but must NOT be treated as supersede
        instructions without review.

    Returns a list of {"number", "year", "kind", "source"} dicts.
    """
    if not warning:
        return []
    refs = []
    for token in warning.get("header_refs") or []:
        token = token.strip()
        if re.fullmatch(r"\d{1,3}", token):
            refs.append({
                "number": token.zfill(3),
                "year": warning.get("year"),
                "kind": "header_ref",
                "source": "header_paren",
            })
    for m in RE_CANCEL_REF.finditer(warning.get("raw_text") or ""):
        refs.append({
            "number": m.group(1).zfill(3),
            "year": m.group(2),
            "kind": "cancellation",
            "source": "body_cancel",
        })
    return refs


# --- sub-areas ---------------------------------------------------------------
RE_SUBAREA_MARKER = re.compile(r"^\s{0,3}([A-Z])\.\s+")
RE_ITEM_LINE = re.compile(r"^\s*\d\.\s")


def split_sub_areas(raw_text: str):
    """Split a warning body into A./B./C. labelled sub-areas.

    Each sub-area becomes its own geometry record (the sync upsert key includes
    sub_area). A sub-area ends at the next sub-area marker or at the next
    numbered item line ("2. CANCEL THIS MSG ..."), whichever comes first.

    Returns [{"label": "A", "text": ...}, ...]; warnings without markers return
    [{"label": None, "text": raw_text}] (single geometry record).
    """
    if not raw_text:
        return []
    lines = raw_text.split("\n")
    marks = []
    for i, line in enumerate(lines):
        m = RE_SUBAREA_MARKER.match(line)
        if m:
            marks.append((i, m.group(1)))
    if not marks:
        return [{"label": None, "text": raw_text}]

    out = []
    for j, (start, label) in enumerate(marks):
        end = marks[j + 1][0] if j + 1 < len(marks) else len(lines)
        for k in range(start + 1, end):
            if RE_ITEM_LINE.match(lines[k]):
                end = k
                break
        seg = "\n".join(lines[start:end]).strip()
        if seg:
            out.append({"label": label, "text": seg})
    return out


def normalize_memo(memo_text: str):
    """Full preprocessing pipeline: rejoin wrapped coordinates, then segment."""
    return split_into_warnings(memo_text, rejoin=True)
