"""Tennis Elo ratings reader — Ultimate Tennis Statistics.

The official ATP rankings endpoint returns HTTP 403 (Cloudflare bot challenge)
and the community CSV mirror 404s from this workspace, so neither is a usable
ratings source here. Ultimate Tennis Statistics publishes an Elo-rating table
that IS reachable (verified live 2026-07-10: HTTP 200 JSON,
`rankType=ELO_RANK`), and Elo is exactly what this project's sports engine
already consumes.

This reader returns raw player display names; name normalization and matching
are the engine's responsibility (`engines/sports.py:_normal_name`), so there is
a single normalization authority.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

RANKINGS_URL = "https://www.ultimatetennisstatistics.com/rankingsTableTable"
USER_AGENT = "Mozilla/5.0 rwoo-verifier/1.0"

_ELO_CACHE: list[dict[str, Any]] | None = None


def _get_with_retry(params: dict[str, Any], timeout: float = 15, attempts: int = 3) -> httpx.Response:
    last_exc: Exception | None = None
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(RANKINGS_URL, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.0 * attempt)
    assert last_exc is not None
    raise last_exc


def fetch_player_elo_ratings(count: int = 500) -> list[dict[str, Any]]:
    """Current men's singles Elo table: list of
    {"rank": int, "player_id": int|None, "name": str, "rating": float}.

    Elo lives in the row's ``points`` field for ``rankType=ELO_RANK``. Rows
    without a usable name/rating are skipped; a short table raises rather than
    letting a truncated feed masquerade as real coverage.
    """
    global _ELO_CACHE
    if _ELO_CACHE is not None:
        return [dict(row) for row in _ELO_CACHE]

    data = _get_with_retry(
        {"rankType": "ELO_RANK", "season": "", "date": "", "count": count}
    ).json()
    ratings: list[dict[str, Any]] = []
    for row in data.get("rows", []):
        name = row.get("name")
        elo = row.get("points")
        if not name or elo in (None, ""):
            continue
        try:
            rating = float(elo)
        except (TypeError, ValueError):
            continue
        ratings.append(
            {
                "rank": int(row.get("rank")) if row.get("rank") is not None else None,
                "player_id": row.get("playerId"),
                "name": name,
                "rating": rating,
            }
        )
    if len(ratings) < 20:
        raise RuntimeError(
            f"Ultimate Tennis Statistics Elo table returned only {len(ratings)} usable rows"
        )
    _ELO_CACHE = [dict(row) for row in ratings]
    return ratings
