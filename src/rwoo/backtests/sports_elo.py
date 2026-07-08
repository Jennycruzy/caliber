"""Self-computed historical World Football Elo ratings.

No public API provides national-team Elo ratings as of an arbitrary past
date (eloratings.net's TSV only gives current + fixed 1/5/10-year-ago
snapshots — verified live, see docs/VERIFICATION_LEDGER.md). So this module
computes its own rating history by replaying every real historical match
result through the published World Football Elo formula, chronologically.
That is the only way to get a genuinely dated rating for a genuine
no-lookahead sports backtest.

Formula cross-verified 2026-07-08 from Wikipedia's "World Football Elo
Ratings" article and eloratings.net's own methodology description (the
eloratings.net /about page itself is JS-rendered and didn't yield formula
text via direct fetch, so Wikipedia is the primary citation here, disclosed
rather than hidden):
  R_new = R_old + K * (W - We)
  We = 1 / (10^(-dr/400) + 1), dr = rating_diff + 100 if home team not on
       neutral ground, else rating_diff
  K: 60 World Cup finals, 50 continental championship finals, 40 World
     Cup/continental qualifiers, 30 other tournaments, 20 friendlies
  Goal-difference multiplier (win margin N): 1.0 for N<=1, 1.5 for N=2,
     1.75 for N=3, 1.75+(N-3)/8 for N>=4 (draws/1-goal wins: no adjustment)

Match data: martj42/international_results on GitHub — a real, actively
maintained public dataset of international football results, 1872-present
(49,506 rows as of 2026-07-08), including the exact `neutral` flag and
`tournament` name each match needs.
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime

import httpx

RESULTS_CSV_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DEFAULT_RATING = 1500.0
HOME_ADVANTAGE = 100.0

_MATCHES_CACHE: list[dict] | None = None


def _get_with_retry(url: str, timeout: float = 30, attempts: int = 3) -> httpx.Response:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def k_factor_for_tournament(tournament: str) -> float:
    t = tournament.lower()
    if t == "fifa world cup":
        return 60.0
    if "qualif" in t:
        return 40.0
    continental_finals = (
        "uefa euro", "copa américa", "copa america", "african cup of nations",
        "afc asian cup", "gold cup", "oceania nations cup", "afcon",
    )
    if any(name in t for name in continental_finals):
        return 50.0
    if t == "friendly":
        return 20.0
    return 30.0


def goal_diff_multiplier(goal_diff: int) -> float:
    if goal_diff <= 1:
        return 1.0
    if goal_diff == 2:
        return 1.5
    if goal_diff == 3:
        return 1.75
    return 1.75 + (goal_diff - 3) / 8.0


def fetch_match_history() -> list[dict]:
    """Real historical results, oldest first, cached for the process
    lifetime — this is a ~3.7MB one-time fetch reused across every team/date
    query in a backtest run rather than re-downloaded per query."""
    global _MATCHES_CACHE
    if _MATCHES_CACHE is not None:
        return _MATCHES_CACHE
    resp = _get_with_retry(RESULTS_CSV_URL)
    reader = csv.DictReader(io.StringIO(resp.text))
    matches = []
    for row in reader:
        try:
            match_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        home_score, away_score = row.get("home_score"), row.get("away_score")
        if home_score in (None, "", "NA") or away_score in (None, "", "NA"):
            continue  # unplayed/future fixture — real data, not yet resolved
        matches.append(
            {
                "date": match_date,
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home_score": int(float(home_score)),
                "away_score": int(float(away_score)),
                "tournament": row["tournament"],
                "neutral": row.get("neutral", "FALSE").strip().upper() == "TRUE",
            }
        )
    matches.sort(key=lambda m: m["date"])
    _MATCHES_CACHE = matches
    return matches


def replay_ratings_as_of(as_of: date, matches: list[dict] | None = None) -> dict[str, float]:
    """Every team's real Elo rating computed by replaying every real match
    strictly before `as_of`, in chronological order. This is the only way to
    get a rating that couldn't have leaked information from the match(es)
    being backtested."""
    matches = matches if matches is not None else fetch_match_history()
    ratings: dict[str, float] = {}
    for m in matches:
        if m["date"] >= as_of:
            break
        home, away = m["home_team"], m["away_team"]
        hs, aw = m["home_score"], m["away_score"]
        r_home = ratings.get(home, DEFAULT_RATING)
        r_away = ratings.get(away, DEFAULT_RATING)
        dr = (r_home - r_away) + (0.0 if m["neutral"] else HOME_ADVANTAGE)
        we_home = 1.0 / (10 ** (-dr / 400.0) + 1.0)
        if hs > aw:
            w_home = 1.0
        elif hs < aw:
            w_home = 0.0
        else:
            w_home = 0.5
        k = k_factor_for_tournament(m["tournament"]) * goal_diff_multiplier(abs(hs - aw))
        delta = k * (w_home - we_home)
        ratings[home] = r_home + delta
        ratings[away] = r_away - delta
    return ratings


def tournament_field(tournament_name: str, year: int, matches: list[dict] | None = None) -> list[str]:
    """The REAL set of teams that actually played in a specific tournament
    instance — reconstructed from the match data itself, not guessed as
    "top N by global rating" (which would be wrong for a continental
    tournament with a fixed, qualified field)."""
    matches = matches if matches is not None else fetch_match_history()
    teams: set[str] = set()
    for m in matches:
        if m["tournament"] != tournament_name or m["date"].year not in (year, year - 1, year + 1):
            continue
        # A tournament's matches can span a turn-of-year edge case; the
        # decisive filter is the caller passing the right (name, year), and
        # this function is only ever used for tournaments in a single year.
        if m["date"].year == year:
            teams.add(m["home_team"])
            teams.add(m["away_team"])
    return sorted(teams)
