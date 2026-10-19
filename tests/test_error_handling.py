#!/usr/bin/env python3
"""
tests/test_error_handling.py — Unit Tests for Error Handling & Retry Decorator
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.exceptions import (
    NavWarnError,
    ValidationError,
    ParseError,
    SyncError,
    ConfigurationError,
)
from shared.retry import retry


class TestErrorHandlingFramework(unittest.TestCase):

    def test_navwarn_error_context(self):
        err = ParseError("Coordinate parsing failed", context={"token": "58-10.2X", "rule": "Rule18"})
        self.assertEqual(err.message, "Coordinate parsing failed")
        self.assertEqual(err.context["token"], "58-10.2X")
        self.assertIn("58-10.2X", str(err))

    def test_exception_inheritance(self):
        err = ValidationError("Bad input", context={"field": "warning_id"})
        self.assertIsInstance(err, NavWarnError)
        self.assertEqual(err.to_dict()["error_type"], "ValidationError")

    def test_retry_decorator_eventual_success(self):
        attempts = 0

        @retry(max_attempts=3, delay=0.01, backoff=1.5, jitter=False)
        def flaky_operation():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("Transient network failure")
            return "SUCCESS"

        result = flaky_operation()
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(attempts, 3)

    def test_retry_decorator_exhaustion(self):
        attempts = 0

        @retry(max_attempts=2, delay=0.01, backoff=1.0, jitter=False)
        def permanently_broken():
            nonlocal attempts
            attempts += 1
            raise ValueError("Unrecoverable error")

        with self.assertRaises(ValueError):
            permanently_broken()
        self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main()
