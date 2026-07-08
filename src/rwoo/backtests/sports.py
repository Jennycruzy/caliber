"""Sports calibration backtest with a no-lookahead proof.

Real, resolved tournament-outright markets (Polymarket) scored against what
the sports engine's method would have said using team ratings computed by
replaying real match history only up to the market's decision date — never
today's ratings, which would leak the outcome of everything since then.

Tournament fields (which teams actually competed) are reconstructed from the
real match dataset itself, not guessed as "top N by global rating" — that
would be wrong for a fixed continental field like the Euros or Copa América.
"""
from __future__ import annotations

import time
from datetime import date, datetime

import httpx

from rwoo.backtests.sports_elo import fetch_match_history, replay_ratings_as_of, tournament_field
from rwoo.calibration import CalibrationRecord, probability_bucket
from rwoo.engines.sports import _rank_decay_probability, _softmax_probability

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"

# Each entry: (Polymarket event slug, our match-dataset tournament name, year,
# the real winner's team name as it appears in BOTH the market question and
# the match dataset). Only tournaments with real, resolved, per-team
# Polymarket markets are included — not guessed or assumed.
RESOLVED_TOURNAMENTS = [
    {"slug": "euro-2024-winner", "dataset_tournament": "UEFA Euro", "year": 2024, "winner": "Spain"},
    {"slug": "copa-america-winner", "dataset_tournament": "Copa América", "year": 2024, "winner": "Argentina"},
]


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


def fetch_resolved_tournament_markets(slug: str) -> dict:
    resp = _get_with_retry(GAMMA_EVENTS_URL, params={"slug": slug})
    events = resp.json()
    if not events:
        raise RuntimeError(f"no Polymarket event found for slug {slug!r}")
    return events[0]


def _team_name_from_question(question: str) -> str | None:
    # "Will England win the 2024 Euros?" / "Will the Netherlands win..."
    # / "Argentina wins Copa America 2024?"
    for prefix, suffix in (("Will ", " win the"), ("", " wins")):
        if question.startswith(prefix) and suffix in question:
            name = question[len(prefix):].split(suffix)[0].strip()
            if name.lower().startswith("the "):
                name = name[4:]
            return name
    return None


def build_sports_backtest() -> tuple[list[CalibrationRecord], list[dict]]:
    records: list[CalibrationRecord] = []
    raw_rows: list[dict] = []
    matches = fetch_match_history()

    for tournament in RESOLVED_TOURNAMENTS:
        try:
            event = fetch_resolved_tournament_markets(tournament["slug"])
        except Exception as exc:  # noqa: BLE001
            raw_rows.append({"tournament": tournament, "engine_result": {"refused": True, "reason": str(exc)}})
            continue

        decision_timestamp = event["startDate"]
        decision_date = datetime.fromisoformat(decision_timestamp.replace("Z", "+00:00")).date()
        field_teams = tournament_field(tournament["dataset_tournament"], tournament["year"], matches=matches)
        if len(field_teams) < 4:
            raw_rows.append(
                {
                    "tournament": tournament,
                    "engine_result": {
                        "refused": True,
                        "reason": f"only {len(field_teams)} teams reconstructed for this tournament — too few for a real field",
                    },
                }
            )
            continue

        ratings_as_of = replay_ratings_as_of(decision_date, matches=matches)
        field_ratings = [
            {"team": t, "rating": ratings_as_of.get(t, 1500.0)} for t in field_teams
        ]
        field_ratings.sort(key=lambda r: -r["rating"])
        for i, r in enumerate(field_ratings, start=1):
            r["rank"] = i

        for market in event.get("markets", []):
            team = _team_name_from_question(market["question"])
            if not team:
                continue  # e.g. "Will another team win the 2024 Euros?" — not a single-team prediction
            target = next((r for r in field_ratings if r["team"].lower() == team.lower()), None)
            if target is None:
                raw_rows.append(
                    {
                        "tournament": tournament,
                        "market": market,
                        "engine_result": {
                            "refused": True,
                            "reason": f"{team!r} not found in the reconstructed real tournament field",
                        },
                    }
                )
                continue

            softmax_prob = _softmax_probability(target, field_ratings, scale=115.0)
            rank_decay_prob = _rank_decay_probability(target, field_ratings)
            oracle_prob = (softmax_prob + rank_decay_prob) / 2
            result = {
                "refused": False,
                "oracle_prob": oracle_prob,
                "per_model_prob": {
                    "elo_rating_softmax": softmax_prob,
                    "elo_rank_decay": rank_decay_prob,
                },
                "decision_timestamp": decision_timestamp,
                "field_size": len(field_teams),
                "target_rating_as_of_decision": target["rating"],
                "target_rank_as_of_decision": target["rank"],
                "method": (
                    "self-computed Elo (replayed from real match history, as-of decision date) over the "
                    "REAL reconstructed tournament field -> same softmax/rank-decay transform as the live engine"
                ),
            }
            raw_rows.append({"tournament": tournament, "market": market, "engine_result": result})

            outcome = 1 if team.lower() == tournament["winner"].lower() else 0
            records.append(
                CalibrationRecord(
                    domain="sports",
                    venue="polymarket",
                    market_id=market["id"],
                    question=market["question"],
                    decision_timestamp=decision_timestamp,
                    resolution_timestamp=event.get("endDate"),
                    oracle_prob=oracle_prob,
                    outcome=outcome,
                    bucket=probability_bucket(oracle_prob),
                    source_run=f"{tournament['dataset_tournament']} {tournament['year']}",
                    source_available_at=f"Elo replayed from real matches strictly before {decision_date.isoformat()}",
                    target_date=str(tournament["year"]),
                )
            )
    return records, raw_rows
