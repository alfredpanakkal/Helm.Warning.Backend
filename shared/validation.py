#!/usr/bin/env python3
"""
shared/validation.py — Schema & Input Validation Framework
Provides robust validation for warning records, coordinate tokens, and public function parameters.
"""

import re
from functools import wraps
from typing import Any, Callable, Dict, List, Optional
from shared.exceptions import ValidationError


def validate_coordinate_token(token: Any) -> str:
    """Validates and normalizes coordinate token strings."""
    if token is None or not isinstance(token, str):
        raise ValidationError(
            f"Invalid coordinate token type: expected string, got {type(token).__name__}",
            context={"token": str(token)}
        )
    cleaned = token.strip()
    if not cleaned:
        raise ValidationError("Coordinate token cannot be empty", context={"token": token})
    if len(cleaned) > 100:
        raise ValidationError(
            f"Coordinate token exceeds maximum length of 100 characters ({len(cleaned)})",
            context={"token": token[:50]}
        )
    return cleaned


def validate_warning_id(warning_id: Any) -> str:
    """Validates maritime warning identifier format."""
    if warning_id is None or not isinstance(warning_id, str):
        raise ValidationError(
            f"Invalid warning ID type: expected string, got {type(warning_id).__name__}",
            context={"warning_id": str(warning_id)}
        )
    cleaned = warning_id.strip()
    if not cleaned:
        raise ValidationError("Warning ID cannot be empty", context={"warning_id": warning_id})
    if len(cleaned) > 120:
        raise ValidationError(
            f"Warning ID exceeds maximum length of 120 characters ({len(cleaned)})",
            context={"warning_id": warning_id[:50]}
        )
    # Permitted characters: alphanumeric, spaces, dashes, slashes, brackets, periods
    if not re.match(r"^[A-Za-z0-9\s\-/_.,\[\]#]+$", cleaned):
        raise ValidationError(
            f"Warning ID contains invalid characters: {cleaned}",
            context={"warning_id": cleaned}
        )
    return cleaned


def validate_raw_text(text: Any, max_length: int = 500000) -> str:
    """Validates raw bulletin corpus text."""
    if text is None:
        raise ValidationError("Raw text cannot be None")
    if not isinstance(text, str):
        raise ValidationError(f"Expected raw text as str, got {type(text).__name__}")
    if len(text) > max_length:
        raise ValidationError(
            f"Corpus size {len(text)} exceeds safety threshold {max_length}",
            context={"length": len(text), "max_length": max_length}
        )
    return text


def validate_lat_lon(lat: Optional[float], lon: Optional[float]) -> bool:
    """Strict range check for decimal coordinates."""
    if lat is None or lon is None:
        return False
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90.0 <= lat_f <= 90.0):
        return False
    if not (-180.0 <= lon_f <= 180.0):
        return False
    return True


def validate_nav_warning_dict(record: Dict[str, Any]) -> Dict[str, Any]:
    """Validates warning dictionary before database operations."""
    if not isinstance(record, dict):
        raise ValidationError("Warning record must be a dictionary", context={"type": type(record).__name__})

    # Required fields
    warning_id = validate_warning_id(record.get("warning_id"))
    record["warning_id"] = warning_id

    # Coordinates validation if present
    lat = record.get("latitude")
    lon = record.get("longitude")
    if lat is not None or lon is not None:
        if not validate_lat_lon(lat, lon):
            raise ValidationError(
                f"Invalid latitude ({lat}) or longitude ({lon}) bounds in warning {warning_id}",
                context={"warning_id": warning_id, "lat": lat, "lon": lon}
            )

    # Status validation
    status = record.get("status", "active")
    if status not in ("active", "cancelled", "archived"):
        raise ValidationError(
            f"Invalid warning status '{status}' in warning {warning_id}",
            context={"warning_id": warning_id, "status": status}
        )

    # Triage tier validation if present
    tier = record.get("triage_tier")
    if tier is not None and str(tier) not in ("A", "B", "C"):
        raise ValidationError(
            f"Invalid triage tier '{tier}' in warning {warning_id}",
            context={"warning_id": warning_id, "triage_tier": tier}
        )

    return record


def validate_public_inputs(func: Callable) -> Callable:
    """Decorator to enforce non-null arguments on public API functions."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Check non-null args
        for i, arg in enumerate(args):
            if arg is None:
                raise ValidationError(
                    f"Null positional argument at index {i} in {func.__name__}",
                    context={"func": func.__name__, "arg_index": i}
                )
        for k, v in kwargs.items():
            if v is None and k not in ("log_file", "context", "key_func", "direction", "direction_or_seconds"):
                raise ValidationError(
                    f"Null keyword argument '{k}' in {func.__name__}",
                    context={"func": func.__name__, "param": k}
                )
        return func(*args, **kwargs)
    return wrapper
