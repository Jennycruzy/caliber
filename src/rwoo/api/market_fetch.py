"""Single-market fetch by (venue, market_id), normalized to stable errors.

This is the only place the API pulls a live market for a paid/priced call. It
never fetches an arbitrary user-supplied URL or parses free text: the caller
names a supported venue and that venue's native id, and the matching read-only
reader returns a validated CanonicalMarket. Every upstream failure becomes a
stable OracleError (MARKET_NOT_FOUND / UNSUPPORTED_VENUE / SOURCE_UNAVAILABLE /
UPSTREAM_TIMEOUT) — never a leaked stack trace or upstream body.
"""
from __future__ import annotations

import httpx

from rwoo.api.errors import OracleError
from rwoo.models import CanonicalMarket
from rwoo.readers import kalshi, limitless, polymarket

SUPPORTED_VENUES = ("kalshi", "polymarket", "limitless")

_FETCHERS = {
    "kalshi": kalshi.fetch_canonical_market,
    "polymarket": polymarket.fetch_canonical_market,
    "limitless": limitless.fetch_canonical_market,
}


def fetch_canonical(venue: str, market_id: str) -> CanonicalMarket:
    venue = (venue or "").strip().lower()
    if venue not in _FETCHERS:
        raise OracleError(
            "UNSUPPORTED_VENUE",
            f"venue {venue!r} is not supported; supported venues are {', '.join(SUPPORTED_VENUES)}",
        )
    try:
        market = _FETCHERS[venue](market_id)
    except httpx.TimeoutException as exc:
        raise OracleError("UPSTREAM_TIMEOUT", f"{venue} did not respond in time") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise OracleError("MARKET_NOT_FOUND", f"{venue} has no market {market_id!r}") from exc
        if status == 429:
            raise OracleError("RATE_LIMITED", f"{venue} rate-limited the lookup; retry shortly") from exc
        raise OracleError("SOURCE_UNAVAILABLE", f"{venue} returned an error while reading the market") from exc
    except httpx.HTTPError as exc:
        raise OracleError("SOURCE_UNAVAILABLE", f"{venue} could not be reached") from exc
    if market is None:
        raise OracleError("MARKET_NOT_FOUND", f"{venue} has no market {market_id!r}")
    return market
