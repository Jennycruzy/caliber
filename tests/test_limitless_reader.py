import unittest
from unittest.mock import patch

import httpx

from rwoo.readers.errors import ExecutableQuoteUnavailable
from rwoo.readers.limitless import (
    fetch_canonical_market,
    fetch_canonical_markets,
    suggest_market_refs,
    to_canonical,
)


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

    def test_group_slug_never_silently_selects_first_child(self):
        group = {
            "slug": "world-cup-winner",
            "title": "World Cup Winner",
            "markets": [
                {"id": 1, "slug": "spain", "title": "Spain", "tradePrices": {
                    "buy": {"market": [40]}, "sell": {"market": [38]},
                }},
                {"id": 2, "slug": "france", "title": "France", "tradePrices": {
                    "buy": {"market": [35]}, "sell": {"market": [33]},
                }},
            ],
        }

        def handler(request):
            return httpx.Response(200, json={"data": group}, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.assertIsNone(fetch_canonical_market("world-cup-winner", client=client))
            candidates = suggest_market_refs("world-cup-winner", client=client)
        self.assertEqual([row["market_id"] for row in candidates], ["spain", "france"])

    def test_single_market_requires_real_executable_quotes(self):
        market = {"id": 1, "slug": "thin-market", "title": "Thin", "prices": [0.5, 0.5]}

        def handler(request):
            return httpx.Response(200, json={"data": market}, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ExecutableQuoteUnavailable):
                fetch_canonical_market("thin-market", client=client)

    def test_batch_scan_quarantines_crossed_book_instead_of_aborting(self):
        crossed = {
            "id": 1, "slug": "crossed", "title": "Crossed",
            "tradePrices": {"buy": {"market": [40]}, "sell": {"market": [60]}},
        }
        valid = {
            "id": 2, "slug": "valid", "title": "Valid",
            "tradePrices": {"buy": {"market": [60]}, "sell": {"market": [40]}},
        }
        with patch(
            "rwoo.readers.limitless.fetch_scanner_markets",
            return_value=[{"market": crossed}, {"market": valid}],
        ):
            markets = fetch_canonical_markets(active_limit=2)
        self.assertEqual([market.market_id for market in markets], ["valid"])


if __name__ == "__main__":
    unittest.main()
