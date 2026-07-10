"""Pure logic in the tennis/NBA engines: name matching and the Elo win model.

No network: these exercise `_match_entity` (how a market's player/team name is
resolved to a ratings row) and `_elo_win_probability` (the win-expectation
curve) with synthetic rows.
"""
import unittest

from rwoo.engines.sports import _elo_win_probability, _match_entity

_ROWS = [
    {"name": "Jannik Sinner", "rating": 2414.0},
    {"name": "Carlos Alcaraz Garfia", "rating": 2280.0},
    {"name": "Novak Djokovic", "rating": 2347.0},
    {"name": "Los Angeles Lakers", "rating": 3.1},
    {"name": "Boston Celtics", "rating": 5.4},
]


class MatchEntityTests(unittest.TestCase):
    def test_exact_full_name(self):
        self.assertEqual(_match_entity("Jannik Sinner", _ROWS)["rating"], 2414.0)

    def test_single_surname_token(self):
        self.assertEqual(_match_entity("Alcaraz", _ROWS)["name"], "Carlos Alcaraz Garfia")

    def test_city_token_for_team(self):
        self.assertEqual(_match_entity("Lakers", _ROWS)["name"], "Los Angeles Lakers")

    def test_unknown_returns_none(self):
        self.assertIsNone(_match_entity("Nobody McNobody", _ROWS))

    def test_ambiguous_single_token_refuses(self):
        rows = [
            {"name": "Andy Murray", "rating": 2000.0},
            {"name": "Jamie Murray", "rating": 1900.0},
        ]
        # 'Murray' is in two rows -> ambiguous -> no guess.
        self.assertIsNone(_match_entity("Murray", rows))


class EloWinProbabilityTests(unittest.TestCase):
    def test_equal_ratings_is_even(self):
        self.assertAlmostEqual(_elo_win_probability(2000, 2000), 0.5)

    def test_higher_rating_favored(self):
        self.assertGreater(_elo_win_probability(2400, 2280), 0.5)

    def test_symmetry(self):
        p = _elo_win_probability(2414, 2280)
        q = _elo_win_probability(2280, 2414)
        self.assertAlmostEqual(p + q, 1.0)


if __name__ == "__main__":
    unittest.main()
