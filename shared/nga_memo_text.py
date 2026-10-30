#!/usr/bin/env python3
"""
shared/nga_memo_text.py — Generalized NGA Daily Memo text preprocessing.

Both NAVAREA XII (DailyMemXII.txt) and NAVAREA IV (DailyMemIV.txt) publish
their in-force warnings as plain-text NGA daily memos with an identical
structure ("NAVAREA <ID> IN FORCE AS OF <DTG>", DTG-prefixed blocks,
A./B./C. sub-areas, CANCEL cross-references). This module implements the
shared, parameterized preprocessing; per-area wrappers bind a configuration:

  shared/navarea_xii_text.py  -> NgaMemoPreprocessor("XII", ref_zfill=3)
  shared/navarea_iv_text.py   -> NgaMemoPreprocessor("IV", ref_zfill=None,
                                  max_subarea_label_len=4,
                                  require_coords_in_subarea=True)

Pure text transforms applied BEFORE deterministic parsing and BEFORE any
AI-fallback grounding (H05):
  - rejoin_wrapped_coords(): repair coordinate tokens split across line wraps
  - split_into_warnings():   DTG-header segmentation of the daily memo
  - extract_cross_refs():    header-paren refs + body "CANCEL NAVAREA <ID> n/yy" refs
  - split_sub_areas():       A./B./C. sub-area split (one geometry record each)
  - extract_geometry_clauses(): clause-level geometry segmentation with
    trackline classification (see below)
  - normalize_memo():        rejoin + segmentation pipeline

Trackline contract: clauses whose text (or item preamble) says
"TRACKLINE(S) JOINING" describe an OPEN line — an iceberg/sea-ice limit or a
survey/cable track — never a closed area. The clause dict carries
is_trackline=True; the parser then converts any ring the shared coordinate
parser produced into an open LineString via ring_to_trackline(). Without
this, e.g. NAVAREA IV 206/26's limits render as filled polygons that shade
the safe water south of the limit instead of the ice north of it.

No coordinate parsing or conversion happens here. Geometry always comes from
shared.utils.parse_coordinates (no-second-parser rule).
"""

import re

from shared.utils import rejoin_wrapped_coords as _shared_rejoin_wrapped_coords
from shared.utils import _REJOIN_WRAP_SPECS as _SHARED_WRAP_SPECS


def ring_to_trackline(spatial):
    """Convert a closed Polygon ring into an open LineString.

    Applies to trackline clauses only ("LIMIT/TRACKLINE JOINING"): the
    ring's duplicated closing vertex is dropped so the geometry renders as
    a boundary stroke, not a filled area. Non-Polygon inputs are returned
    unchanged.
    """
    if not isinstance(spatial, dict) or spatial.get("type") != "Polygon":
        return spatial
    rings = spatial.get("coordinates") or []
    if not rings:
        return spatial
    ring = list(rings[0] or [])
    if len(ring) > 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return {"type": "LineString", "coordinates": ring}


