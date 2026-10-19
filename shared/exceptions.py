#!/usr/bin/env python3
"""
shared/exceptions.py — Standardized Exception Hierarchy for Helm.Warning.Backend
Provides rich contextual error data for auditing and error tracing.
"""

from typing import Any, Dict, Optional


class NavWarnError(Exception):
    """Base exception for all NavWarn errors with contextual metadata."""
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        self.message = message
        self.context = context or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
        }

    def __str__(self) -> str:
        if self.context:
            ctx_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} ({ctx_str})"
        return self.message


class ValidationError(NavWarnError):
    """Input or schema validation failed."""
    pass


class ParseError(NavWarnError):
    """Coordinate, date, or bulletin parsing failed."""
    pass


class SyncError(NavWarnError):
    """Synchronization or database persistence failed."""
    pass


class AIValidationError(NavWarnError):
    """AI escalation or grounding returned invalid/unverifiable geometry."""
    pass


class ConfigurationError(NavWarnError):
    """Startup configuration missing or invalid."""
    pass


class CircuitBreakerError(NavWarnError):
    """Circuit breaker execution failed or tripped."""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """Circuit breaker is currently OPEN, blocking requests."""
    pass
