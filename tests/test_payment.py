"""OKX Agent Payments (x402) 402 flow — no network.

Proves the unpaid -> 402 -> valid-payment -> 200 handshake and every rejection
path with a stub verifier that is impossible to enable in production. The
cryptographic settlement is delegated to the verifier; these tests exercise the
transport, the server-side binding checks, replay protection, receipt linkage,
and no-double-charge.
"""
from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from rwoo.api.app import create_app
from rwoo.api.config import Settings
from rwoo.api import payment as pay
from rwoo.api.payment import PaymentConfig, StubVerifier
from tests.test_api import a_market, make_settings, priced_record
from tests.support import ASGITestClient

PRICE = "10000"  # atomic units


def paid_config(**overrides) -> PaymentConfig:
    base = dict(
        enabled=True, mode="stub", environment="development", scheme="exact",
        network="base-sepolia", asset="0xTOKEN", asset_name="USDC", asset_version="2",
        asset_decimals=6,
        recipient="0xRECIPIENT", max_timeout_seconds=300,
        prices={"rwoo.best_signals": PRICE, "rwoo.check_market": PRICE, "rwoo.cross_venue_edge": PRICE},
    )
    base.update(overrides)
    return PaymentConfig(**base)


def paid_client(tmp, config=None, *, settings=None):
    config = config or paid_config()
    settings = settings or make_settings(tmp)
    app = create_app(
        settings,
        fetch_market=lambda v, m: a_market(v, m),
        evaluate=lambda market: priced_record(market),
        payment_config=config,
    )
    return ASGITestClient(app, raise_server_exceptions=False)


def x_payment(config: PaymentConfig, request_hash: str, service="rwoo.check_market", **overrides) -> str:
    inner = {
        "stub_authorized": True,
        "payTo": config.recipient,
        "asset": config.asset,
        "amount": PRICE,
        "validBefore": int(time.time()) + 200,
        "nonce": "nonce-" + str(time.time_ns()),
        "requestHash": request_hash,
        "service": service,
    }
    inner.update(overrides)
    payload = {"x402Version": pay.X402_VERSION, "scheme": config.scheme,
               "network": config.network, "payload": inner}
    return pay.encode_payment_header(payload)


CHECK_BODY = {"market": {"venue": "kalshi", "market_id": "KX-1"},
              "include": {"why_trace": True, "calibration": True, "receipt": True}}


def challenge_hash(client, body=CHECK_BODY) -> str:
    """The faithful client flow: the request-binding hash is read from the 402
    challenge the server issues, not recomputed by the client."""
    resp = client.post("/v1/check-market", json=body)
    assert resp.status_code == 402, resp.status_code
    return resp.json()["accepts"][0]["extra"]["requestHash"]


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_unpaid_returns_402_challenge(self):
        client = paid_client(self.tmp)
        resp = client.post("/v1/check-market", json=CHECK_BODY)
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.headers.get("WWW-Authenticate"), "Payment")
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        body = resp.json()
        self.assertEqual(body["x402Version"], pay.X402_VERSION)
        self.assertEqual(body["error"], "PAYMENT-REQUIRED")
        accept = body["accepts"][0]
        self.assertEqual(accept["scheme"], "exact")
        self.assertEqual(accept["network"], "base-sepolia")
        self.assertEqual(accept["maxAmountRequired"], PRICE)
        self.assertEqual(accept["payTo"], "0xRECIPIENT")
        self.assertEqual(accept["asset"], "0xTOKEN")
        self.assertEqual(accept["extra"]["service"], "rwoo.check_market")
        self.assertIsNotNone(accept["extra"]["requestHash"])

    def test_disabled_config_needs_no_payment(self):
        client = paid_client(self.tmp, config=PaymentConfig())  # disabled
        resp = client.post("/v1/check-market", json=CHECK_BODY)
        self.assertEqual(resp.status_code, 200)


class PaidCallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = paid_config()
        self.client = paid_client(self.tmp, self.config)
        self.req_hash = challenge_hash(self.client)

    def _pay(self, **overrides):
        header = x_payment(self.config, self.req_hash, **overrides)
        return self.client.post("/v1/check-market", json=CHECK_BODY,
                                headers={pay.X_PAYMENT_HEADER: header})

    def test_valid_payment_returns_200_and_links_receipt(self):
        resp = self._pay()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(pay.PAYMENT_RESPONSE_HEADER, resp.headers)
        body = resp.json()
        self.assertEqual(body["status"], "priced")
        rh = body["receipt"]["record_hash"]
        receipt = self.client.get(f"/v1/receipts/{rh}").json()
        self.assertTrue(str(receipt["payload"]["payment_reference"]).startswith("stub:"))
        self.assertEqual(receipt["payload"]["request_id"], body["request_id"])

    def test_wrong_network_rejected(self):
        # override the outer network by re-encoding a full header
        header = self._bad_header(network="ethereum")
        resp = self.client.post("/v1/check-market", json=CHECK_BODY, headers={pay.X_PAYMENT_HEADER: header})
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_wrong_recipient_rejected(self):
        resp = self._pay(payTo="0xATTACKER")
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_wrong_asset_rejected(self):
        resp = self._pay(asset="0xOTHER")
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_insufficient_amount_rejected(self):
        resp = self._pay(amount="1")
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_expired_rejected(self):
        resp = self._pay(validBefore=int(time.time()) - 5)
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_request_binding_mismatch_rejected(self):
        resp = self._pay(requestHash="not-this-request")
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_wrong_service_binding_rejected(self):
        resp = self._pay(service="rwoo.cross_venue_edge")
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_private_key_material_rejected(self):
        resp = self._pay(privateKey="0xdeadbeef")
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_malformed_header_rejected(self):
        resp = self.client.post("/v1/check-market", json=CHECK_BODY,
                                headers={pay.X_PAYMENT_HEADER: "not-base64!!"})
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(resp.json()["error"]["code"], "PAYMENT_INVALID")

    def test_replayed_nonce_rejected_and_no_double_charge(self):
        header = x_payment(self.config, self.req_hash, nonce="fixed-nonce")
        first = self.client.post("/v1/check-market", json=CHECK_BODY, headers={pay.X_PAYMENT_HEADER: header})
        second = self.client.post("/v1/check-market", json=CHECK_BODY, headers={pay.X_PAYMENT_HEADER: header})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 402)
        self.assertEqual(second.json()["error"]["code"], "PAYMENT_REPLAYED")

    def test_idempotency_retry_does_not_recharge(self):
        header = x_payment(self.config, self.req_hash, nonce="idem-nonce")
        h = {pay.X_PAYMENT_HEADER: header, "Idempotency-Key": "key-1"}
        first = self.client.post("/v1/check-market", json=CHECK_BODY, headers=h)
        second = self.client.post("/v1/check-market", json=CHECK_BODY, headers=h)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["receipt"]["record_hash"], second.json()["receipt"]["record_hash"])

    def test_paid_idempotency_cache_is_bound_to_payment_credential(self):
        first_header = x_payment(self.config, self.req_hash, nonce="credential-one")
        headers = {pay.X_PAYMENT_HEADER: first_header, "Idempotency-Key": "credential-bound"}
        first = self.client.post("/v1/check-market", json=CHECK_BODY, headers=headers)
        self.assertEqual(first.status_code, 200)

        different_header = x_payment(self.config, self.req_hash, nonce="credential-two")
        changed = self.client.post(
            "/v1/check-market",
            json=CHECK_BODY,
            headers={pay.X_PAYMENT_HEADER: different_header, "Idempotency-Key": "credential-bound"},
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def _bad_header(self, **outer):
        inner = {
            "stub_authorized": True, "payTo": self.config.recipient, "asset": self.config.asset,
            "amount": PRICE, "validBefore": int(time.time()) + 200, "nonce": "n" + str(time.time_ns()),
            "requestHash": self.req_hash, "service": "rwoo.check_market",
        }
        payload = {"x402Version": pay.X402_VERSION, "scheme": self.config.scheme,
                   "network": self.config.network, "payload": inner}
        payload.update(outer)
        return pay.encode_payment_header(payload)


class ProductionSafetyTests(unittest.TestCase):
    def test_stub_verifier_refused_in_production(self):
        with self.assertRaises(RuntimeError):
            StubVerifier("production")

    def test_stub_mode_refused_at_boot_in_production(self):
        cfg = paid_config(environment="production")
        with self.assertRaises(RuntimeError):
            create_app(make_settings(tempfile.mkdtemp()),
                       fetch_market=lambda v, m: a_market(v, m),
                       evaluate=lambda m: priced_record(m), payment_config=cfg)

    def test_settlement_readiness_lists_missing(self):
        cfg = PaymentConfig(enabled=True, mode="facilitator")
        ready, missing = cfg.settlement_readiness()
        self.assertFalse(ready)
        self.assertIn("RWOO_PAYMENT_RECIPIENT", missing)
        self.assertIn("RWOO_PAYMENT_FACILITATOR_URL", missing)
        self.assertIn("RWOO_PAYMENT_ASSET_VERSION", missing)

    def test_facilitator_has_no_legacy_verify_only_path(self):
        cfg = paid_config(mode="facilitator", okx_api_key="key", okx_secret_key="secret",
                          okx_passphrase="pass", facilitator_url="https://web3.okx.com")
        self.assertIsInstance(pay.select_verifier(cfg), pay.DisabledVerifier)

    def test_official_v2_mainnet_challenge_fields(self):
        from x402.schemas import SupportedKind, SupportedResponse

        class FakeFacilitator:
            def __init__(self, *args, **kwargs):
                pass

            def get_supported(self):
                return SupportedResponse(kinds=[SupportedKind(
                    x402_version=2, scheme="exact", network="eip155:196",
                )])

        cfg = paid_config(
            mode="facilitator", environment="production", network="eip155:196",
            asset="0x779ded0c9e1022225f8e0630b35a9b54be713736",
            asset_name="USD₮0", asset_version="1", asset_decimals=6,
            recipient="0x38c3299ee0e771e8d0a756e1a5dd4b8a8e9930ca",
            facilitator_url="https://web3.okx.com", okx_api_key="key",
            okx_secret_key="secret", okx_passphrase="pass", max_timeout_seconds=60,
        )
        tmp = tempfile.mkdtemp()
        scan_path = Path(tmp) / "scan.json"
        scan_path.write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "top": [
                {"venue": "polymarket", "market_id": "0xcurrent-poly",
                 "market_status": "active", "coverage_status": "actionable"},
                {"venue": "kalshi", "market_id": "KX-CURRENT",
                 "market_status": "open", "coverage_status": "actionable"},
            ],
        }), encoding="utf-8")
        settings = make_settings(tmp, opportunity_scan_path=scan_path)
        with patch("x402.http.OKXFacilitatorClient", FakeFacilitator):
            client = paid_client(tmp, cfg, settings=settings)
            response = client.post("/v1/signals", json={"message": "Give me the best signals"})
            check_market_response = client.post(
                "/v1/check-market",
                json={"market": {"venue": "polymarket", "market_id": "fed-decision-in-october"}},
            )
            cross_venue_response = client.post(
                "/v1/cross-venue-edge",
                json={
                    "left": {"venue": "kalshi", "market_id": "KX-EXACT"},
                    "right": {"venue": "polymarket", "market_id": "0xabc"},
                },
            )
            guessed_body_response = client.post(
                "/v1/signals", json={"query": "Show calibration"},
            )
            guessed_check_response = client.post("/v1/check-market", json={"market": "wrong"})
            guessed_cross_response = client.post("/v1/cross-venue-edge", json={"markets": []})

        self.assertEqual(response.status_code, 402)
        # Payment interception precedes FastAPI body validation. A marketplace
        # probe that guessed the body must still receive the discoverable 402,
        # not the business-layer 400 observed during the failed review.
        self.assertEqual(guessed_body_response.status_code, 402)
        self.assertEqual(guessed_check_response.status_code, 402)
        self.assertEqual(guessed_cross_response.status_code, 402)
        self.assertIn("PAYMENT-REQUIRED", guessed_body_response.headers)
        encoded = response.headers.get("PAYMENT-REQUIRED")
        self.assertIsNotNone(encoded)
        challenge = json.loads(base64.b64decode(encoded))
        self.assertEqual(challenge["x402Version"], 2)
        accepted = challenge["accepts"][0]
        self.assertEqual(accepted["network"], "eip155:196")
        self.assertEqual(accepted["asset"], cfg.asset)
        self.assertEqual(accepted["amount"], PRICE)
        self.assertEqual(accepted["payTo"], cfg.recipient)
        self.assertEqual(accepted["maxTimeoutSeconds"], 60)
        self.assertEqual(accepted["extra"], {"name": "USD₮0", "version": "1", "decimals": 6})
        discovery = challenge["extensions"]["bazaar"]
        input_info = discovery["info"]["input"]
        self.assertEqual(input_info["method"], "POST")
        self.assertEqual(input_info["bodyType"], "json")
        self.assertEqual(input_info["body"]["limit"], 5)
        body_schema = discovery["schema"]["properties"]["input"]["properties"]["body"]
        self.assertIn("message", body_schema["required"])
        self.assertEqual(body_schema["properties"]["limit"]["maximum"], 10)
        output_schema = discovery["schema"]["properties"]["output"]["properties"]["example"]
        self.assertEqual(output_schema, {"type": "object"})
        self.assertIn("signals", discovery["info"]["output"]["example"])
        # Keep enough headroom for nginx and marketplace-client header limits.
        self.assertLess(len(encoded), 3_500)

        # The protected check-market route advertises the nested object shape
        # in the 402 itself, before a buyer pays or probes validation errors.
        check_encoded = check_market_response.headers.get("PAYMENT-REQUIRED")
        self.assertIsNotNone(check_encoded)
        check_challenge = json.loads(base64.b64decode(check_encoded))
        check_discovery = check_challenge["extensions"]["bazaar"]
        check_info = check_discovery["info"]["input"]
        self.assertEqual(check_info["body"], {
            "market": {"venue": "polymarket", "market_id": "0xcurrent-poly"},
            "include": {"why_trace": True, "calibration": True, "receipt": True},
        })
        check_schema = check_discovery["schema"]["properties"]["input"]["properties"]["body"]
        self.assertIn("market", check_schema["required"])
        market_ref = check_schema["properties"]["market"]
        self.assertEqual(set(market_ref["required"]), {"venue", "market_id"})
        self.assertIn("single-market event slug", market_ref["properties"]["market_id"]["description"])
        self.assertLess(len(check_encoded), 3_500)

        cross_encoded = cross_venue_response.headers.get("PAYMENT-REQUIRED")
        self.assertIsNotNone(cross_encoded)
        cross_challenge = json.loads(base64.b64decode(cross_encoded))
        cross_schema = cross_challenge["extensions"]["bazaar"]["schema"]["properties"]["input"]["properties"]["body"]
        self.assertEqual(set(cross_schema["required"]), {"left", "right"})
        venue_ref = cross_schema["properties"]["left"]
        self.assertEqual(set(venue_ref["required"]), {"venue", "market_id"})
        cross_info = cross_challenge["extensions"]["bazaar"]["info"]["input"]
        self.assertEqual(cross_info["body"]["left"], {
            "venue": "polymarket", "market_id": "0xcurrent-poly",
        })
        self.assertEqual(cross_info["body"]["right"], {
            "venue": "kalshi", "market_id": "KX-CURRENT",
        })
        self.assertLess(len(cross_encoded), 3_500)

    def test_paid_best_signals_readiness_requires_a_fresh_scan(self):
        tmp = tempfile.mkdtemp()
        missing_scan = Path(tmp) / "missing.json"
        settings = make_settings(tmp, opportunity_scan_path=missing_scan)
        client = paid_client(tmp, settings=settings)
        response = client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertFalse(response.json()["checks"]["paid_signal_scan"]["ok"])

        scan_path = Path(tmp) / "fresh.json"
        scan_path.write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(), "top": [],
        }), encoding="utf-8")
        fresh_settings = make_settings(tmp, opportunity_scan_path=scan_path)
        fresh_client = paid_client(tmp, settings=fresh_settings)
        self.assertEqual(fresh_client.get("/readyz").status_code, 200)

    def test_listing_probe_get_receives_challenge_before_business_logic(self):
        """The marketplace can probe and replay an identical body-free GET.

        This is the endpoint we advertise for listing review: it has safe
        defaults after payment, while the payment middleware must intercept
        the initial request before any request-schema validation.
        """
        from x402.schemas import SupportedKind, SupportedResponse

        class FakeFacilitator:
            def __init__(self, *args, **kwargs):
                pass

            def get_supported(self):
                return SupportedResponse(kinds=[SupportedKind(
                    x402_version=2, scheme="exact", network="eip155:196",
                )])

        cfg = paid_config(
            mode="facilitator", environment="production", network="eip155:196",
            asset="0x779ded0c9e1022225f8e0630b35a9b54be713736",
            asset_name="USD₮0", asset_version="1", asset_decimals=6,
            recipient="0x38c3299ee0e771e8d0a756e1a5dd4b8a8e9930ca",
            facilitator_url="https://web3.okx.com", okx_api_key="key",
            okx_secret_key="secret", okx_passphrase="pass", max_timeout_seconds=300,
        )
        with patch("x402.http.OKXFacilitatorClient", FakeFacilitator):
            client = paid_client(tempfile.mkdtemp(), cfg)
            response = client.get("/v1/signals")

        self.assertEqual(response.status_code, 402)
        challenge = json.loads(base64.b64decode(response.headers["PAYMENT-REQUIRED"]))
        self.assertEqual(challenge["x402Version"], 2)
        self.assertEqual(challenge["resource"]["url"], "http://testserver/v1/signals")
        self.assertEqual(challenge["accepts"][0]["payTo"], cfg.recipient)
        discovery = challenge["extensions"]["bazaar"]
        input_info = discovery["info"]["input"]
        self.assertEqual(input_info["method"], "GET")
        self.assertEqual(input_info["queryParams"]["limit"], 5)
        query_schema = discovery["schema"]["properties"]["input"]["properties"]["queryParams"]
        self.assertEqual(query_schema["properties"]["limit"]["maximum"], 10)
        self.assertFalse(query_schema["additionalProperties"])

    def test_settlement_timeout_poll_releases_paid_deliverable(self):
        """A submitted transfer can confirm just after OKX's settle call times out.

        The facilitator wrapper must expose get_settle_status so upstream x402
        can confirm that transaction and return the buffered business response,
        rather than charging the buyer and replying with an empty 402.
        """
        from x402.schemas import SettleResponse, SupportedKind, SupportedResponse, VerifyResponse

        class TimeoutThenConfirmedFacilitator:
            instance = None

            def __init__(self, *args, **kwargs):
                self.status_calls = 0
                type(self).instance = self

            def get_supported(self):
                return SupportedResponse(kinds=[SupportedKind(
                    x402_version=2, scheme="exact", network="eip155:196",
                )])

            async def verify(self, payload, requirements):
                return VerifyResponse(isValid=True, payer="0x" + "1" * 40)

            async def verify_signature(self, payload, requirements=None):
                return VerifyResponse(isValid=True, payer="0x" + "1" * 40)

            async def settle(self, payload, requirements):
                return SettleResponse(
                    success=True, status="timeout", payer="0x" + "1" * 40,
                    transaction="0xabc", network="eip155:196",
                )

            async def get_settle_status(self, tx_hash):
                self.status_calls += 1
                return SettleResponse(
                    success=True, status="success", payer="0x" + "1" * 40,
                    transaction=tx_hash, network="eip155:196",
                )

        cfg = paid_config(
            mode="facilitator", environment="production", network="eip155:196",
            asset="0x779ded0c9e1022225f8e0630b35a9b54be713736",
            asset_name="USD₮0", asset_version="1", asset_decimals=6,
            recipient="0x38c3299ee0e771e8d0a756e1a5dd4b8a8e9930ca",
            facilitator_url="https://web3.okx.com", okx_api_key="key",
            okx_secret_key="secret", okx_passphrase="pass",
        )
        with patch("x402.http.OKXFacilitatorClient", TimeoutThenConfirmedFacilitator):
            client = paid_client(tempfile.mkdtemp(), cfg)
            unpaid = client.post("/v1/check-market", json=CHECK_BODY)
            challenge = json.loads(base64.b64decode(unpaid.headers["PAYMENT-REQUIRED"]))
            payload = {
                "x402Version": 2,
                "payload": {"authorization": {}},
                "accepted": challenge["accepts"][0],
                "resource": challenge["resource"],
            }
            payment_signature = base64.b64encode(
                json.dumps(payload, separators=(",", ":")).encode()
            ).decode()
            paid = client.post(
                "/v1/check-market", json=CHECK_BODY,
                headers={"PAYMENT-SIGNATURE": payment_signature},
            )

        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.json()["status"], "priced")
        self.assertIn("PAYMENT-RESPONSE", paid.headers)
        self.assertEqual(TimeoutThenConfirmedFacilitator.instance.status_calls, 1)

    def test_production_idempotency_replay_settles_only_once(self):
        from x402.schemas import SettleResponse, SupportedKind, SupportedResponse, VerifyResponse

        class CountingFacilitator:
            instance = None

            def __init__(self, *args, **kwargs):
                self.verify_calls = 0
                self.settle_calls = 0
                type(self).instance = self

            def get_supported(self):
                return SupportedResponse(kinds=[SupportedKind(
                    x402_version=2, scheme="exact", network="eip155:196",
                )])

            async def verify(self, payload, requirements):
                self.verify_calls += 1
                return VerifyResponse(isValid=True, payer="0x" + "1" * 40)

            async def verify_signature(self, payload, requirements=None):
                self.verify_calls += 1
                return VerifyResponse(isValid=True, payer="0x" + "1" * 40)

            async def settle(self, payload, requirements):
                self.settle_calls += 1
                return SettleResponse(
                    success=True, status="success", payer="0x" + "1" * 40,
                    transaction="0xpaid", network="eip155:196",
                )

            async def get_settle_status(self, tx_hash):
                raise AssertionError("successful settlement must not poll")

        cfg = paid_config(
            mode="facilitator", environment="production", network="eip155:196",
            asset="0x779ded0c9e1022225f8e0630b35a9b54be713736",
            asset_name="USD₮0", asset_version="1", asset_decimals=6,
            recipient="0x38c3299ee0e771e8d0a756e1a5dd4b8a8e9930ca",
            facilitator_url="https://web3.okx.com", okx_api_key="key",
            okx_secret_key="secret", okx_passphrase="pass",
        )
        with patch("x402.http.OKXFacilitatorClient", CountingFacilitator):
            client = paid_client(tempfile.mkdtemp(), cfg)
            unpaid = client.post("/v1/check-market", json=CHECK_BODY)
            challenge = json.loads(base64.b64decode(unpaid.headers["PAYMENT-REQUIRED"]))
            payload = {
                "x402Version": 2,
                "payload": {"authorization": {}},
                "accepted": challenge["accepts"][0],
                "resource": challenge["resource"],
            }
            signature = base64.b64encode(
                json.dumps(payload, separators=(",", ":")).encode()
            ).decode()
            headers = {
                "PAYMENT-SIGNATURE": signature,
                "Idempotency-Key": "production-once",
            }
            first = client.post("/v1/check-market", json=CHECK_BODY, headers=headers)
            second = client.post("/v1/check-market", json=CHECK_BODY, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers["X-Idempotent-Replay"], "true")
        self.assertEqual(first.json()["receipt"], second.json()["receipt"])
        self.assertEqual(CountingFacilitator.instance.verify_calls, 1)
        self.assertEqual(CountingFacilitator.instance.settle_calls, 1)


if __name__ == "__main__":
    unittest.main()
