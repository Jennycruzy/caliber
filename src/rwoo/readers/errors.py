"""Typed reader failures that the API maps without leaking upstream data."""
from __future__ import annotations


class ExecutableQuoteUnavailable(ValueError):
    """The market exists but lacks a trustworthy executable bid/ask pair."""

    def __init__(self, venue: str, market_id: str, reason: str) -> None:
        super().__init__(reason)
        self.venue = venue
        self.market_id = market_id
        self.reason = reason
