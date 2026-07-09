"""Polymarket market reader — Stage 1.

Gamma API field shapes verified live against the real API; see
docs/VERIFICATION_LEDGER.md §3, including the corrected finding that Gamma's
own `bestBid`/`bestAsk`/`spread` fields are authoritative for the midpoint —
no separate CLOB call is required for the canonical object.
"""
from datetime import datetime, timezone

import httpx

from rwoo.domain import classify_polymarket
from rwoo.models import CanonicalMarket

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_markets(
    limit: int = 5,
    closed: bool = False,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> list[dict]:
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(
            f"{GAMMA_BASE_URL}/markets",
            params={"limit": limit, "closed": str(closed).lower(), "offset": offset},
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def to_canonical(market: dict) -> CanonicalMarket:
    best_bid = market.get("bestBid")
    best_ask = market.get("bestAsk")
    if best_bid is None or best_ask is None:
        # Some markets (e.g. very new or very thin) may not have quoted a
        # book yet. Fall back to outcomePrices (Yes price) as a last resort,
        # with spread reported as unknown (0.0) rather than fabricated.
        import json as _json
        outcome_prices = market.get("outcomePrices")
        prices = _json.loads(outcome_prices) if isinstance(outcome_prices, str) else (outcome_prices or [])
        implied_prob = float(prices[0]) if prices else 0.5
        spread = 0.0
    else:
        best_bid = float(best_bid)
        best_ask = float(best_ask)
        implied_prob = (best_bid + best_ask) / 2
        spread = market.get("spread")
        spread = float(spread) if spread is not None else (best_ask - best_bid)

    event_tags: list[str] = []
    for ev in market.get("events") or []:
        for t in ev.get("tags") or []:
            label = t.get("label")
            if label:
                event_tags.append(label)

    domain = classify_polymarket(event_tags, market.get("question", ""))

    return CanonicalMarket(
        venue="polymarket",
        market_id=market.get("conditionId", market.get("id", "")),
        question=market.get("question", ""),
        domain=domain,
        resolution_rule=market.get("description", ""),
        resolution_source=market.get("resolutionSource") or "see resolution rule text",
        resolution_time=market.get("endDate"),
        implied_prob=implied_prob,
        spread=spread,
        fetched_at=_now_iso(),
        raw=market,
    )


def fetch_canonical_markets(limit: int = 5, closed: bool = False, offset: int = 0) -> list[CanonicalMarket]:
    return [to_canonical(m) for m in fetch_markets(limit=limit, closed=closed, offset=offset)]


def fetch_canonical_active_markets(max_markets: int = 500, page_size: int = 100) -> list[CanonicalMarket]:
    out: list[CanonicalMarket] = []
    offset = 0
    with httpx.Client(timeout=20) as client:
        while len(out) < max_markets:
            batch_size = min(page_size, max_markets - len(out))
            batch = fetch_markets(limit=batch_size, closed=False, offset=offset, client=client)
            if not batch:
                break
            out.extend(to_canonical(m) for m in batch)
            offset += len(batch)
            if len(batch) < batch_size:
                break
    return out
