#!/usr/bin/env python3
"""
shared/metrics.py — Instrumentation & Metrics Framework
Collects operational counters, gauges, and latency histograms for Prometheus export and monitoring.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Counter:
    name: str
    description: str = ""
    value: int = 0
    labels: Dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def increment(self, by: int = 1) -> None:
        with self.lock:
            self.value += by

    def get(self) -> int:
        with self.lock:
            return self.value


@dataclass
class Gauge:
    name: str
    description: str = ""
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, val: float) -> None:
        with self.lock:
            self.value = float(val)

    def increment(self, by: float = 1.0) -> None:
        with self.lock:
            self.value += by

    def decrement(self, by: float = 1.0) -> None:
        with self.lock:
            self.value -= by

    def get(self) -> float:
        with self.lock:
            return self.value


@dataclass
class Histogram:
    name: str
    description: str = ""
    buckets: List[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    counts: Dict[float, int] = field(default_factory=dict)
    count_total: int = 0
    sum_total: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        with self.lock:
            for b in self.buckets:
                self.counts[b] = 0
            self.counts[float("inf")] = 0

    def observe(self, value: float) -> None:
        with self.lock:
            val = float(value)
            self.count_total += 1
            self.sum_total += val
            for b in sorted(self.buckets):
                if val <= b:
                    self.counts[b] = self.counts.get(b, 0) + 1
            self.counts[float("inf")] = self.counts.get(float("inf"), 0) + 1

    def get_summary(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "count": self.count_total,
                "sum": round(self.sum_total, 4),
                "buckets": dict(self.counts),
            }


class Metrics:
    """Thread-safe metric registry."""
    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def _make_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        if not labels:
            return name
        sorted_labels = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{sorted_labels}}}"

    def counter(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Counter:
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = Counter(name=name, description=description, labels=labels or {})
            return self._counters[key]

    def gauge(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Gauge:
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._gauges:
                self._gauges[key] = Gauge(name=name, description=description, labels=labels or {})
            return self._gauges[key]

    def histogram(
        self,
        name: str,
        description: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: Optional[List[float]] = None
    ) -> Histogram:
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                h = Histogram(name=name, description=description, labels=labels or {})
                if buckets:
                    h.buckets = sorted(buckets)
                self._histograms[key] = h
            return self._histograms[key]

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "counters": {k: c.get() for k, c in self._counters.items()},
                "gauges": {k: g.get() for k, g in self._gauges.items()},
                "histograms": {k: h.get_summary() for k, h in self._histograms.items()},
            }

    def to_prometheus(self) -> str:
        """Serializes registry metrics to Prometheus exposition text format."""
        lines = []
        with self._lock:
            for key, c in self._counters.items():
                if c.description:
                    lines.append(f"# HELP {c.name} {c.description}")
                lines.append(f"# TYPE {c.name} counter")
                lines.append(f"{key} {c.get()}")

            for key, g in self._gauges.items():
                if g.description:
                    lines.append(f"# HELP {g.name} {g.description}")
                lines.append(f"# TYPE {g.name} gauge")
                lines.append(f"{key} {g.get()}")

            for key, h in self._histograms.items():
                if h.description:
                    lines.append(f"# HELP {h.name} {h.description}")
                lines.append(f"# TYPE {h.name} histogram")
                summary = h.get_summary()
                # Bucket lines
                base_labels = dict(h.labels)
                for b, count in summary["buckets"].items():
                    b_str = "+Inf" if b == float("inf") else str(b)
                    lbls = dict(base_labels)
                    lbls["le"] = b_str
                    lbl_str = ",".join(f'{k}="{v}"' for k, v in sorted(lbls.items()))
                    lines.append(f"{h.name}_bucket{{{lbl_str}}} {count}")
                lines.append(f"{h.name}_sum {summary['sum']}")
                lines.append(f"{h.name}_count {summary['count']}")

        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Resets all metrics (for testing)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Global Singleton Metrics Registry
metrics = Metrics()
