#!/usr/bin/env python3
"""
shared/models.py - Data models for NAVAREA warnings
Defines the data structures used throughout the scraping pipeline.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import json

@dataclass
class RawCoordinate:
    """Represents a raw coordinate string."""
    lat_deg: str
    lat_min: str
    lat_sec: Optional[str] = None
    lat_dir: str = "N"
    lon_deg: str
    lon_min: str
    lon_sec: Optional[str] = None
    lon_dir: str = "E"

    def to_string(self) -> str:
        """Convert to display string format."""
        lat_str = f"{self.lat_deg}-{self.lat_min}"
        if self.lat_sec:
            lat_str += f"-{self.lat_sec}"
        lat_str += self.lat_dir

        lon_str = f"{self.lon_deg}-{self.lon_min}"
        if self.lon_sec:
            lon_str += f"-{self.lon_sec}"
        lon_str += self.lon_dir

        return f"{lat_str} {lon_str}"

@dataclass
class ParsedData:
    """Container for all parsed data from a scrape."""
    raw_messages: List[Dict[str, Any]] = field(default_factory=list)
    nav_warnings: List[Dict[str, Any]] = field(default_factory=list)
    spatial_features: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "raw_messages": self.raw_messages,
            "nav_warnings": self.nav_warnings,
            "spatial_features": self.spatial_features
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParsedData":
        """Create from dictionary."""
        return cls(
            raw_messages=data.get("raw_messages", []),
            nav_warnings=data.get("nav_warnings", []),
            spatial_features=data.get("spatial_features", [])
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ParsedData":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
