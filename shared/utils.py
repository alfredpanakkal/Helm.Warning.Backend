#!/usr/bin/env python3
"""
shared/utils.py - Common utilities for all NAVAREA scrapers

Provides shared functionality including:
- UTF-8 terminal configuration
- SHA256 checksum calculation
- Logging utilities
- File I/O helpers
"""

import sys
import hashlib
import logging
from typing import Optional, Any

# Configure logging
logger = logging.getLogger(__name__)

def configure_utf8_terminal():
    """Configure stdout and stderr for UTF-8 output on Windows terminals."""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

def calculate_sha256(text: str) -> str:
    """
    Calculate SHA256 checksum for a text string.

    Args:
        text: The text to hash

    Returns:
        Hexadecimal SHA256 hash string
    """
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def clean_text(text: str) -> str:
    """
    Normalize text by unescaping HTML entities and normalizing whitespace.

    Args:
        text: The text to clean

    Returns:
        Cleaned text with normalized whitespace
    """
    if not text:
        return ""

    import html
    text = html.unescape(text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\xa0', ' ')
    text = text.replace('\u2028', '\n')
    text = text.replace('\u2029', '\n')

    return ' '.join(text.split()).strip()

def setup_logging(level: int = logging.INFO, debug: bool = False) -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        level: Logging level (default: INFO)
        debug: If True, set level to DEBUG

    Returns:
        Configured logger
    """
    if debug:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logger

def read_file_utf8(filepath: str) -> str:
    """
    Read a file with UTF-8 encoding.

    Args:
        filepath: Path to the file

    Returns:
        File contents as string
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def write_file_utf8(filepath: str, content: str) -> None:
    """
    Write a file with UTF-8 encoding.

    Args:
        filepath: Path to the file
        content: Content to write
    """
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def safe_get(dictionary: dict, key: str, default: Any = None) -> Any:
    """
    Safely get a value from a dictionary.
    """
    return dictionary.get(key, default)

def filter_dict_keys(dictionary: dict, valid_keys: set) -> dict:
    """
    Filter a dictionary to only include specified keys.
    """
    return {k: v for k, v in dictionary.items() if k in valid_keys}
