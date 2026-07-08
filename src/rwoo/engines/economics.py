"""Phase 4 economics engine.

This is intentionally a conservative baseline, not a finished macro desk
model. For Kalshi core-CPI markets it pulls official BLS CPI-U less food and
energy data, computes real month-over-month changes, and estimates the target
event from two deterministic views of that same official history:

1. a long-window empirical distribution of reported monthly changes;
2. a trailing-recent empirical distribution.

Because this does not yet include a verified consensus-forecast distribution,
confidence is capped. The engine may produce a probability for end-to-end
testing, but the restraint layer should usually refuse strong action until a
proper forecast-distribution source is added and calibrated.
"""
from __future__ import annotations

import os
import statistics
import time
from datetime import date, datetime, timezone

import httpx

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
# Optional: a free registration key (data.bls.gov/registrationEngine/) raises
# the daily quota from ~25 to ~500 requests. Registration requires solving a
# CAPTCHA, so it can't be automated — set BLS_API_KEY once you have one; unset
# behaves exactly as before (unauthenticated, lower quota).
BLS_API_KEY_ENV = "BLS_API_KEY"
BLS_CORE_CPI_SA_SERIES = "CUSR0000SA0L1E"
HISTORY_START_YEAR = 2016

# The unauthenticated BLS v2 API allows only ~25 requests/day. A backtest
# scores many sibling markets (same event, different strike thresholds) that
# share the same decision date and therefore the same `as_of` cutoff — without
# caching, each one re-fetches the entire history separately and burns the
# daily quota in a handful of markets. Keyed on the exact query shape.
_CPI_SERIES_CACHE: dict[tuple[int, int], list[dict]] = {}

# Real BLS CPI release dates (release covers the PRIOR month's data), sourced
# 2026-07-08 from usinflationcalculator.com/inflation/consumer-price-index-release-schedule/
# which states it reproduces the official BLS release schedule
# (bls.gov/schedule/news_release/cpi.htm — direct fetch returned HTTP 403 from
# this workspace, so this is a cross-referenced secondary source, disclosed
# rather than treated as unquestionable). Key = (reference_year, reference_month).
# None = release was canceled/unavailable (the October 2025 report was
# canceled due to a government shutdown) — real-world messiness, not smoothed
# over. Used ONLY to backtest without lookahead; the live engine (no `as_of`)
# is unaffected by this table.
CPI_RELEASE_DATES: dict[tuple[int, int], date | None] = {
    (2025, 10): None,
    (2025, 11): date(2025, 12, 18),
    (2025, 12): date(2026, 1, 13),
    (2026, 1): date(2026, 2, 13),
    (2026, 2): date(2026, 3, 11),
    (2026, 3): date(2026, 4, 10),
    (2026, 4): date(2026, 5, 12),
    (2026, 5): date(2026, 6, 10),
    (2026, 6): date(2026, 7, 14),
    (2026, 7): date(2026, 8, 12),
    (2026, 8): date(2026, 9, 11),
    (2026, 9): date(2026, 10, 14),
    (2026, 10): date(2026, 11, 10),
    (2026, 11): date(2026, 12, 10),
}


def release_date_for(year: int, month: int) -> date | None:
    if (year, month) in CPI_RELEASE_DATES:
        return CPI_RELEASE_DATES[(year, month)]
    # Outside the verified table (i.e. more than ~8 months before any
    # backtested decision date in this project's window): a deliberately
    # LATE conservative estimate — release day 20 of month+1, versus the real
    # observed pattern of day ~10-14. This errs toward excluding a value
    # rather than risking a lookahead false-include; it does not need to be
    # exact for months this far in the past relative to any decision date
    # we backtest against.
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)
    return date(next_year, next_month, 20)


def _post_with_retry(url: str, json: dict, timeout: float = 25, attempts: int = 3) -> httpx.Response:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.post(url, json=json, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def _fetch_core_cpi_chunk(start_year: int, end_year: int) -> list[dict]:
    payload = {
        "seriesid": [BLS_CORE_CPI_SA_SERIES],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    api_key = os.environ.get(BLS_API_KEY_ENV)
    if api_key:
        payload["registrationkey"] = api_key
    resp = _post_with_retry(BLS_URL, json=payload)
    data = resp.json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS request failed: {data}")
    return data["Results"]["series"][0]["data"]


def _fetch_and_parse_full_history(start_year: int, end_year: int) -> list[dict]:
    """The full raw parsed history for [start_year, end_year], fetched once
    and cached — regardless of how many different `as_of` cutoffs later slice
    it. This is what keeps a many-market backtest inside BLS's real
    unauthenticated daily quota (~25 requests/day): one raw fetch serves every
    market's as-of filter instead of each market re-fetching the same years."""
    cache_key = (start_year, end_year)
    if cache_key in _CPI_SERIES_CACHE:
        return _CPI_SERIES_CACHE[cache_key]

    rows = []
    chunk_start = start_year
    while chunk_start <= end_year:
        chunk_end = min(chunk_start + 9, end_year)
        rows.extend(_fetch_core_cpi_chunk(chunk_start, chunk_end))
        chunk_start = chunk_end + 1

    parsed = []
    seen = set()
    for row in rows:
        period = row.get("period", "")
        value = row.get("value")
        if not period.startswith("M") or value in (None, "-"):
            continue
        year, month = int(row["year"]), int(period[1:])
        key = (year, month)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "year": year,
                "month": month,
                "value": float(value),
                "latest": row.get("latest") == "true",
            }
        )
    parsed = sorted(parsed, key=lambda r: (r["year"], r["month"]))
    _CPI_SERIES_CACHE[cache_key] = parsed
    return parsed


