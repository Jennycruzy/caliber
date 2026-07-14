import unittest

from rwoo.readers.limitless import to_canonical


class LimitlessReaderTests(unittest.TestCase):
    def test_canonical_id_uses_retrievable_slug_not_condition_id(self):
        market = {
            "id": 320995,
            "conditionId": "0xcondition",
            "slug": "england-1783846801420",
            "title": "England",
            "description": "England wins the match.",
            "expirationTimestamp": 1784228400000,
            "prices": [0.36, 0.64],
            "categories": ["Football Matches"],
            "tags": ["Football"],
            "status": "FUNDED",
        }

        canonical = to_canonical(market)

        self.assertEqual(canonical.market_id, "england-1783846801420")
        self.assertEqual(canonical.raw["market"]["conditionId"], "0xcondition")


if __name__ == "__main__":
    unittest.main()
