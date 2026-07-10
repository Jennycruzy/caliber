"""Real-World Odds Oracle HTTP API (ASP surface).

This package wraps the existing deterministic core (`rwoo.scanner`,
`rwoo.edge`, `rwoo.cross_venue`, `rwoo.evidence`, `rwoo.receipts`) in a
production FastAPI application. It does not create, alter, veto, or
sanity-check any probability — every number still originates in the
deterministic engines. The API only reads a market, routes it to the correct
engine, assembles the documented response, commits a tamper-evident receipt,
and fails closed when a market cannot be safely interpreted.
"""
from __future__ import annotations

API_VERSION = "1.0.0"

__all__ = ["API_VERSION"]
