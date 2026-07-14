"""Polymarket market reader — Stage 1.

Gamma API field shapes verified live against the real API; see
docs/VERIFICATION_LEDGER.md §3, including the corrected finding that Gamma's
own `bestBid`/`bestAsk`/`spread` fields are authoritative for the midpoint —
no separate CLOB call is required for the canonical object.
"""
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from urllib.parse import quote

import httpx

from rwoo.domain import classify_polymarket
from rwoo.models import CanonicalMarket
from rwoo.readers.errors import ExecutableQuoteUnavailable

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


def _get_json_or_none(
    client: httpx.Client,
    path: str,
    *,
    params: dict | None = None,
    miss_statuses: tuple[int, ...] = (404,),
) -> dict | list | None:
    """Read a Gamma resource, treating only an explicit 404 as a miss.

    Other statuses deliberately propagate to the API error mapper.  In
    particular, a Gamma 5xx must never be mislabeled as "market not found".
    """
    resp = client.get(f"{GAMMA_BASE_URL}{path}", params=params)
    if resp.status_code in miss_statuses:
        return None
    resp.raise_for_status()
    return resp.json()


def _event_markets(event: dict | None) -> list[dict]:
    if not isinstance(event, dict):
        return []
    return [row for row in (event.get("markets") or []) if isinstance(row, dict)]


def _candidate(row: dict, event: dict | None = None) -> dict | None:
    market_id = row.get("conditionId") or row.get("id")
    if not market_id:
        return None
    closed = bool(row.get("closed"))
    return {
        "market_id": str(market_id),
        "gamma_id": str(row.get("id")) if row.get("id") is not None else None,
        "slug": row.get("slug"),
        "question": row.get("question") or (event or {}).get("title"),
        "event_slug": (event or {}).get("slug"),
        "status": "closed" if closed else ("active" if row.get("active", True) else "inactive"),
    }


_MONTH_ALIASES = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "sept": "september", "oct": "october", "nov": "november", "dec": "december",
}


def _search_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    return [_MONTH_ALIASES.get(token, token) for token in tokens]


def _candidate_match_score(query: str, row: dict, event: dict) -> tuple[float, float, float]:
    target = _search_tokens(query)
    candidate = _search_tokens(" ".join(str(value or "") for value in (
        row.get("slug"), row.get("question"), event.get("slug"), event.get("title"),
    )))
    target_set = set(target)
    candidate_set = set(candidate)
    overlap = len(target_set & candidate_set) / max(len(target_set), 1)
    similarity = SequenceMatcher(None, " ".join(target), " ".join(candidate)).ratio()

    target_years = {token for token in target_set if len(token) == 4 and token.isdigit()}
    candidate_years = {token for token in candidate_set if len(token) == 4 and token.isdigit()}
    year_score = 1.0 if target_years & candidate_years else (0.0 if target_years else 0.5)
    return year_score, overlap, similarity


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


def to_canonical(market: dict, *, require_executable_quotes: bool = False) -> CanonicalMarket:
    best_bid = market.get("bestBid")
    best_ask = market.get("bestAsk")
    if best_bid is None or best_ask is None:
        if require_executable_quotes:
            raise ExecutableQuoteUnavailable(
                "polymarket",
                str(market.get("conditionId") or market.get("id") or market.get("slug") or ""),
                "Gamma response did not include both bestBid and bestAsk",
            )
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
        if not (0 <= best_bid <= best_ask <= 1):
            raise ExecutableQuoteUnavailable(
                "polymarket",
                str(market.get("conditionId") or market.get("id") or market.get("slug") or ""),
                "Gamma returned an invalid or crossed bestBid/bestAsk pair",
            )
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

    # implied_prob prices outcomes[0]. For a subject-vs-subject event that is a
    # generic "Yes", so the real subject is the market's groupItemTitle; fall
    # back to a non-Yes/No first outcome label.
    import json as _json
    outcomes_raw = market.get("outcomes")
    outcomes = _json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
    first_outcome = outcomes[0] if outcomes else None
    yes_subtitle = market.get("groupItemTitle") or (
        first_outcome if first_outcome and str(first_outcome).strip().lower() not in ("yes", "no") else None
    )

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
        yes_subtitle=yes_subtitle,
        trading_close_time=market.get("endDate"),
        market_status="closed" if market.get("closed") else ("active" if market.get("active", True) else "inactive"),
        raw=market,
    )


def fetch_canonical_markets(limit: int = 5, closed: bool = False, offset: int = 0) -> list[CanonicalMarket]:
    out: list[CanonicalMarket] = []
    for market in fetch_markets(limit=limit, closed=closed, offset=offset):
        try:
            out.append(to_canonical(market))
        except ExecutableQuoteUnavailable:
            continue
    return out


