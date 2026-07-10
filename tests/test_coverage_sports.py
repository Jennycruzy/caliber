"""Coverage classification for the tennis/NBA sources added 2026-07-10.

These assert the *status* the classifier assigns — the honest distinction
between `engine_available` (priced), `model_missing` (source reachable but the
specific engine is deferred), and `parse_missing` (recognized, unparseable).
All paths here are pure text classification; no network calls.
"""
import unittest

from rwoo.coverage import classify_market_shape
from tests.support import make_market


def _cov(question, venue="limitless"):
    return classify_market_shape(make_market(venue=venue, domain="sports", question=question))


class TennisNbaCoverageTests(unittest.TestCase):
    def test_tennis_head_to_head_is_engine_available(self):
        # one-sided title binds YES unambiguously -> priced shape
        cov = _cov("Wimbledon: Will Sinner beat Alcaraz?")
        self.assertEqual(cov.family, "sports.tennis")
        self.assertEqual(cov.status, "engine_available")

    def test_tennis_unbindable_head_to_head_is_parse_missing(self):
        # symmetric title with no bound YES side -> refuse (non-actionable)
        cov = _cov("Wimbledon: Sinner vs Alcaraz - who wins?")
        self.assertEqual(cov.family, "sports.tennis")
        self.assertEqual(cov.status, "parse_missing")

    def test_tennis_tournament_winner_is_model_missing(self):
        # source reachable (UTS Elo) but no draw/bracket simulation wired.
        cov = _cov("Wimbledon winner 2026?")
        self.assertEqual(cov.family, "sports.tennis")
        self.assertEqual(cov.status, "model_missing")

    def test_nba_champion_is_model_missing(self):
        # source reachable (ESPN) but no champion simulation wired.
        cov = _cov("Who will be the 2027 NBA champion?")
        self.assertEqual(cov.family, "sports.nba")
        self.assertEqual(cov.status, "model_missing")

    def test_no_status_is_source_missing_for_these(self):
        # regression guard: the 2026-07-09 source_missing verdicts were retired
        # once ESPN/UTS were verified reachable.
        for q in (
            "Wimbledon: Sinner vs Alcaraz - who wins?",
            "Wimbledon winner 2026?",
            "Who will be the 2027 NBA champion?",
        ):
            self.assertNotEqual(_cov(q).status, "source_missing", q)


if __name__ == "__main__":
    unittest.main()
