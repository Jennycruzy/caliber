"""Weather calibration backtest with no-lookahead proof.

Inputs are real finalized Kalshi weather markets and archived Open-Meteo
Single Runs forecasts. The decision timestamp is each market's `open_time`.
The forecast run is the previous day's 06:00 UTC model cycle; Open-Meteo's
docs state global model outputs are typically available 4-6 hours after
initialisation, so this code records `run + 6h` and requires it to be before
the market open. If that proof fails, the record is refused.
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone

import httpx

from rwoo.calibration import CalibrationRecord, probability_bucket
from rwoo.engines.weather import MIN_STD_F, _probability_from_ensemble
from rwoo.readers import kalshi
from rwoo.weather_stations import station_for_series

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
ARCHIVED_MODELS = ["ecmwf_ifs025", "gfs_global", "icon_global"]
_SINGLE_RUN_CACHE: dict[tuple[float, float, str, str, str], float | None] = {}


def _get_with_retry(url: str, params: dict, timeout: float = 45, attempts: int = 3) -> httpx.Response:
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


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _target_date_from_event(event_ticker: str) -> str:
    return kalshi.parse_event_date(event_ticker)


def _previous_day_06z(target_date: str) -> str:
    target = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
    run = target - timedelta(days=1)
    return run.replace(hour=6, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def _run_available_at(run: str) -> str:
    run_dt = datetime.fromisoformat(run).replace(tzinfo=timezone.utc)
    return (run_dt + timedelta(hours=6)).isoformat()


def fetch_finalized_weather_markets(series_ticker: str = "KXHIGHNY", limit: int = 24) -> list[dict]:
    resp = _get_with_retry(
        f"{kalshi.BASE_URL}/markets",
        params={"series_ticker": series_ticker, "status": "settled", "limit": limit},
    )
    markets = resp.json().get("markets", [])
    return [m for m in markets if m.get("status") == "finalized" and m.get("result") in {"yes", "no"}]


def fetch_single_run_daily_max(
    lat: float,
    lon: float,
    target_date: str,
    run: str,
    model: str,
    timezone_name: str = "America/New_York",
) -> float | None:
    cache_key = (round(lat, 4), round(lon, 4), target_date, run, model)
    if cache_key in _SINGLE_RUN_CACHE:
        return _SINGLE_RUN_CACHE[cache_key]
    resp = _get_with_retry(
        SINGLE_RUNS_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": timezone_name,
            "models": model,
            "run": run,
            "forecast_days": 4,
        },
    )
    data = resp.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    values = [temp for ts, temp in zip(times, temps) if ts.startswith(target_date) and temp is not None]
    if not values:
        _SINGLE_RUN_CACHE[cache_key] = None
        return None
    value = max(values)
    _SINGLE_RUN_CACHE[cache_key] = value
    return value


def compute_archived_probability(market: dict, series_ticker: str = "KXHIGHNY") -> dict:
    target_date = _target_date_from_event(market["event_ticker"])
    run = _previous_day_06z(target_date)
    available_at = _run_available_at(run)
    decision_timestamp = market["open_time"]
    if _parse_dt(available_at) > _parse_dt(decision_timestamp):
        return {
            "refused": True,
            "reason": f"forecast run availability {available_at} is after market open {decision_timestamp}",
        }

    station = station_for_series(series_ticker)
    forecasts = {}
    for model in ARCHIVED_MODELS:
        value = fetch_single_run_daily_max(station.lat, station.lon, target_date, run, model)
        if value is not None:
            forecasts[model] = value
    if len(forecasts) < 2:
        return {
            "refused": True,
            "reason": f"only {len(forecasts)} archived model forecasts returned",
            "per_source_values": forecasts,
        }

    values = list(forecasts.values())
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    prob = min(
        1.0,
        max(
            0.0,
            _probability_from_ensemble(
                mean,
                std,
                market["strike_type"],
                market.get("floor_strike"),
                market.get("cap_strike"),
            ),
        ),
    )
    per_model_prob = {
        model: min(
            1.0,
            max(
                0.0,
                _probability_from_ensemble(
                    value,
                    MIN_STD_F,
                    market["strike_type"],
                    market.get("floor_strike"),
                    market.get("cap_strike"),
                ),
            ),
        )
        for model, value in forecasts.items()
    }
    return {
        "refused": False,
        "oracle_prob": prob,
        "prob_low": min(per_model_prob.values()),
        "prob_high": max(per_model_prob.values()),
        "per_model_prob": per_model_prob,
        "per_source_values": forecasts,
        "ensemble_mean_f": mean,
        "ensemble_std_f": std,
        "source_run": run,
        "source_available_at": available_at,
        "decision_timestamp": decision_timestamp,
        "target_date": target_date,
        "method": "Open-Meteo Single Runs previous-day 06Z archived ensemble -> same Stage-2 normal-CDF transform",
    }


def build_weather_backtest(max_records: int = 18, series_ticker: str = "KXHIGHNY") -> tuple[list[CalibrationRecord], list[dict]]:
    records: list[CalibrationRecord] = []
    raw_rows = []
    markets = fetch_finalized_weather_markets(series_ticker=series_ticker, limit=40)
    # Prefer a spread of outcomes and strike types by taking recent finalized
    # markets in API order until the requested sample is filled.
    for market in markets:
        if len(records) >= max_records:
            break
        result = compute_archived_probability(market, series_ticker=series_ticker)
        raw_rows.append({"market": market, "engine_result": result})
        if result.get("refused"):
            continue
        outcome = 1 if market["result"] == "yes" else 0
        record = CalibrationRecord(
            domain="weather",
            venue="kalshi",
            market_id=market["ticker"],
            question=market["title"],
            decision_timestamp=result["decision_timestamp"],
            resolution_timestamp=market.get("settlement_ts") or market.get("expiration_time"),
            oracle_prob=result["oracle_prob"],
            outcome=outcome,
            bucket=probability_bucket(result["oracle_prob"]),
            source_run=result["source_run"],
            source_available_at=result["source_available_at"],
            target_date=result["target_date"],
        )
        records.append(record)
    return records, raw_rows
