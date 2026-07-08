"""Economics calibration backtest with a no-lookahead proof.

Real settled Kalshi core-CPI markets, scored against what the economics
engine would have said using ONLY BLS values whose real publication date
(not reference month) was already public as of the market's decision time.
No sample-size cap — every real settled KXCPICORE market is attempted.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

from rwoo.calibration import CalibrationRecord, probability_bucket
from rwoo.engines.economics import compute_core_cpi_probability, release_date_for
from rwoo.readers import kalshi

_MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _get_with_retry(url: str, params: dict, timeout: float = 25, attempts: int = 3) -> httpx.Response:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def fetch_finalized_cpi_markets(series_ticker: str = "KXCPICORE", page_size: int = 200) -> list[dict]:
    """Paginates through ALL settled markets for a series — no cap."""
    all_markets: list[dict] = []
    cursor = None
    while True:
        params = {"series_ticker": series_ticker, "status": "settled", "limit": page_size}
        if cursor:
            params["cursor"] = cursor
        resp = _get_with_retry(f"{kalshi.BASE_URL}/markets", params=params)
        data = resp.json()
        page = data.get("markets", [])
        all_markets.extend(page)
        cursor = data.get("cursor")
        if not cursor or not page:
            break
    return [m for m in all_markets if m.get("status") == "finalized" and m.get("result") in {"yes", "no"}]


def _parse_target_month(event_ticker: str) -> tuple[int, int]:
    """'KXCPICORE-26MAY' -> (2026, 5). Same convention as
    rwoo.readers.kalshi.parse_event_date, adapted for a monthly (no day)
    series."""
    suffix = event_ticker.rsplit("-", 1)[-1]
    year, month_abbr = suffix[:2], suffix[2:5]
    return 2000 + int(year), _MONTH_ABBR[month_abbr.upper()]


def compute_archived_cpi_probability(market: dict) -> dict:
    target_year, target_month = _parse_target_month(market["event_ticker"])
    decision_timestamp = market["open_time"]
    decision_date = datetime.fromisoformat(decision_timestamp.replace("Z", "+00:00")).date()

    # No-lookahead proof: the target month's own release must NOT already be
    # public as of the decision date — if it were, this market would already
    # be resolved, not a genuine forecast.
    target_release = release_date_for(target_year, target_month)
    if target_release is not None and target_release <= decision_date:
        return {
            "refused": True,
            "reason": (
                f"target month {target_year}-{target_month:02d}'s BLS release ({target_release}) "
                f"was already public by decision time ({decision_date}) — not a genuine forecast"
            ),
        }

    result = compute_core_cpi_probability(
        strike_type=market["strike_type"],
        floor_strike=market.get("floor_strike"),
        cap_strike=market.get("cap_strike"),
        target_month=target_month,
        as_of=decision_date,
    )
    if result.get("refused"):
        return result

    result["decision_timestamp"] = decision_timestamp
    result["target_month"] = f"{target_year}-{target_month:02d}"
    result["source_available_at"] = f"all included BLS values released on/before {decision_date.isoformat()}"
    return result


def build_economics_backtest(series_ticker: str = "KXCPICORE") -> tuple[list[CalibrationRecord], list[dict]]:
    records: list[CalibrationRecord] = []
    raw_rows = []
    markets = fetch_finalized_cpi_markets(series_ticker=series_ticker)
    for market in markets:
        try:
            result = compute_archived_cpi_probability(market)
        except Exception as exc:  # noqa: BLE001
            result = {"refused": True, "reason": f"error scoring this market: {exc}"}
        raw_rows.append({"market": market, "engine_result": result})
        if result.get("refused"):
            continue
        outcome = 1 if market["result"] == "yes" else 0
        record = CalibrationRecord(
            domain="economics",
            venue="kalshi",
            market_id=market["ticker"],
            question=market["title"],
            decision_timestamp=result["decision_timestamp"],
            resolution_timestamp=market.get("settlement_ts") or market.get("expiration_time"),
            oracle_prob=result["oracle_prob"],
            outcome=outcome,
            bucket=probability_bucket(result["oracle_prob"]),
            source_run=result["target_month"],
            source_available_at=result["source_available_at"],
            target_date=result["target_month"],
        )
        records.append(record)
    return records, raw_rows
