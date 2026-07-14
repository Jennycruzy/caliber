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
from rwoo.readers.errors import ExecutableQuoteUnavailable

SUPPORTED_VENUES = ("kalshi", "polymarket", "limitless")

_FETCHERS = {
    "kalshi": kalshi.fetch_canonical_market,
    "polymarket": polymarket.fetch_canonical_market,
    "limitless": limitless.fetch_canonical_market,
}


def _not_found(venue: str, market_id: str) -> OracleError:
    details: dict = {
        "venue": venue,
        "requested_market_id": market_id,
    }
    if venue == "polymarket":
        details["accepted_identifier_types"] = [
            "numeric Gamma market id",
            "0x-prefixed condition id",
            "market slug",
            "single-market event slug",
        ]
        suggest = polymarket.suggest_market_refs
    elif venue == "limitless":
        details["accepted_identifier_types"] = [
            "market slug",
            "market address",
            "numeric Limitless market id",
        ]
        suggest = limitless.suggest_market_refs
    else:
        details["accepted_identifier_types"] = ["exact Kalshi market ticker"]
        details["action"] = "copy the exact ticker from an active Kalshi market"
        suggest = None

    if suggest is not None:
        try:
            candidates = suggest(market_id)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            # Suggestions are diagnostic only.  A failed fuzzy-search request
            # must not turn a confirmed exact-lookup miss into a 503.
            candidates = []
        if candidates:
            details["candidates"] = candidates
            details["action"] = "resubmit with one candidate market_id"
        elif venue == "polymarket":
            details["action"] = "check the Polymarket URL slug or use a numeric/condition market id"
        else:
            details["action"] = "check the Limitless market slug or query an active market first"
    return OracleError(
        "MARKET_NOT_FOUND",
        f"{venue} has no market matching {market_id!r}",
        details=details,
    )


def _upstream_details(venue: str, *, status: int | None = None, reason: str) -> dict:
    details = {
        "venue": venue,
        "upstream": "gamma-api.polymarket.com" if venue == "polymarket" else f"{venue} public API",
        "reason": reason,
        "retryable": True,
        "action": "retry later with the same market_id",
    }
    if status is not None:
        details["upstream_status"] = status
    return details


def fetch_canonical(venue: str, market_id: str) -> CanonicalMarket:
    venue = (venue or "").strip().lower()
    if venue not in _FETCHERS:
        raise OracleError(
            "UNSUPPORTED_VENUE",
            f"venue {venue!r} is not supported; supported venues are {', '.join(SUPPORTED_VENUES)}",
        )
    try:
        market = _FETCHERS[venue](market_id)
    except ExecutableQuoteUnavailable as exc:
        raise OracleError(
            "SOURCE_STALE",
            f"{venue} market {market_id!r} has no executable two-sided quote",
            details={
                "venue": venue,
                "requested_market_id": market_id,
                "reason": "no_executable_quote",
                "retryable": True,
                "action": "retry after liquidity appears or choose an active candidate with bid and ask quotes",
            },
        ) from exc
    except httpx.TimeoutException as exc:
        raise OracleError(
            "UPSTREAM_TIMEOUT",
            f"{venue} did not respond in time",
            details=_upstream_details(venue, reason="timeout"),
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise _not_found(venue, market_id) from exc
        if status == 429:
            raise OracleError(
                "RATE_LIMITED",
                f"{venue} rate-limited the lookup; retry shortly",
                details=_upstream_details(venue, status=status, reason="rate_limited"),
            ) from exc
        raise OracleError(
            "SOURCE_UNAVAILABLE",
            f"{venue} upstream returned HTTP {status} while reading the market",
            details=_upstream_details(venue, status=status, reason="upstream_http_error"),
        ) from exc
    except httpx.HTTPError as exc:
        raise OracleError(
            "SOURCE_UNAVAILABLE",
            f"{venue} could not be reached",
            details=_upstream_details(venue, reason="network_error"),
        ) from exc
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        # JSON decoding and venue-schema failures are upstream read failures,
        # not buyer mistakes and not confirmed 404s. Keep implementation
        # details private while giving clients a stable, retryable reason.
        raise OracleError(
            "SOURCE_UNAVAILABLE",
            f"{venue} returned an invalid market payload",
            details=_upstream_details(venue, reason="invalid_upstream_payload"),
        ) from exc
    if market is None:
        raise _not_found(venue, market_id)
    return market


async def discover_live_candidates(
    *,
    venue: str | None = None,
    query: str | None = None,
    limit: int = 10,
) -> tuple[list[dict], list[dict]]:
    """Read small current venue batches when the scan artifact is stale.

    Only markets with a positive, valid two-sided spread are returned. Venue
    failures are reported separately so one unavailable source does not hide
    usable candidates from the others.
    """
    limit = max(1, min(int(limit), 20))
    terms = [term for term in (query or "").lower().replace("-", " ").split() if term]
    selected = [venue] if venue else list(SUPPORTED_VENUES)
    candidates: list[dict] = []
    errors: list[dict] = []

    async with httpx.AsyncClient(timeout=20) as client:
        async def load(current: str) -> tuple[str, list[CanonicalMarket] | None, dict | None]:
            try:
                if current == "kalshi":
                    response = await client.get(
                        f"{kalshi.BASE_URL}/markets",
                        params={"limit": max(100, limit * 10), "status": "open"},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    rows = payload.get("markets") or []
                    convert = ((row, None) for row in rows if isinstance(row, dict))
                elif current == "polymarket":
                    response = await client.get(
                        f"{polymarket.GAMMA_BASE_URL}/markets",
                        params={"limit": max(50, limit * 5), "closed": "false", "offset": 0},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    convert = ((row, None) for row in payload if isinstance(row, dict)) \
                        if isinstance(payload, list) else iter(())
                else:
                    response = await client.get(
                        f"{limitless.BASE_URL}/markets/active",
                        params={"page": 1, "limit": 25},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    parents = payload.get("data") or [] if isinstance(payload, dict) else []
                    convert = (
                        pair for parent in parents if isinstance(parent, dict)
                        for pair in limitless._iter_market_rows(parent)
                    )

                markets: list[CanonicalMarket] = []
                for row, parent in convert:
                    try:
                        if current == "kalshi":
                            markets.append(kalshi.market_row_to_canonical(row))
                        elif current == "polymarket":
                            markets.append(polymarket.to_canonical(row))
                        else:
                            markets.append(limitless.to_canonical(row, parent))
                    except (ExecutableQuoteUnavailable, ValueError, KeyError, TypeError, AttributeError):
                        continue
                return current, markets, None
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                return current, None, {
                    "venue": current,
                    "reason": "live_discovery_failed",
                    "error_type": type(exc).__name__,
                }

        import asyncio
        loaded = await asyncio.gather(*(load(current) for current in selected))

    for current, markets, error in loaded:
        if error is not None:
            errors.append(error)
            continue
        assert markets is not None
        for market in markets:
            status = str(market.market_status or "").lower()
            haystack = f"{market.market_id} {market.question} {market.domain}".lower()
            if status and status not in {"active", "open", "funded"}:
                continue
            if market.spread <= 0 or not (0 <= market.implied_prob <= 1):
                continue
            if terms and not all(term in haystack for term in terms):
                continue
            candidates.append({
                "venue": market.venue,
                "market_id": market.market_id,
                "question": market.question,
                "family": None,
                "market_status": market.market_status,
                "trading_close_time": market.trading_close_time,
            })
            if len(candidates) >= limit:
                return candidates, errors
    return candidates, errors
