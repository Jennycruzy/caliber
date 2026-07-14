"""Limitless market reader.

Limitless is integrated as a read-only scanned venue. Public market reads,
group-market nesting, and price fields were verified live against
https://api.limitless.exchange; see docs/VERIFICATION_LEDGER.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from typing import Any
from urllib.parse import quote

import httpx

from rwoo.domain import classify_limitless
from rwoo.models import CanonicalMarket
from rwoo.readers.errors import ExecutableQuoteUnavailable

BASE_URL = "https://api.limitless.exchange"

SCAN_SEARCH_QUERIES = [
    "weather",
    "temperature",
    "rain",
    "inflation",
    "CPI",
    "GDP",
    "recession",
    "World Cup",
    "football",
    "NBA",
    "NHL",
    "Wimbledon",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_ms_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _plain_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split())


def _normal_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price > 1:
        price /= 100
    return price


def _yes_bid_ask(market: dict) -> tuple[float, float, str]:
    trade_prices = market.get("tradePrices") or {}
    buy_market = (trade_prices.get("buy") or {}).get("market") or []
    sell_market = (trade_prices.get("sell") or {}).get("market") or []
    ask = _normal_price(buy_market[0]) if buy_market else None
    bid = _normal_price(sell_market[0]) if sell_market else None
    if bid is not None and ask is not None:
        return bid, ask, "tradePrices.sell.market[0]/buy.market[0]"

    prices = market.get("prices") or []
    midpoint = _normal_price(prices[0]) if prices else None
    if midpoint is not None:
        return midpoint, midpoint, "prices[0] midpoint fallback; no bid/ask spread"
    return 0.5, 0.5, "no usable Limitless price fields; defaulted to 0.5"


def _resolution_source(rule: str) -> str:
    for pattern in (
        r"resolution source:?\s+(.+?)(?:\.|$)",
        r"primary resolution source (?:will be|is) (.+?)(?:\.|$)",
        r"reported by (.+?)(?:\.|$)",
        r"published by (.+?)(?:\.|$)",
    ):
        match = re.search(pattern, rule, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "see resolution rule text"


def fetch_active_markets(
    *,
    page: int = 1,
    limit: int = 25,
    sort_by: str | None = None,
    client: httpx.Client | None = None,
) -> dict:
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    params: dict[str, Any] = {"page": page, "limit": limit}
    if sort_by:
        params["sortBy"] = sort_by
    try:
        resp = client.get(f"{BASE_URL}/markets/active", params=params)
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def search_markets(query: str, *, limit: int = 10, client: httpx.Client | None = None) -> list[dict]:
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(f"{BASE_URL}/markets/search", params={"query": query, "limit": limit})
        resp.raise_for_status()
        data = resp.json()
        return data.get("markets") or data.get("data") or []
    finally:
        if own_client:
            client.close()


def fetch_market(slug: str, client: httpx.Client | None = None) -> dict:
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(f"{BASE_URL}/markets/{quote(str(slug), safe='')}")
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def fetch_orderbook(slug: str, client: httpx.Client | None = None) -> dict:
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(f"{BASE_URL}/markets/{slug}/orderbook")
        resp.raise_for_status()
        return resp.json()
    finally:
        if own_client:
            client.close()


def _iter_market_rows(market_or_group: dict) -> list[tuple[dict, dict | None]]:
    children = market_or_group.get("markets") or []
    if children:
        return [(child, market_or_group) for child in children]
    return [(market_or_group, None)]


def _dedupe_key(market: dict) -> str:
    return str(market.get("conditionId") or market.get("slug") or market.get("id"))


def fetch_scanner_markets(
    *,
    active_limit: int = 100,
    search_queries: list[str] | None = None,
    search_limit: int = 8,
) -> list[dict]:
    search_queries = SCAN_SEARCH_QUERIES if search_queries is None else search_queries
    rows: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(timeout=25) as client:
        page = 1
        remaining = max(0, active_limit)
        while remaining > 0:
            page_limit = min(25, remaining)
            active = fetch_active_markets(page=page, limit=page_limit, client=client)
            batch = active.get("data") or []
            if not batch:
                break
            for parent in batch:
                for row, group in _iter_market_rows(parent):
                    key = _dedupe_key(row)
                    if key not in seen:
                        seen.add(key)
                        rows.append({"market": row, "parent": group})
            remaining -= len(batch)
            page += 1
        for query in search_queries:
            for parent in search_markets(query, limit=search_limit, client=client):
                for row, group in _iter_market_rows(parent):
                    key = _dedupe_key(row)
                    if key not in seen:
                        seen.add(key)
                        rows.append({"market": row, "parent": group})
    return rows


def _question(market: dict, parent: dict | None) -> tuple[str, str | None]:
    parent_title = (parent or {}).get("title") or ""
    title = market.get("title") or parent_title
    tags = {str(t).lower() for t in (market.get("tags") or []) + ((parent or {}).get("tags") or [])}
    if (parent_title == "World Cup Winner" or "wc_winner" in tags) and not market.get("isOther") and title.lower() != "other":
        return f"Will {title} win the 2026 FIFA World Cup?", "world_cup_winner"
    if parent_title and parent_title != title:
        return f"{parent_title} - {title}", None
    return title, None


def to_canonical(
    market: dict,
    parent: dict | None = None,
    *,
    require_executable_quotes: bool = False,
) -> CanonicalMarket:
    bid, ask, price_method = _yes_bid_ask(market)
    market_id = str(market.get("slug") or market.get("address") or market.get("id") or "")
    if require_executable_quotes and not price_method.startswith("tradePrices."):
        raise ExecutableQuoteUnavailable(
            "limitless", market_id, "Limitless response did not include executable buy and sell quotes",
        )
    if not (0 <= bid <= ask <= 1):
        raise ExecutableQuoteUnavailable(
            "limitless", market_id, "Limitless returned an invalid or crossed bid/ask pair",
        )
    implied_prob = (bid + ask) / 2
    spread = max(0.0, ask - bid)
    rule = _plain_text(market.get("description") or (parent or {}).get("description"))
    question, supported_shape = _question(market, parent)
    categories = list(market.get("categories") or (parent or {}).get("categories") or [])
    tags = list(market.get("tags") or (parent or {}).get("tags") or [])

    raw = {
        "market": market,
        "parent": parent,
        "price_method": price_method,
        "collateralToken": market.get("collateralToken") or (parent or {}).get("collateralToken"),
        "fee_metadata": (market.get("metadata") or {}).get("fee"),
    }
    metadata = market.get("metadata") or {}
    weather = metadata.get("weather") or market.get("weather")
    if isinstance(weather, dict):
        raw["weather"] = weather
    if supported_shape:
        raw["limitless_supported_shape"] = supported_shape

    return CanonicalMarket(
        venue="limitless",
        # Limitless's public single-market endpoint accepts a slug (or market
        # address), not a Polymarket-style condition ID. Exposing conditionId
        # here made scanner-discovered markets impossible to retrieve through
        # /v1/check-market and /v1/cross-venue-edge.
        market_id=market_id,
        question=question,
        domain=classify_limitless(categories, tags, question, rule),
        resolution_rule=rule,
        resolution_source=_resolution_source(rule),
        resolution_time=_timestamp_ms_to_iso(
            market.get("expirationTimestamp") or (parent or {}).get("expirationTimestamp")
        ),
        implied_prob=implied_prob,
        spread=spread,
        fetched_at=_now_iso(),
        # A flattened child's own title is the specific outcome YES prices; a
        # raw "A vs B" title (no per-outcome child) binds to neither player and
        # so is correctly left unbindable downstream.
        yes_subtitle=market.get("title"),
        trading_close_time=_timestamp_ms_to_iso(
            market.get("expirationTimestamp") or (parent or {}).get("expirationTimestamp")
        ),
        market_status=str(market.get("status") or (parent or {}).get("status") or "active").lower(),
        raw=raw,
    )


def fetch_canonical_markets(active_limit: int = 100) -> list[CanonicalMarket]:
    out: list[CanonicalMarket] = []
    for row in fetch_scanner_markets(active_limit=active_limit):
        try:
            out.append(to_canonical(row["market"], row.get("parent")))
        except ExecutableQuoteUnavailable:
            # A single malformed/crossed venue book must not abort the broad
            # scan. Exact paid lookups remain strict and surface SOURCE_STALE.
            continue
    return out


def fetch_canonical_market(slug: str, client: httpx.Client | None = None) -> CanonicalMarket | None:
    """Single canonical market by slug/id. Flattens a group parent to the child
    whose identifier matches `slug` so the returned object prices one outcome,
    not the group. Returns None when nothing matches."""
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        raw = fetch_market(slug, client=client)
        obj = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not isinstance(obj, dict) or not obj:
            return None
        children = obj.get("markets") or []
        if children:
            for child in children:
                if slug in {str(child.get("conditionId")), str(child.get("id")), str(child.get("slug"))}:
                    return to_canonical(child, obj, require_executable_quotes=True)
            return None
        return to_canonical(obj, require_executable_quotes=True)
    finally:
        if own_client:
            client.close()


def _candidate_ref(market: dict, parent: dict | None = None) -> dict | None:
    market_id = market.get("slug") or market.get("address") or market.get("id")
    if market_id in (None, ""):
        return None
    return {
        "market_id": str(market_id),
        "slug": market.get("slug"),
        "question": _question(market, parent)[0],
        "group_slug": (parent or {}).get("slug"),
        "status": str(market.get("status") or (parent or {}).get("status") or "unknown").lower(),
    }


def suggest_market_refs(
    market_id: str,
    *,
    limit: int = 5,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Return exact group children or fuzzy Limitless market candidates."""
    market_id = (market_id or "").strip()
    if not market_id:
        return []
    limit = max(1, min(int(limit), 10))
    own_client = client is None
    client = client or httpx.Client(timeout=10)
    try:
        parents: list[dict] = []
        try:
            raw = fetch_market(market_id, client=client)
            obj = raw.get("data", raw) if isinstance(raw, dict) else None
            if isinstance(obj, dict) and obj.get("markets"):
                parents = [obj]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        if not parents:
            query = re.sub(r"[^a-zA-Z0-9]+", " ", market_id).strip() or market_id
            parents = [row for row in search_markets(query, limit=limit, client=client)
                       if isinstance(row, dict)]

        out: list[dict] = []
        seen: set[str] = set()
        for parent in parents:
            for row, group in _iter_market_rows(parent):
                item = _candidate_ref(row, group)
                if item is None or item["market_id"] in seen:
                    continue
                seen.add(item["market_id"])
                out.append(item)
                if len(out) >= limit:
                    return out
        return out
    finally:
        if own_client:
            client.close()