class NgaMemoPreprocessor:
    """Parameterized NGA daily memo preprocessor for one NAVAREA."""

    RE_COORD_TOKEN = re.compile(r"^(\d{1,3})-(\d{1,2}(?:\.\d{1,4})?)([NSEW])$")
    RE_DTG_LINE = re.compile(r"^(\d{6}Z\s+[A-Za-z]{3}\s+\d{2})$")
    RE_IN_FORCE = re.compile(r"IN\s+FORCE\s+AS\s+OF\s+(\d{6}Z\s+[A-Z]{3})", re.IGNORECASE)
    RE_ITEM_LINE = re.compile(r"^\s*\d\.\s")
    RE_ITEM_NUM = re.compile(r"^\s*(\d{1,2})\.\s")
    RE_COORD_PAIR = re.compile(
        r"\d{2,3}-\d{2}(?:\.\d+)?[NS]\s+\d{2,3}-\d{2}(?:\.\d+)?[EW]", re.IGNORECASE
    )
    RE_HEADER_PAREN_CONT = re.compile(r"^\(([^)]*)\)\.?$")
    RE_TRACKLINE_CLAUSE = re.compile(r"\bTRACKLINES?\s+JOINING\b", re.IGNORECASE)

    # Dedup (2026-10-30): the memo-local wrap specs were a byte-identical
    # copy of shared/utils.py, minus its CRLF-tolerant _WRAP. The class now
    # delegates rejoining to the canonical shared implementation;
    # _WRAP_SPECS aliases the shared specs for backward compatibility
    # (navarea_xii_text re-exports RE_SPLIT_TOKEN = _impl._WRAP_SPECS[0][0]).
    _WRAP_SPECS = _SHARED_WRAP_SPECS

    def __init__(self, navarea_id, ref_zfill=None, max_subarea_label_len=1,
                 require_coords_in_subarea=False):
        self.navarea_id = navarea_id
        # Zero-pad width for cross-reference numbers (XII memos use 3-digit
        # padded ids; IV memos use unpadded ids and the DB canonical_id must
        # match the memo header verbatim).
        self.ref_zfill = ref_zfill
        self.require_coords_in_subarea = require_coords_in_subarea
        self.re_header_line = re.compile(
            rf"^NAVAREA\s+{navarea_id}\s+(\d+)/(\d{{2}})(?:\(([^)]*)\))?\.?$",
            re.IGNORECASE,
        )
        self.re_cancel_refs = re.compile(
            rf"\bCANCEL\s+NAVAREA\s+(?:{navarea_id}\s+)?"
            rf"((?:\d+/\d{{2}})(?:\s*,\s*\d+/\d{{2}})*)",
            re.IGNORECASE,
        )
        self.re_subarea_marker = re.compile(
            rf"^\s{{0,3}}([A-Z]{{1,{max_subarea_label_len}}})\.\s"
        )

    # --- rejoin_wrapped_coords ----------------------------------------------
    def rejoin_wrapped_coords(self, text: str) -> str:
        """Delegates to the canonical shared.utils implementation.

        One rejoin implementation for every parse path (no-second-parser
        rule): parse_coordinates() and the IV/XII memo pipeline share the
        same wrap specs, including the CRLF-tolerant wrap handling the
        old memo-local copy lacked. Idempotent; only merges fragments
        that form a valid coordinate token; prose word-wraps untouched.
        """
        return _shared_rejoin_wrapped_coords(text)

    # --- segmentation --------------------------------------------------------
    def get_in_force_dtg(self, memo_text: str):
        """DTG of the memo's 'IN FORCE AS OF' line (scraper idempotency marker)."""
        if not memo_text:
            return None
        m = self.RE_IN_FORCE.search(memo_text)
        return m.group(1) if m else None

    def split_into_warnings(self, memo_text: str, rejoin: bool = True):
        """Segment the daily memo into warning blocks at header lines.

        Primary anchor: a DTG line ("040124Z MAR 26") immediately above a
        "NAVAREA <ID> n/yy(refs)." header line. Legacy blocks without a DTG
        (MSGID/GENADMIN ... RMKS/ prefixed) start at the header line, and when
        the two preceding lines are MSGID/RMKS they are included in the block.
        Header parens wrapped to the next line ("NAVAREA IV 113/26\\n(26).")
        are treated as part of the header.

        Returns a list of dicts with keys:
          warning_id, dtg, number, year, header_refs, raw_text
        """
        if not memo_text:
            return []
        text = self.rejoin_wrapped_coords(memo_text) if rejoin else memo_text
        lines = text.split("\n")

        starts = []  # (start_line_index, dtg, header_match, header_line_index)
        for i, line in enumerate(lines):
            hm = self.re_header_line.match(line.strip())
            if not hm:
                continue
            dtg = None
            start = i
            if i >= 1:
                dm = self.RE_DTG_LINE.match(lines[i - 1].strip())
                if dm:
                    dtg = dm.group(1)
                    start = i - 1
                elif (
                    i >= 2
                    and lines[i - 1].strip() == "RMKS/"
                    and lines[i - 2].strip().startswith("MSGID/")
                ):
                    start = i - 2
            starts.append((start, dtg, hm, i))

        warnings = []
        for idx, (start, dtg, hm, hline) in enumerate(starts):
            end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
            raw_text = "\n".join(lines[start:end]).strip()
            if not raw_text:
                continue
            refs_raw = hm.group(3)
            if not refs_raw and hline + 1 < len(lines):
                cm = self.RE_HEADER_PAREN_CONT.match(lines[hline + 1].strip())
                if cm:
                    refs_raw = cm.group(1)
            header_refs = (
                [t.strip() for t in refs_raw.split(",") if t.strip()] if refs_raw else []
            )
            warnings.append({
                "warning_id": "NAVAREA %s %s/%s" % (self.navarea_id, hm.group(1), hm.group(2)),
                "dtg": dtg,
                "number": hm.group(1),
                "year": hm.group(2),
                "header_refs": header_refs,
                "raw_text": raw_text,
            })
        return warnings

    # --- cross-references ----------------------------------------------------
    def extract_cross_refs(self, warning: dict):
        """Structured cross-references for a block from split_into_warnings().

        Kinds:
          - "cancellation": body "CANCEL NAVAREA <ID> n/yy[, m/yy]" — the
            referenced warnings are superseded. "CANCEL THIS MSG ..." self-
            cancels never match.
          - "header_ref": numeric tokens in the header parentheses. Review
            decision (carried over from XII): header parens ARE cross-
            references — the sync layer marks referenced warnings SUPERSEDED.
            Non-numeric tokens like "(GEN)" are broadcast-category codes and
            are ignored.

        Returns a list of {"number", "year", "kind", "source"} dicts.
        """
        if not warning:
            return []
        refs = []
        for token in warning.get("header_refs") or []:
            token = token.strip()
            if re.fullmatch(r"\d{1,4}", token):
                number = token.zfill(self.ref_zfill) if self.ref_zfill else token
                refs.append({
                    "number": number,
                    "year": warning.get("year"),
                    "kind": "header_ref",
                    "source": "header_paren",
                })
        seen = set()
        for m in self.re_cancel_refs.finditer(warning.get("raw_text") or ""):
            for tok in [t.strip() for t in m.group(1).split(",") if t.strip()]:
                if "/" not in tok:
                    continue
                number, year = tok.split("/", 1)
                if (number, year) in seen:
                    continue
                seen.add((number, year))
                if self.ref_zfill:
                    number = number.zfill(self.ref_zfill)
                refs.append({
                    "number": number,
                    "year": year,
                    "kind": "cancellation",
                    "source": "body_cancel",
                })
        return refs

    # --- sub-areas ------------------------------------------------------------
    def _segment_end(self, lines, marks, j):
        end = marks[j + 1][0] if j + 1 < len(marks) else len(lines)
        for k in range(marks[j][0] + 1, end):
            if self.RE_ITEM_LINE.match(lines[k]):
                return k
        return end

    def split_sub_areas(self, raw_text: str):
        """Split a warning body into A./B./C. labelled sub-areas.

        Each sub-area becomes its own geometry record. A sub-area ends at the
        next sub-area marker or at the next numbered item line, whichever
        comes first.

        When require_coords_in_subarea is enabled (NAVAREA IV), a candidate
        marker line is accepted only if its segment actually contains a
        coordinate pair. This rejects title-line false positives such as
        "ST. KITTS AND NEVIS." (1524/24) while keeping every legitimate
        marker — including markers whose coordinates continue on the next
        line (e.g. "R. (NEW POSITION) DEEPWATER PONTUS\\n 27-35.9N ...").

        Returns [{"label": "A", "text": ...}, ...]; warnings without markers
        return [{"label": None, "text": raw_text}] (single geometry record).
        """
        if not raw_text:
            return []
        lines = raw_text.split("\n")
        marks = []
        for i, line in enumerate(lines):
            m = self.re_subarea_marker.match(line)
            if m:
                marks.append((i, m.group(1)))
        if not marks:
            return [{"label": None, "text": raw_text}]

        if self.require_coords_in_subarea:
            kept = []
            for j, (start, label) in enumerate(marks):
                end = self._segment_end(lines, marks, j)
                segment = "\n".join(lines[start:end])
                if self.RE_COORD_PAIR.search(segment):
                    kept.append((start, label))
            if not kept:
                return [{"label": None, "text": raw_text}]
            marks = kept

        out = []
        for j, (start, label) in enumerate(marks):
            end = self._segment_end(lines, marks, j)
            segment = "\n".join(lines[start:end]).strip()
            if segment:
                out.append({"label": label, "text": segment})
        return out

    # --- geometry clauses -----------------------------------------------------
    def extract_geometry_clauses(self, raw_text: str):
        """Segment a warning body into geometry clauses (parser-facing).

        A clause is one numbered item, or one A./B./C. sub-area within an
        item. Unlike split_sub_areas(), clauses also cover UNMARKED numbered
        items, so limits declared as "2. ICEBERG LIMIT ALONG TRACKLINE
        JOINING ..." become their own geometry records instead of being
        silently dropped or merged.

        Each clause dict:
          label        — "Item N" for unmarked items; the marker letter for
                         sub-areas; None for markerless, itemless warnings.
                         Duplicate marker labels across items are
                         disambiguated as "N.L" (e.g. "5.A").
          text         — the clause's verbatim text (coordinates live here).
          context      — the classification scope (item preamble + clause
                         text): the governing keyword ('IN AREAS BOUND BY',
                         'ALONG TRACKLINES JOINING') often lives in the
                         preamble, outside the sub-area segment.
          is_trackline — True when the clause or its item preamble says
                         "TRACKLINE(S) JOINING": the geometry is an open
                         boundary/survey line, not a closed area. The parser
                         applies ring_to_trackline() to these clauses.

        Markers that appear before any numbered item ("LIGHTS UNLIT:\\nA. ...")
        are handled via an implicit item context, matching the legacy
        split_sub_areas() behavior. When require_coords_in_subarea is
        enabled, coordinate-less marker segments are rejected and the item
        falls back to a single whole-item clause (never loses geometry).

        Returns [{"label", "text", "is_trackline"}, ...]; empty text -> [].
        """
        if not raw_text:
            return []
        lines = raw_text.split("\n")

        events = []  # (line_index, kind, value)
        for i, line in enumerate(lines):
            m = self.RE_ITEM_NUM.match(line)
            if m:
                events.append((i, "item", m.group(1)))
                continue
            m = self.re_subarea_marker.match(line)
            if m:
                events.append((i, "mark", m.group(1)))

        if not events:
            return [{
                "label": None,
                "text": raw_text,
                "context": raw_text,
                "is_trackline": bool(self.RE_TRACKLINE_CLAUSE.search(raw_text)),
            }]

        # Implicit item context for warnings whose markers are not preceded
        # by any numbered item (e.g. "LIGHTS UNLIT:\\nA. BOSTON ...").
        if events[0][1] == "mark":
            events.insert(0, (0, "item", None))

        clauses = []  # dicts + private "_item" for label disambiguation
        n = len(events)
        e = 0
        while e < n:
            start, kind, item_num = events[e]
            if kind != "item":
                e += 1
                continue

            # Item ends at the next item event (or end of block).
            item_end = len(lines)
            for k in range(e + 1, n):
                if events[k][1] == "item":
                    item_end = events[k][0]
                    break
            marks = [ev for ev in events[e + 1:] if ev[1] == "mark" and ev[0] < item_end]

            def _emit(label, text, context, item=item_num):
                if not text:
                    return
                clauses.append({
                    "label": label,
                    "text": text,
                    "context": context,
                    "is_trackline": bool(self.RE_TRACKLINE_CLAUSE.search(context)),
                    "_item": item,
                })

            if not marks:
                text = "\n".join(lines[start:item_end]).strip()
                _emit(("Item %s" % item_num) if item_num else None, text, text)
            else:
                preamble = "\n".join(lines[start:marks[0][0]])
                kept = marks
                if self.require_coords_in_subarea:
                    kept = []
                    for j, (mstart, _kind, mlabel) in enumerate(marks):
                        mend = marks[j + 1][0] if j + 1 < len(marks) else item_end
                        if self.RE_COORD_PAIR.search("\n".join(lines[mstart:mend])):
                            kept.append((mstart, _kind, mlabel))
                if kept:
                    for j, (mstart, _kind, mlabel) in enumerate(kept):
                        mend = kept[j + 1][0] if j + 1 < len(kept) else item_end
                        seg = "\n".join(lines[mstart:mend]).strip()
                        context = (preamble + "\n" + seg) if preamble else seg
                        _emit(mlabel, seg, context)
                else:
                    # All candidate markers were false positives: keep the
                    # geometry by falling back to the whole item.
                    text = "\n".join(lines[start:item_end]).strip()
                    _emit(("Item %s" % item_num) if item_num else None, text, text)
            e += 1

        # Disambiguate duplicate marker labels across items ("A" in items 1
        # and 5 -> "1.A" / "5.A"). Item labels are already unique.
        from collections import Counter
        mark_labels = Counter(
            c["label"] for c in clauses if c["label"] and not str(c["label"]).startswith("Item ")
        )
        for c in clauses:
            label = c["label"]
            if (
                label
                and not str(label).startswith("Item ")
                and mark_labels[label] > 1
                and c.get("_item")
            ):
                c["label"] = "%s.%s" % (c["_item"], label)
            c.pop("_item", None)
        return clauses

    def normalize_memo(self, memo_text: str):
        """Full preprocessing pipeline: rejoin wrapped coordinates, then segment."""
        return self.split_into_warnings(memo_text, rejoin=True)
