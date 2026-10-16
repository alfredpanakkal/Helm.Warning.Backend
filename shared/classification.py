#!/usr/bin/env python3
"""
shared/classification.py - Hazard classification for navigational warnings
Classifies maritime warnings into hazard categories based on terminology.
"""

import re
from typing import List, Optional

def classify_hazard(raw_text: str) -> str:
    """
    Classify maritime hazard category based on terminology in the warning text.

    Categories (in priority order):
    1. electronic - GNSS, DGPS, AIS, radar interference
    2. military - Detonations, firing, gunnery, missile, weapons
    3. aton - Light, buoy, racón, beacon, unlit, extinguished
    4. subsea - Seismic, cable, pipeline, ROV, towing, dredging
    5. drifting - Drifting, derelict, mine, container, adrift
    6. offshore - Rig, platform, jack-up
    7. general - All other warnings
    """
    text = raw_text.upper()

    # 1. Electronic / GNSS interference
    electronic_keywords = [
        "GNSS", "DGPS", "AIS INTERFERENCE", "RADAR INTERFERENCE",
        "INTERFERENCE OBSERVED", "JAMMING", "SPOOFING"
    ]
    if any(k in text for k in electronic_keywords):
        return "electronic"

    # 2. Military / Naval operations
    military_pattern = r'\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|NAVAL EXERCISES|MILITARY EXERCISE)\b'
    if re.search(military_pattern, text):
        return "military"

    # 3. Aids to Navigation (AtoN)
    aton_keywords = [
        "LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON",
        "UNLIT", "EXTINGUISHED", "OFF AIR"
    ]
    if any(k in text for k in aton_keywords):
        return "aton"

    # 4. Subsea / Obstruction
    subsea_keywords = [
        "SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING",
        "DREDGING", "ANCHOR", "CHAIN LOST", "SUNKEN WRECK"
    ]
    if any(k in text for k in subsea_keywords):
        return "subsea"

    # 5. Drifting hazards
    drifting_keywords = [
        "DRIFTING", "DERELICT", "MINE", "CONTAINER",
        "ADRIFT", "SPACE DEBRIS"
    ]
    if any(k in text for k in drifting_keywords):
        return "drifting"

    # 6. Offshore operations
    offshore_keywords = ["RIG", "PLATFORM", "JACK-UP"]
    if any(k in text for k in offshore_keywords):
        return "offshore"

    # 7. General (default)
    return "general"

def get_hazard_keywords(category: str) -> List[str]:
    """Get the list of keywords associated with a hazard category."""
    hazard_map = {
        "electronic": [
            "GNSS", "DGPS", "AIS INTERFERENCE", "RADAR INTERFERENCE",
            "INTERFERENCE OBSERVED", "JAMMING", "SPOOFING"
        ],
        "military": [
            "DETONATION", "DETONATIONS", "FIRING", "FIRINGS", "GUNNERY",
            "MISSILE", "WEAPON", "WEAPONS", "ARMED FORCES",
            "NAVAL EXERCISE", "NAVAL EXERCISES", "MILITARY EXERCISE"
        ],
        "aton": [
            "LIGHT", "LIGHTS", "BUOY", "BUOYS", "RACON", "BEACON",
            "UNLIT", "EXTINGUISHED", "OFF AIR"
        ],
        "subsea": [
            "SEISMIC", "CABLE", "PIPELINE", "ROV", "TOWING",
            "DREDGING", "ANCHOR", "CHAIN LOST", "SUNKEN WRECK"
        ],
        "drifting": [
            "DRIFTING", "DERELICT", "MINE", "CONTAINER",
            "ADRIFT", "SPACE DEBRIS"
        ],
        "offshore": ["RIG", "PLATFORM", "JACK-UP"],
        "general": []
    }
    return hazard_map.get(category, [])

def validate_category(category: str) -> bool:
    """Validate that a category is a known hazard category."""
    valid_categories = [
        "electronic", "military", "aton", "subsea",
        "drifting", "offshore", "general"
    ]
    return category in valid_categories

def get_all_categories() -> List[str]:
    """Get list of all valid hazard categories."""
    return [
        "electronic", "military", "aton", "subsea",
        "drifting", "offshore", "general"
    ]
