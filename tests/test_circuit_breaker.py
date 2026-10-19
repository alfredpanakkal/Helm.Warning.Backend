#!/usr/bin/env python3
"""
tests/test_circuit_breaker.py — Unit Tests for Circuit Breaker Pattern
"""

import unittest
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, circuit_breaker


class TestCircuitBreaker(unittest.TestCase):

    def test_closed_state_normal_operation(self):
        cb = CircuitBreaker(name="test_normal", max_failures=3, reset_timeout=0.1)
        res = cb.call(lambda x, y: x + y, 5, 10)
        self.assertEqual(res, 15)
        self.assertEqual(cb.state, "CLOSED")

    def test_transition_to_open_after_max_failures(self):
        cb = CircuitBreaker(name="test_trip", max_failures=3, reset_timeout=0.2)

        def failing():
            raise RuntimeError("Backend timeout")

        for _ in range(3):
            with self.assertRaises(RuntimeError):
                cb.call(failing)

        self.assertEqual(cb.state, "OPEN")

        # In OPEN state, calls should immediately fail with CircuitBreakerOpenError without invoking the function
        with self.assertRaises(CircuitBreakerOpenError):
            cb.call(lambda: "should not run")

    def test_transition_to_half_open_and_recovery(self):
        cb = CircuitBreaker(name="test_recover", max_failures=2, reset_timeout=0.05, half_open_max_attempts=2)

        def failing():
            raise RuntimeError("API down")

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                cb.call(failing)

        self.assertEqual(cb.state, "OPEN")

        # Wait for reset timeout
        time.sleep(0.06)
        self.assertEqual(cb.state, "HALF_OPEN")

        # Successful calls should close the circuit
        self.assertEqual(cb.call(lambda: "probe_1"), "probe_1")
        self.assertEqual(cb.call(lambda: "probe_2"), "probe_2")
        self.assertEqual(cb.state, "CLOSED")

    def test_circuit_breaker_decorator(self):
        @circuit_breaker(name="test_dec", max_failures=2, reset_timeout=0.1)
        def my_call(val):
            if val < 0:
                raise ValueError("Negative value not allowed")
            return val * 2

        self.assertEqual(my_call(10), 20)
        with self.assertRaises(ValueError):
            my_call(-1)
        with self.assertRaises(ValueError):
            my_call(-2)

        # Now open
        with self.assertRaises(CircuitBreakerOpenError):
            my_call(10)


if __name__ == "__main__":
    unittest.main()