def fetch_core_cpi_series(
    start_year: int = HISTORY_START_YEAR, end_year: int | None = None, as_of: date | None = None
) -> list[dict]:
    """Official BLS values, oldest first. Unavailable government-shutdown rows
    carry '-' and are skipped rather than coerced into numbers.

    `as_of`: if given, rows whose real BLS *release* date (not reference
    month — see CPI_RELEASE_DATES) falls after `as_of` are excluded. This is
    what makes a genuine no-lookahead backtest possible: BLS's API always
    returns the CURRENT full history, so the caller must filter by when a
    value actually became public, not merely which month it describes.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    full_history = _fetch_and_parse_full_history(start_year, end_year)
    if as_of is None:
        return full_history
    out = []
    for row in full_history:
        rd = release_date_for(row["year"], row["month"])
        if rd is None or rd > as_of:
            continue
        out.append(row)
    return out


def month_over_month_changes(rows: list[dict]) -> list[dict]:
    changes = []
    for prev, cur in zip(rows, rows[1:]):
        pct = (cur["value"] - prev["value"]) / prev["value"] * 100
        reported_single_decimal = round(pct, 1)
        changes.append({**cur, "mom_pct": pct, "reported_single_decimal": reported_single_decimal})
    return changes


def _event_probability(values: list[float], strike_type: str, floor_strike, cap_strike) -> float:
    if not values:
        raise ValueError("cannot compute probability from an empty history")
    if strike_type == "greater":
        hits = sum(1 for v in values if v > float(floor_strike))
    elif strike_type == "less":
        hits = sum(1 for v in values if v < float(cap_strike))
    elif strike_type == "between":
        hits = sum(1 for v in values if float(floor_strike) <= v <= float(cap_strike))
    else:
        raise ValueError(f"Unknown strike_type: {strike_type!r}")
    return hits / len(values)


def compute_core_cpi_probability(
    strike_type: str, floor_strike, cap_strike, target_month: int | None = None, as_of: date | None = None
) -> dict:
    rows = fetch_core_cpi_series(as_of=as_of)
    changes = month_over_month_changes(rows)
    if len(changes) < 36:
        return {
            "oracle_prob": None,
            "confidence": 0.0,
            "prob_low": None,
            "prob_high": None,
            "per_source_values": {"official_bls_rows": len(rows), "usable_monthly_changes": len(changes)},
            "method": "insufficient_bls_history",
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "base_rate": None,
            "refused": True,
            "reason": f"only {len(changes)} usable BLS monthly changes returned",
        }

    all_values = [c["reported_single_decimal"] for c in changes]
    same_month = [
        c["reported_single_decimal"] for c in changes if target_month is not None and c["month"] == target_month
    ]
    trailing = [c["reported_single_decimal"] for c in changes[-36:]]

    historical_prob = _event_probability(all_values, strike_type, floor_strike, cap_strike)
    trailing_prob = _event_probability(trailing, strike_type, floor_strike, cap_strike)
    model_probs = {
        "official_bls_all_history_empirical": historical_prob,
        "official_bls_trailing_36_months_empirical": trailing_prob,
    }
    if len(same_month) >= 5:
        model_probs["official_bls_same_calendar_month_empirical"] = _event_probability(
            same_month, strike_type, floor_strike, cap_strike
        )

    oracle_prob = statistics.fmean(model_probs.values())
    prob_low = min(model_probs.values())
    prob_high = max(model_probs.values())

    # Confidence is the model agreement, capped because this is official
    # history only; it is not a verified consensus-forecast distribution yet.
    raw_agreement = 1.0 - (prob_high - prob_low)
    confidence = min(0.50, max(0.0, raw_agreement))
    latest = rows[-1]

    return {
        "oracle_prob": oracle_prob,
        "confidence": confidence,
        "prob_low": prob_low,
        "prob_high": prob_high,
        "per_model_prob": model_probs,
        "per_source_values": {
            "source": "BLS public API",
            "series": BLS_CORE_CPI_SA_SERIES,
            "latest_observation": f"{latest['year']}-{latest['month']:02d}",
            "latest_index_value": latest["value"],
            "usable_monthly_changes": len(changes),
            "same_month_samples": len(same_month),
            "recent_reported_single_decimal_values": all_values[-8:],
        },
        "method": (
            "official BLS seasonally adjusted core CPI history -> single-decimal MoM changes -> "
            "empirical probability; confidence capped pending verified consensus forecast distribution"
        ),
        "data_freshness": datetime.now(timezone.utc).isoformat(),
        "base_rate": historical_prob,
        "refused": False,
    }