def fetch_canonical_market(market_id: str, client: httpx.Client | None = None) -> CanonicalMarket | None:
    """Single canonical market by Gamma id, condition id, or exact slug.

    Gamma's `/markets/{id}` path takes the numeric id; a caller holding a
    0x-prefixed condition id is matched through the `condition_ids` filter.
    Slugs use Gamma's dedicated market-slug path.  A Polymarket frontend URL
    usually contains an event slug, so a single-market event slug is also
    accepted.  Multi-market events return None rather than silently choosing
    the wrong child; the API layer can then return the child market IDs as
    candidates.

    Returns None for a confirmed miss.  Upstream outages still raise.
    """
    market_id = (market_id or "").strip()
    own_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        if market_id.startswith("0x"):
            rows = _get_json_or_none(client, "/markets", params={"condition_ids": market_id})
            row = rows[0] if isinstance(rows, list) and rows else None
        elif market_id.isdigit():
            # Gamma returns 404 for ordinary missing numeric IDs but 422 when
            # the all-digit value exceeds its accepted integer range. Both are
            # lookup misses caused by the identifier, not upstream outages.
            row = _get_json_or_none(
                client,
                f"/markets/{market_id}",
                miss_statuses=(404, 422),
            )
        else:
            encoded = quote(market_id, safe="")
            row = _get_json_or_none(client, f"/markets/slug/{encoded}")
            if row is None:
                event = _get_json_or_none(client, f"/events/slug/{encoded}")
                event_rows = _event_markets(event if isinstance(event, dict) else None)
                row = event_rows[0] if len(event_rows) == 1 else None
        if isinstance(row, list):
            row = row[0] if row else None
        if not isinstance(row, dict):
            return None
        return to_canonical(row, require_executable_quotes=True) if row else None
    finally:
        if own_client:
            client.close()


def suggest_market_refs(
    market_id: str,
    *,
    limit: int = 5,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Return safe, compact candidate identifiers for an unresolved slug.

    Exact event children come first.  Otherwise Gamma's public search is used
    as a best-effort fuzzy lookup.  This function never selects a candidate;
    callers must resubmit one of the returned ``market_id`` values.
    """
    market_id = (market_id or "").strip()
    if not market_id or market_id.startswith("0x") or market_id.isdigit():
        return []
    limit = max(1, min(int(limit), 10))
    encoded = quote(market_id, safe="")
    own_client = client is None
    client = client or httpx.Client(timeout=10)
    try:
        event = _get_json_or_none(client, f"/events/slug/{encoded}")
        events: list[dict]
        if isinstance(event, dict) and _event_markets(event):
            events = [event]
        else:
            # Slug punctuation is useful for exact paths but spaces produce a
            # better public-search query.
            query = re.sub(r"[^a-zA-Z0-9]+", " ", market_id).strip() or market_id
            resp = client.get(
                f"{GAMMA_BASE_URL}/public-search",
                params={
                    "q": query,
                    "limit_per_type": limit,
                    "keep_closed_markets": 1,
                    "search_profiles": "false",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            events = [row for row in (payload.get("events") or []) if isinstance(row, dict)] \
                if isinstance(payload, dict) else []

        ranked_rows: list[tuple[dict, dict]] = []
        for candidate_event in events:
            ranked_rows.extend((row, candidate_event) for row in _event_markets(candidate_event))
        if not (isinstance(event, dict) and _event_markets(event)):
            # Public search is event-oriented and may return many child
            # markets. Rank those children against the original identifier so
            # a September-like slug does not return January merely because it
            # appeared first in the event payload.
            ranked_rows.sort(
                key=lambda pair: _candidate_match_score(market_id, pair[0], pair[1]),
                reverse=True,
            )

        out: list[dict] = []
        seen: set[str] = set()
        for row, candidate_event in ranked_rows:
            item = _candidate(row, candidate_event)
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


def fetch_canonical_active_markets(max_markets: int = 500, page_size: int = 100) -> list[CanonicalMarket]:
    out: list[CanonicalMarket] = []
    offset = 0
    with httpx.Client(timeout=20) as client:
        while len(out) < max_markets:
            batch_size = min(page_size, max_markets - len(out))
            batch = fetch_markets(limit=batch_size, closed=False, offset=offset, client=client)
            if not batch:
                break
            for market in batch:
                try:
                    out.append(to_canonical(market))
                except ExecutableQuoteUnavailable:
                    continue
            offset += len(batch)
            if len(batch) < batch_size:
                break
    return out
