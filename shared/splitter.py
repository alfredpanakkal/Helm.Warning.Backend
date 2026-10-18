#!/usr/bin/env python3
"""shared/splitter.py — Stateful multi-dialect block splitter (Rule 106)."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

DIALECT_HEADERS = [
    # X — Australia
    re.compile(r"^(AUSCOAST\s+)?WARNING\s+\d+/\d+\s*$", re.I),
    # XIV — NZ (optional WARNING)
    re.compile(r"^NAVAREA\s+XIV(\s+WARNING)?\s+\d+/\d+\s*$", re.I),
    # generic NAVAREA n/yy
    re.compile(r"^NAVAREA\s+([IVX]+)\s+(\d{1,4})/(\d{2})\s*$", re.I),
    # XI — JCG Kaiho
    re.compile(r"^NO\.\d{2}-\d{4}\s+Date:", re.I),
    # V — Brazil bare serial
    re.compile(r"^\d{4}/\d{2}$"),
    # VI — Argentina
    re.compile(r"^NAVAREA\s+-\s*\d{4}-\d{4}\s*-\s*\d{2}/\d{2}/\d{4}", re.I),
]


@dataclass
class DialectState:
    current_area: str | None = None
    current_year: str | None = None   # XV section divider: "YEAR 2025"
    blocks: list[dict] = field(default_factory=list)


def split_corpus(text: str, state: DialectState | None = None) -> list[dict]:
    """Splits raw corpus text into header-attributed blocks.
    Handles: dashed separators (VIII), YEAR dividers (XV), ZCZC/NNNN
    envelopes (XVI), orphan fragments after CANCEL lines (VIII)."""
    st = state or DialectState()
    current: dict | None = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^YEAR\s+(\d{4})$", s, re.I)
        if m:
            st.current_year = m.group(1)
            continue
        if s in ("---", "- - -"):
            if current:
                st.blocks.append(current)
                current = None
            continue
        if s.startswith("ZCZC"):
            if current:
                st.blocks.append(current)
            current = {"area": st.current_area, "year": st.current_year, "lines": [], "envelope": "ZCZC"}
            continue
        if s == "NNNN":
            if current:
                st.blocks.append(current)
                current = None
            continue
        hit = next((h for h in DIALECT_HEADERS if h.match(s)), None)
        if hit:
            if current:
                st.blocks.append(current)
            current = {"area": st.current_area, "year": st.current_year, "lines": [s], "header": s}
            continue
        if current is not None:
            current["lines"].append(line)
        elif s:  # headerless content after a CANCEL
            st.blocks.append({
                "area": st.current_area,
                "year": st.current_year,
                "lines": [line],
                "orphan": True,
                "unplotted_reason": "orphan_fragment"
            })
    if current:
        st.blocks.append(current)
    return st.blocks
