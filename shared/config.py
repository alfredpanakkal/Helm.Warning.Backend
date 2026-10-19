#!/usr/bin/env python3
"""
shared/config.py — Centralized Configuration Management & Pre-Flight Validation
Validates environment settings, database connections, feed policies, and AI parameters at startup.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List
from shared.exceptions import ConfigurationError
from shared.logging import get_logger

logger = get_logger("config")


@dataclass
class SupabaseConfig:
    url: str
    key: str
    timeout: int = 30

    def validate(self, errors: Optional[List[str]] = None) -> bool:
        """Validates Supabase connection credentials."""
        valid = True
        errs = errors if errors is not None else []

        if not self.url:
            errs.append("SUPABASE_URL is required.")
            valid = False
        elif not (self.url.startswith("http://") or self.url.startswith("https://")):
            errs.append(f"Invalid SUPABASE_URL: must start with https:// or http:// (got {self.url[:20]}...)")
            valid = False

        if not self.key:
            errs.append("SUPABASE_KEY is required.")
            valid = False
        elif len(self.key) < 20:
            errs.append("SUPABASE_KEY appears truncated or invalid (too short).")
            valid = False

        return valid


@dataclass
class AIConfig:
    api_key: str
    model_name: str = "gemini-3.1-flash-lite"
    enabled: bool = False
    timeout: float = 10.0
    temperature: float = 0.0

    def validate(self, errors: Optional[List[str]] = None) -> bool:
        """Validates AI grounding configuration."""
        valid = True
        errs = errors if errors is not None else []

        if self.enabled:
            if not self.api_key:
                errs.append("GEMINI_API_KEY is required when NAVWARN_AI_ENABLED is true.")
                valid = False
            elif self.api_key in ("YOUR_GEMINI_API_KEY_HERE", "mock_key"):
                errs.append("GEMINI_API_KEY contains placeholder value.")
                valid = False

            if not self.model_name:
                errs.append("GEMINI_MODEL_NAME cannot be empty when AI is enabled.")
                valid = False
        return valid


@dataclass
class FeedPolicyConfig:
    mode: str = "escalate_and_continue"  # "escalate_and_continue" | "strict_abort"
    min_feed_size_for_cancel: int = 5
    max_warning_age_days: int = 30

    def validate(self, errors: Optional[List[str]] = None) -> bool:
        valid = True
        errs = errors if errors is not None else []
        if self.mode not in ("escalate_and_continue", "strict_abort"):
            errs.append(f"Invalid feed policy mode '{self.mode}'. Use 'escalate_and_continue' or 'strict_abort'.")
            valid = False
        if self.min_feed_size_for_cancel < 0:
            errs.append("min_feed_size_for_cancel must be >= 0.")
            valid = False
        return valid


@dataclass
class AppConfig:
    supabase: SupabaseConfig
    ai: AIConfig
    feed_policy: FeedPolicyConfig = field(default_factory=FeedPolicyConfig)
    log_level: str = "INFO"
    log_file: Optional[str] = None
    redis_host: Optional[str] = None
    redis_port: int = 6379
    prometheus_port: int = 8000

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Loads configuration from environment variables with safe defaults."""
        return cls(
            supabase=SupabaseConfig(
                url=os.getenv("SUPABASE_URL", "").strip(),
                key=os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip(),
                timeout=int(os.getenv("SUPABASE_TIMEOUT", "30")),
            ),
            ai=AIConfig(
                api_key=os.getenv("GEMINI_API_KEY", "").strip(),
                model_name=os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite").strip(),
                enabled=os.getenv("NAVWARN_AI_ENABLED", "false").lower() in ("true", "1", "yes"),
                timeout=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "10.0")),
                temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.0")),
            ),
            feed_policy=FeedPolicyConfig(
                mode=os.getenv("NAVWARN_FEED_MODE", "escalate_and_continue").lower().strip(),
                min_feed_size_for_cancel=int(os.getenv("MIN_FEED_SIZE_FOR_CANCEL", "5")),
                max_warning_age_days=int(os.getenv("MAX_WARNING_AGE_DAYS", "30")),
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
            log_file=os.getenv("LOG_FILE", None),
            redis_host=os.getenv("REDIS_HOST", None),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            prometheus_port=int(os.getenv("PROMETHEUS_PORT", "8000")),
        )

    def validate(self, require_db: bool = False) -> bool:
        """Validates all sub-configurations."""
        errors: List[str] = []
        if require_db:
            self.supabase.validate(errors)
        self.ai.validate(errors)
        self.feed_policy.validate(errors)

        if errors:
            for err in errors:
                logger.error(f"Configuration error: {err}")
            return False
        return True

    def validate_or_raise(self, require_db: bool = False) -> None:
        """Validates configuration and raises ConfigurationError if invalid."""
        errors: List[str] = []
        if require_db:
            self.supabase.validate(errors)
        self.ai.validate(errors)
        self.feed_policy.validate(errors)

        if errors:
            raise ConfigurationError(
                f"Configuration failed validation with {len(errors)} error(s): " + "; ".join(errors),
                context={"errors": errors}
            )
