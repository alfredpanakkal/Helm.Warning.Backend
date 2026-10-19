#!/usr/bin/env python3
"""
shared/prometheus.py — Lightweight HTTP Metrics Server & Prometheus Integration
Exposes /metrics endpoint for Prometheus scraping.
"""

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from shared.metrics import metrics
from shared.logging import get_logger

logger = get_logger("prometheus")


class MetricsHTTPRequestHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler serving /metrics endpoint."""

    def do_GET(self):
        if self.path in ("/metrics", "/metrics/"):
            prom_data = metrics.to_prometheus()
            data_bytes = prom_data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
        elif self.path in ("/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def log_message(self, format, *args):
        # Silence default stderr logging for http server requests
        pass


class PrometheusServer:
    """Manages background HTTP server for Prometheus metrics."""

    def __init__(self, port: int = 8000, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        """Starts Prometheus HTTP server in a daemon thread."""
        if self._running:
            return True
        try:
            self._server = HTTPServer((self.host, self.port), MetricsHTTPRequestHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._running = True
            logger.info(f"Prometheus metrics exporter started on http://{self.host}:{self.port}/metrics")
            return True
        except Exception as e:
            logger.warning(f"Could not bind Prometheus server to port {self.port}: {e}")
            return False

    def stop(self) -> None:
        """Stops the metrics server."""
        if self._server and self._running:
            self._server.shutdown()
            self._server.server_close()
            self._running = False
            logger.info("Prometheus metrics server stopped")
