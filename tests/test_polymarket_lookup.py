"""Offline tests for exact Polymarket identifiers and safe fuzzy suggestions."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import httpx

from rwoo.api import market_fetch
from rwoo.api.errors import OracleError
from rwoo.readers import polymarket
from rwoo.readers.errors import ExecutableQuoteUnavailable


def market_row(**overrides) -> dict:
    row = {
        "id": "123",
        "conditionId": "0xabc",
        "slug": "fed-decision-in-october",
        "question": "Will the Fed cut rates in October?",
        "description": "Resolves from the Federal Reserve announcement.",
        "resolutionSource": "Federal Reserve",
        "endDate": "2026-10-31T00:00:00Z",
        "bestBid": 0.40,
        "bestAsk": 0.44,
        "outcomes": '["Yes", "No"]',
        "events": [],
        "active": True,
        "closed": False,
    }
    row.update(overrides)
    return row


class PolymarketReaderLookupTests(unittest.TestCase):
    def client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_numeric_id_uses_market_id_path(self):
        def handler(request):
            self.assertEqual(request.url.path, "/markets/123")
            return httpx.Response(200, json=market_row(), request=request)

        with self.client(handler) as client:
            result = polymarket.fetch_canonical_market("123", client=client)
        self.assertEqual(result.market_id, "0xabc")

    def test_oversized_numeric_id_422_is_a_confirmed_miss(self):
        def handler(request):
            self.assertEqual(request.url.path, "/markets/9999999999")
            return httpx.Response(422, json={"detail": "invalid integer"}, request=request)

        with self.client(handler) as client:
            result = polymarket.fetch_canonical_market("9999999999", client=client)
        self.assertIsNone(result)

    def test_condition_id_uses_filter(self):
        def handler(request):
            self.assertEqual(request.url.path, "/markets")
            self.assertEqual(request.url.params["condition_ids"], "0xabc")
            return httpx.Response(200, json=[market_row()], request=request)

        with self.client(handler) as client:
            result = polymarket.fetch_canonical_market("0xabc", client=client)
        self.assertEqual(result.market_id, "0xabc")

    def test_exact_market_slug_uses_slug_path(self):
        def handler(request):
            self.assertEqual(request.url.path, "/markets/slug/fed-decision-in-october")
            return httpx.Response(200, json=market_row(), request=request)

        with self.client(handler) as client:
            result = polymarket.fetch_canonical_market(
                "fed-decision-in-october", client=client,
            )
        self.assertEqual(result.raw["slug"], "fed-decision-in-october")

    def test_single_market_event_slug_resolves_exact_child(self):
        seen = []

        def handler(request):
            seen.append(request.url.path)
            if request.url.path.startswith("/markets/slug/"):
                return httpx.Response(404, json={"error": "not found"}, request=request)
            return httpx.Response(
                200,
                json={"slug": "fed-event", "title": "Fed event", "markets": [market_row()]},
                request=request,
            )

        with self.client(handler) as client:
            result = polymarket.fetch_canonical_market("fed-event", client=client)
        self.assertEqual(
            seen,
            ["/markets/slug/fed-event", "/events/slug/fed-event"],
        )
        self.assertEqual(result.market_id, "0xabc")

    def test_multi_market_event_is_not_silently_selected(self):
        def handler(request):
            if request.url.path.startswith("/markets/slug/"):
                return httpx.Response(404, json={}, request=request)
            return httpx.Response(
                200,
                json={
                    "slug": "fed-event",
                    "markets": [market_row(), market_row(id="124", conditionId="0xdef")],
                },
                request=request,
            )

        with self.client(handler) as client:
            result = polymarket.fetch_canonical_market("fed-event", client=client)
        self.assertIsNone(result)

    def test_real_upstream_503_propagates(self):
        def handler(request):
            return httpx.Response(503, json={"error": "down"}, request=request)

        with self.client(handler) as client:
            with self.assertRaises(httpx.HTTPStatusError) as raised:
                polymarket.fetch_canonical_market("fed-event", client=client)
        self.assertEqual(raised.exception.response.status_code, 503)

    def test_single_lookup_requires_executable_bid_and_ask(self):
        def handler(request):
            return httpx.Response(
                200,
                json=market_row(bestBid=None, bestAsk=None, outcomePrices='["0.5", "0.5"]'),
                request=request,
            )

        with self.client(handler) as client:
            with self.assertRaises(ExecutableQuoteUnavailable):
                polymarket.fetch_canonical_market("123", client=client)

    def test_exact_event_candidates_are_compact_and_resubmittable(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "slug": "fed-event",
                    "title": "Fed event",
                    "markets": [
                        market_row(),
                        market_row(
                            id="124", conditionId="0xdef", slug="fed-no-cut",
                            question="Will the Fed hold rates?", closed=True,
                        ),
                    ],
                },
                request=request,
            )

        with self.client(handler) as client:
            candidates = polymarket.suggest_market_refs("fed-event", client=client)
        self.assertEqual([row["market_id"] for row in candidates], ["0xabc", "0xdef"])
        self.assertEqual(candidates[0]["event_slug"], "fed-event")
        self.assertEqual(candidates[1]["status"], "closed")

    def test_fuzzy_search_is_used_only_for_suggestions(self):
        seen = []

        def handler(request):
            seen.append(request)
            if request.url.path.startswith("/events/slug/"):
                return httpx.Response(404, json={}, request=request)
            return httpx.Response(
                200,
                json={"events": [{"slug": "match", "markets": [market_row()]}]},
                request=request,
            )

        with self.client(handler) as client:
            candidates = polymarket.suggest_market_refs(
                "fed-rate-cut-september-2025", client=client,
            )
        self.assertEqual(seen[-1].url.path, "/public-search")
        self.assertEqual(seen[-1].url.params["q"], "fed rate cut september 2025")
        self.assertEqual(candidates[0]["market_id"], "0xabc")

    def test_fuzzy_candidates_rank_closest_child_not_event_order(self):
        def handler(request):
            if request.url.path.startswith("/events/slug/"):
                return httpx.Response(404, json={}, request=request)
            return httpx.Response(200, json={"events": [{
                "slug": "fed-rate-cut-by",
                "title": "Fed rate cut by...?",
                "markets": [
                    market_row(
                        id="1", conditionId="0xjan", slug="fed-rate-cut-by-january-2026",
                        question="Fed rate cut by January 2026?",
                    ),
                    market_row(
                        id="2", conditionId="0xsep", slug="fed-rate-cut-by-september-2026",
                        question="Fed rate cut by September 2026?",
                    ),
                ],
            }]}, request=request)

        with self.client(handler) as client:
            candidates = polymarket.suggest_market_refs(
                "fed-rate-cut-sep-2025", client=client,
            )
        self.assertEqual(candidates[0]["market_id"], "0xsep")


class MarketFetchErrorTests(unittest.TestCase):
    def test_missing_executable_quote_is_422_not_fabricated_probability(self):
        from rwoo.readers.errors import ExecutableQuoteUnavailable

        def no_quote(_market_id):
            raise ExecutableQuoteUnavailable("polymarket", "0xabc", "no book")

        with patch.dict(market_fetch._FETCHERS, {"polymarket": no_quote}):
            with self.assertRaises(OracleError) as raised:
                market_fetch.fetch_canonical("polymarket", "0xabc")
        self.assertEqual(raised.exception.code, "SOURCE_STALE")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertEqual(raised.exception.details["reason"], "no_executable_quote")

    def test_confirmed_miss_is_404_with_candidates(self):
        candidate = {"market_id": "0xabc", "slug": "correct-slug"}
        with patch.dict(market_fetch._FETCHERS, {"polymarket": lambda _v: None}), patch(
            "rwoo.api.market_fetch.polymarket.suggest_market_refs",
            return_value=[candidate],
        ):
            with self.assertRaises(OracleError) as raised:
                market_fetch.fetch_canonical("polymarket", "wrong-slug")
        error = raised.exception
        self.assertEqual(error.code, "MARKET_NOT_FOUND")
        self.assertEqual(error.http_status, 404)
        self.assertEqual(error.details["candidates"], [candidate])
        self.assertIn("resubmit", error.details["action"])

    def test_suggestion_failure_does_not_change_confirmed_404(self):
        request = httpx.Request("GET", "https://gamma-api.polymarket.com/public-search")
        with patch.dict(market_fetch._FETCHERS, {"polymarket": lambda _v: None}), patch(
            "rwoo.api.market_fetch.polymarket.suggest_market_refs",
            side_effect=httpx.ConnectError("offline", request=request),
        ):
            with self.assertRaises(OracleError) as raised:
                market_fetch.fetch_canonical("polymarket", "wrong-slug")
        self.assertEqual(raised.exception.code, "MARKET_NOT_FOUND")
        self.assertNotIn("candidates", raised.exception.details)

    def test_upstream_503_has_actionable_safe_details(self):
        request = httpx.Request("GET", "https://gamma-api.polymarket.com/markets/123")
        response = httpx.Response(503, request=request)

        def unavailable(_market_id):
            raise httpx.HTTPStatusError("down", request=request, response=response)

        with patch.dict(market_fetch._FETCHERS, {"polymarket": unavailable}):
            with self.assertRaises(OracleError) as raised:
                market_fetch.fetch_canonical("polymarket", "123")
        error = raised.exception
        self.assertEqual(error.code, "SOURCE_UNAVAILABLE")
        self.assertEqual(error.http_status, 503)
        self.assertEqual(error.details["upstream_status"], 503)
        self.assertEqual(error.details["reason"], "upstream_http_error")
        self.assertTrue(error.details["retryable"])
        self.assertNotIn("down", error.to_body("req_1")["error"].get("details", {}))

    def test_invalid_upstream_json_is_retryable_503_not_internal_error(self):
        def malformed(_market_id):
            raise ValueError("invalid JSON containing private upstream text")

        with patch.dict(market_fetch._FETCHERS, {"polymarket": malformed}):
            with self.assertRaises(OracleError) as raised:
                market_fetch.fetch_canonical("polymarket", "123")
        error = raised.exception
        self.assertEqual(error.code, "SOURCE_UNAVAILABLE")
        self.assertEqual(error.http_status, 503)
        self.assertEqual(error.details["reason"], "invalid_upstream_payload")
        self.assertNotIn("private", error.message)


class LiveCandidateDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_venue_http_reads_are_concurrent_and_non_blocking(self):
        active = 0
        max_active = 0

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, params=None):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.01)
                active -= 1
                request = httpx.Request("GET", url, params=params)
                if "gamma-api.polymarket.com" in url:
                    payload = [market_row(conditionId="0xpoly", slug="poly-live")]
                elif "kalshi.com" in url:
                    payload = {"markets": [{
                        "ticker": "KX-LIVE", "title": "Kalshi live market",
                        "series_ticker": "KXFED", "yes_bid_dollars": "0.40",
                        "yes_ask_dollars": "0.44", "status": "open",
                    }]}
                else:
                    payload = {"data": [{
                        "id": 1, "slug": "limitless-live", "title": "Limitless live market",
                        "status": "FUNDED", "tradePrices": {
                            "buy": {"market": [44]}, "sell": {"market": [40]},
                        },
                    }]}
                return httpx.Response(200, json=payload, request=request)

        with patch("rwoo.api.market_fetch.httpx.AsyncClient", return_value=FakeAsyncClient()):
            candidates, errors = await market_fetch.discover_live_candidates(limit=10)

        self.assertEqual(errors, [])
        self.assertEqual(max_active, 3)
        self.assertEqual(
            {candidate["venue"] for candidate in candidates},
            {"kalshi", "polymarket", "limitless"},
        )


if __name__ == "__main__":
    unittest.main()
