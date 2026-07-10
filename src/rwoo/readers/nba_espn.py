"""NBA team-strength reader — ESPN public standings API.

`stats.nba.com` times out from this workspace and `balldontlie` now requires an
API key, so neither is usable here. ESPN's undocumented public standings
endpoint IS reachable (verified live 2026-07-10: HTTP 200 JSON) and exposes,
per team, wins/losses and season point differential — a well-established
team-strength signal (the basis of SRS). This is undocumented and can change
shape without notice, so parsing is defensive and a thin/short table raises
rather than passing off partial data as coverage.

The engine (`engines/sports.py`) keys its confidence on games actually played,
so an early-season or empty table is priced with low confidence (or refused)
rather than pretending a prior-season prior is current form.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
USER_AGENT = "Mozilla/5.0 rwoo-verifier/1.0"

_STANDINGS_CACHE: dict[str, Any] | None = None


def _get_with_retry(timeout: float = 15, attempts: int = 3) -> httpx.Response:
    last_exc: Exception | None = None
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(STANDINGS_URL, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.0 * attempt)
    assert last_exc is not None
    raise last_exc


def _collect_entries(node: Any, acc: list) -> None:
    """Gather every ``entries`` list in the tree. ESPN splits the standings
    into conference groups (Eastern/Western), so a single group is only half
    the league — all groups must be merged."""
    if isinstance(node, dict):
        if node.get("entries"):
            acc.extend(node["entries"])
        for value in node.values():
            _collect_entries(value, acc)
    elif isinstance(node, list):
        for value in node:
            _collect_entries(value, acc)


def _stat_value(stats: list[dict], name: str) -> float | None:
    for stat in stats:
        if stat.get("type") == name or stat.get("name") == name:
            value = stat.get("value")
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    return None


def fetch_team_strength() -> dict[str, Any]:
    """Return {"season": str|None, "teams": [ {name, wins, losses,
    games_played, avg_point_diff} ]} from the ESPN standings feed.

    ``avg_point_diff`` (net points per game) is the rating the engine uses.
    """
    global _STANDINGS_CACHE
    if _STANDINGS_CACHE is not None:
        return dict(_STANDINGS_CACHE)

    data = _get_with_retry().json()
    season_label = (data.get("season") or {}).get("displayName")
    entries: list = []
    _collect_entries(data, entries)
    teams: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        name = (entry.get("team") or {}).get("displayName")
        stats = entry.get("stats", [])
        if not name or not stats or name in seen:
            continue
        seen.add(name)
        wins = _stat_value(stats, "wins")
        losses = _stat_value(stats, "losses")
        # Prefer per-game differential; fall back to total / games played.
        avg_diff = _stat_value(stats, "differential")
        games_played = None
        if wins is not None and losses is not None:
            games_played = int(wins + losses)
        if avg_diff is None:
            total_diff = _stat_value(stats, "pointDifferential")
            if total_diff is not None and games_played:
                avg_diff = total_diff / games_played
        if avg_diff is None:
            continue
        teams.append(
            {
                "name": name,
                "wins": int(wins) if wins is not None else None,
                "losses": int(losses) if losses is not None else None,
                "games_played": games_played,
                "avg_point_diff": avg_diff,
            }
        )
    if len(teams) < 20:
        raise RuntimeError(
            f"ESPN NBA standings returned only {len(teams)} usable teams (expected 30)"
        )
    result = {"season": season_label, "teams": teams}
    _STANDINGS_CACHE = dict(result)
    return result
