"""Canonical three-level maritime hazard severity.

Severity describes navigational risk, not parser confidence (triage A/B/C).
The backend is the source of truth; unknown/low-risk notices default to
moderate rather than being silently promoted.
"""
from __future__ import annotations

import re
from typing import Iterable

VALID_SEVERITIES = frozenset({"critical", "high", "moderate"})

# Require operational context for SAR: a NAVAREA index may contain a list of
# SAR warning numbers without describing an active search-and-rescue incident.
_CRITICAL_TEXT = re.compile(
    r"\b(?:DRIFTING\s+MINE|SEA\s+MINE|MINES?|DISTRESS\s+ALERT|"
    r"SAR\s+(?:OPERATION|CASE|INCIDENT|ALERT|IN\s+PROGRESS|UNDERWAY)|"
    r"SEARCH\s+AND\s+RESCUE|MAN\s+OVERBOARD|PERSON\s+OVERBOARD|"
    r"GUNNERY|FIRING\s+EXERCISE|LIVE\s+WEAPON\s+FIRING|"
    r"LIVE\s+FIRING\s+PRACTICE|FIRING\s+PRACTICE|PRACTICE\s+FIRING|"
    r"MILITARY\s+FIRING|MISSILE\s+FIRING|NAVAL\s+FIRING|"
    r"ROCKET\s+LAUNCH(?:ING)?|TSUNAMI|CYCLONE|TYPHOON|HURRICANE)\b",
    re.IGNORECASE,
)
_HIGH_TEXT = re.compile(
    r"\b(?:UNEXPLODED\s+ORDNANCE|ORDNANCE\s+DISPOSAL|EXPLOSIVE\s+ORDNANCE|"
    r"SECURITY\s+ADVISORY|SECURITY\s+INCIDENT|PIRACY|SUSPICIOUS\s+SKIFF|ATTACK|BOARDED|"
    r"DERELICT|ADRIFT|SUNK|SANK|SINKING|DRIFTING\s+(?:VESSEL|BARGE|CONTAINER|HATCH)|"
    r"ICEBERG|SEA\s+ICE|DANGEROUS\s+WRECK|SUNKEN\s+WRECK|"
    r"SUBMERGED\s+OBSTRUCTION|OBSTRUCTION|COLLISION|UNLIT|DAMAGED|"
    r"DESTROYED|OFF\s+STATION|UNDER\s+TOW|ALERT)\b",
    re.IGNORECASE,
)
_MILITARY_FIRING_TEXT = re.compile(
    r"\b(?:FIRING|FIRINGS|GUNNERY|WEAPON\s+FIRING)\b",
    re.IGNORECASE,
)


def determine_hazard_severity(raw_text: str, categories: Iterable[str] | None = None) -> str:
    """Return critical/high/moderate from source wording and canonical categories.

    Any explicit critical hazard wins over secondary categories. Military
    firing requires both source-text evidence and a military category; this
    avoids promoting unrelated bulletins from a noisy category alone.
    High-risk hazards are next. Other operational/chart/service notices remain
    moderate. This does not inspect or infer parser triage, geometry, or
    verification.
    """
    text = raw_text if isinstance(raw_text, str) else ""
    cats = {str(category).strip().lower() for category in (categories or []) if category}

    # Category labels can be noisy (e.g. space-debris notices tagged mil_fire).
    # Critical promotion therefore requires source-text evidence.
    if _CRITICAL_TEXT.search(text):
        return "critical"
    if cats.intersection({"military", "mil_fire"}) and _MILITARY_FIRING_TEXT.search(text):
        return "critical"
    if _HIGH_TEXT.search(text) or cats.intersection({"uxo", "security", "drift", "drifting", "ice", "wreck"}):
        return "high"
    if "aton" in cats and re.search(r"\b(?:UNLIT|DAMAGED|DESTROYED|OFF\s+STATION|WITHDRAWN)\b", text, re.I):
        return "high"
    if "rig" in cats and re.search(r"\b(?:ALERT|UNDER\s+TOW|ADRIFT)\b", text, re.I):
        return "high"
    return "moderate"
