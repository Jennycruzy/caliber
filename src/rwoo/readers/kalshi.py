"""Kalshi market reader — Stage 1.

Base URL, auth (none needed for public market reads), and field shapes are
all verified live against the real API; see docs/VERIFICATION_LEDGER.md §2.
"""
from datetime import datetime, timezone

import httpx

from rwoo.domain import classify_kalshi
from rwoo.models import CanonicalMarket

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_event(event_ticker: str, client: httpx.Client | None = None) -> dict:
    """Fetch a Kalshi event, which embeds its markets and its
    settlement_sources — the event level is where category and the named
    official settlement source live (verified live, Ledger §2)."""
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(f"{BASE_URL}/events/{event_ticker}")
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def to_canonical(event: dict, market: dict) -> CanonicalMarket:
    ev = event["event"]
    settlement_sources = ev.get("settlement_sources") or []
    resolution_source = ", ".join(
        f"{s.get('name')} ({s.get('url')})" for s in settlement_sources
    ) or "not specified in event metadata"

    yes_bid = float(market.get("yes_bid_dollars", 0) or 0)
    yes_ask = float(market.get("yes_ask_dollars", 0) or 0)
    implied_prob = (yes_bid + yes_ask) / 2
    spread = yes_ask - yes_bid

    domain = classify_kalshi(ev.get("category"), market.get("title", ""))

    return CanonicalMarket(
        venue="kalshi",
        market_id=market["ticker"],
        question=market.get("title") or ev.get("title", ""),
        domain=domain,
        resolution_rule=market.get("rules_primary", ""),
        resolution_source=resolution_source,
        resolution_time=market.get("expiration_time") or ev.get("strike_date"),
        implied_prob=implied_prob,
        spread=spread,
        fetched_at=_now_iso(),
        raw={"event": ev, "market": market},
    )


def fetch_markets_for_event(event_ticker: str, client: httpx.Client | None = None) -> list[CanonicalMarket]:
    data = fetch_event(event_ticker, client=client)
    event = {"event": data["event"]}
    return [to_canonical(event, m) for m in data.get("markets", [])]
