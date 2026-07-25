import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _load(name):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


bc = _load("buyer_client")

USDCE = bc.USDCE.lower()
PUSD = bc.PUSD.lower()
ONRAMP = bc.COLLATERAL_ONRAMP.lower()
POLYGON_USDT = bc.buyer_funding.SOURCE_TOKENS["polygon_usdt"]["address"].lower()


class FakeSigner(bc.Signer):
    def __init__(self, address="0x" + "11" * 20):
        self._address = address
        self.sent = []

    def address(self):
        return self._address

    def sign_order(self, order_eip712):
        return "0x" + "cd" * 65

    def sign_and_send(self, tx):
        self.sent.append(tx)
        return "0x" + f"{len(self.sent):064x}"


class FakeRpc:
    """Scripts eth_call reads; every broadcast confirms with status 0x1."""

    def __init__(self, balances=None, allowances=None):
        self.balances = {k.lower(): v for k, v in (balances or {}).items()}
        self.allowances = {k.lower(): v for k, v in (allowances or {}).items()}

    def __call__(self, method, params):
        if method == "eth_call":
            to = params[0]["to"].lower()
            selector = params[0]["data"][:10]
            if selector == bc.SEL_BALANCE_OF:
                return hex(self.balances.get(to, 0))
            if selector == bc.SEL_ALLOWANCE:
                return hex(self.allowances.get(to, 0))
        if method == "eth_getTransactionReceipt":
            return {"status": "0x1"}
        raise AssertionError(f"unexpected rpc call: {method}")


class EnsurePusdTests(unittest.TestCase):
    def test_entry_approval_is_exact_and_bounded(self):
        rpc = FakeRpc(allowances={PUSD: 0})
        signer = FakeSigner()
        tx_hash = bc.ensure_bounded_approval(
            signer, rpc, token=bc.PUSD, spender="0x" + "22" * 20,
            required_units=225_000,
        )
        self.assertIsNotNone(tx_hash)
        self.assertEqual(int(signer.sent[0]["data"][-64:], 16), 225_000)

    def test_sufficient_entry_approval_is_not_rebroadcast(self):
        rpc = FakeRpc(allowances={PUSD: 225_000})
        signer = FakeSigner()
        tx_hash = bc.ensure_bounded_approval(
            signer, rpc, token=bc.PUSD, spender="0x" + "22" * 20,
            required_units=225_000,
        )
        self.assertIsNone(tx_hash)
        self.assertEqual(signer.sent, [])

    def test_already_funded_does_nothing(self):
        rpc = FakeRpc(balances={PUSD: 1_000_000})
        signer = FakeSigner()
        result = bc.ensure_pusd(signer, rpc, 1_000_000)
        self.assertEqual(result["status"], "already_funded")
        self.assertEqual(signer.sent, [])

    def test_usdce_route_approves_then_wraps(self):
        rpc = FakeRpc(balances={USDCE: 2_000_000, PUSD: 0}, allowances={USDCE: 0})
        signer = FakeSigner()
        bc.ensure_pusd(signer, rpc, 1_000_000)
        self.assertEqual(len(signer.sent), 2)
        self.assertEqual(signer.sent[0]["to"].lower(), USDCE)     # approve on-ramp
        self.assertTrue(signer.sent[0]["data"].startswith(bc.SEL_APPROVE))
        self.assertEqual(signer.sent[1]["to"].lower(), ONRAMP)    # wrap
        self.assertTrue(signer.sent[1]["data"].startswith(bc.SEL_WRAP))

    def test_sufficient_allowance_skips_approve(self):
        rpc = FakeRpc(balances={USDCE: 2_000_000, PUSD: 0}, allowances={USDCE: 5_000_000})
        signer = FakeSigner()
        bc.ensure_pusd(signer, rpc, 1_000_000)
        self.assertEqual(len(signer.sent), 1)
        self.assertEqual(signer.sent[0]["to"].lower(), ONRAMP)

    def test_wrap_amount_is_the_shortfall(self):
        rpc = FakeRpc(balances={USDCE: 5_000_000, PUSD: 400_000}, allowances={USDCE: _big()})
        signer = FakeSigner()
        bc.ensure_pusd(signer, rpc, 1_000_000)
        wrapped = int(signer.sent[0]["data"][-64:], 16)
        self.assertEqual(wrapped, 600_000)

    def test_missing_injected_handler_is_a_clear_error(self):
        # Polygon USDT needs a swap handler, which is not built in.
        rpc = FakeRpc(balances={POLYGON_USDT: 3_000_000, PUSD: 0})
        signer = FakeSigner()
        with self.assertRaises(bc.ExecutionError):
            bc.ensure_pusd(signer, rpc, 1_000_000)

    def test_injected_swap_handler_runs_then_wrap(self):
        # USDC.e below the shortfall forces the planner onto the swap route; the
        # CREDITED wrap then consumes whatever USDC.e is present.
        rpc = FakeRpc(balances={POLYGON_USDT: 3_000_000, PUSD: 0, USDCE: 200_000}, allowances={USDCE: _big()})
        signer = FakeSigner()
        calls = []

        def swap(signer_, rpc_, step):
            calls.append(step["action"])
            return "0xswap"

        result = bc.ensure_pusd(signer, rpc, 1_000_000, handlers={"swap": swap})
        self.assertEqual(calls, ["swap"])
        self.assertEqual([s["action"] for s in result["steps"]], ["swap", "wrap"])

    def test_polygon_swap_is_locally_signed_with_bounded_approval(self):
        signer = FakeSigner()
        rpc = FakeRpc()
        balances = iter([200_000, 1_195_000])

        def route_builder(_args):
            return {
                "ok": True,
                "data": [{
                    "routerResult": {
                        "fromToken": {"isHoneyPot": False},
                        "toToken": {"isHoneyPot": False},
                    },
                    "tx": {
                        "to": "0x" + "22" * 20,
                        "data": "0x1234",
                        "value": "0",
                        "gas": "700000",
                        "minReceiveAmount": "990000",
                    },
                }],
            }

        with patch.object(bc, "balance_of", side_effect=lambda *_: next(balances)), \
             patch.object(bc, "allowance", return_value=0):
            tx_hash = bc.polygon_swap_handler(
                signer,
                rpc,
                {"from_token": "polygon_usdt", "amount_units": 1_000_000},
                route_builder=route_builder,
            )

        self.assertEqual(tx_hash, "0x" + f"{2:064x}")
        self.assertEqual(len(signer.sent), 2)
        self.assertTrue(signer.sent[0]["data"].startswith(bc.SEL_APPROVE))
        self.assertEqual(int(signer.sent[0]["data"][-64:], 16), 1_000_000)
        self.assertEqual(signer.sent[1]["to"], "0x" + "22" * 20)

    def test_polygon_swap_rejects_output_below_router_minimum(self):
        signer = FakeSigner()
        rpc = FakeRpc()
        balances = iter([0, 900_000])

        def route_builder(_args):
            return {
                "ok": True,
                "data": [{
                    "routerResult": {
                        "fromToken": {"isHoneyPot": False},
                        "toToken": {"isHoneyPot": False},
                    },
                    "tx": {
                        "to": "0x" + "22" * 20,
                        "data": "0x1234",
                        "value": "0",
                        "minReceiveAmount": "990000",
                    },
                }],
            }

        with patch.object(bc, "balance_of", side_effect=lambda *_: next(balances)), \
             patch.object(bc, "allowance", return_value=1_000_000):
            with self.assertRaises(bc.ExecutionError):
                bc.polygon_swap_handler(
                    signer,
                    rpc,
                    {"from_token": "polygon_usdt", "amount_units": 1_000_000},
                    route_builder=route_builder,
                )


class _Order:
    signatureType = 3
    maker = "0x" + "22" * 20  # deposit wallet (funder)
    signer = "0x" + "11" * 20  # EOA (key holder)


_DEFAULT_EOA = "0x" + "11" * 20
_DEFAULT_DEPOSIT_WALLET = "0x" + "22" * 20


class _Creds:
    api_key = "secret-api-key"


class _Clob:
    def __init__(self, address=_DEFAULT_EOA, deposit_wallet=_DEFAULT_DEPOSIT_WALLET):
        self.serialized = None
        self.created_side = None
        self.address = address
        self.deposit_wallet = deposit_wallet

    def create_or_derive_api_key(self):
        return _Creds()

    def set_api_creds(self, _creds):
        pass

    def get_tick_size(self, _token):
        return "0.001"

    def get_neg_risk(self, _token):
        return False

    def create_order(self, args, _options):
        self.created_side = args.side
        order = _Order()
        order.maker = self.deposit_wallet  # POLY_1271: maker = deposit wallet
        order.signer = self.address         # signer = EOA
        return order

    def _l2_headers(self, _method, _path, *, body, serialized_body):
        self.serialized = serialized_body
        return {
            "POLY_ADDRESS": self.address,
            "POLY_API_KEY": "secret-api-key",
            "POLY_PASSPHRASE": "secret-passphrase",
            "POLY_SIGNATURE": "secret-hmac",
            "POLY_TIMESTAMP": "1",
        }


def _fake_sdk_modules():
    sdk = types.ModuleType("py_clob_client_v2")

    class OrderArgs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class PartialCreateOrderOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class OrderType:
        GTC = "GTC"

    sdk.OrderArgs = OrderArgs
    sdk.OrderType = OrderType
    sdk.PartialCreateOrderOptions = PartialCreateOrderOptions
    endpoints = types.ModuleType("py_clob_client_v2.endpoints")
    endpoints.POST_ORDER = "/order"
    model = types.ModuleType("py_clob_client_v2.order_utils.model.order_data_v2")
    model.order_to_json_v2 = lambda order, owner, order_type: {
        "order": {
            "maker": order.maker,
            "signer": order.signer,
            "signatureType": 3,
            "signature": "secret-order-signature",
        },
        "owner": owner,
        "orderType": order_type,
    }
    return {
        "py_clob_client_v2": sdk,
        "py_clob_client_v2.endpoints": endpoints,
        "py_clob_client_v2.order_utils": types.ModuleType("py_clob_client_v2.order_utils"),
        "py_clob_client_v2.order_utils.model": types.ModuleType("py_clob_client_v2.order_utils.model"),
        "py_clob_client_v2.order_utils.model.order_data_v2": model,
    }


class EoaOrderSubmitterTests(unittest.TestCase):
    def test_serializes_once_headers_exact_bytes_and_redacts_result(self):
        clob = _Clob()
        seen = {}

        def post(url, payload):
            seen["url"] = url
            seen["payload"] = payload
            return {
                "intent_id": "intent-1",
                "state": "OPEN",
                "venue_order_id": "order-1",
                "signature": "must-not-escape",
                "headers": payload["headers"],
            }

        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=post,
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            result = submitter.submit({
                "intent": {
                    "intent_id": "intent-1",
                    "token_id": "123",
                    "price": "0.045",
                    "quantity": "5",
                    "side": "BUY",
                    "time_in_force": "GTC",
                },
                "client_execution": {
                    "submit_signed": {"url": "http://asp/v1/executions/intent-1/submit-signed"}
                },
            })

        raw = bc.base64.b64decode(seen["payload"]["body_base64"])
        self.assertEqual(raw, clob.serialized.encode())
        self.assertEqual(json.loads(raw)["order"]["signatureType"], 3)
        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["side"], "BUY")
        self.assertNotIn("signature", result)
        self.assertNotIn("headers", result)
        self.assertNotIn("secret", json.dumps(result))

    def test_builds_sell_order(self):
        clob = _Clob()
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=lambda *_: {"state": "OPEN"},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            result = submitter.submit({
                "token_id": "123",
                "price": "0.044",
                "quantity": "5",
                "time_in_force": "GTC",
                "deposit_wallet": _DEFAULT_DEPOSIT_WALLET,
                "client_execution": {
                    "submit_signed": {"url": "http://asp/submit-signed"}
                },
            }, side="SELL")
        self.assertEqual(clob.created_side, "SELL")
        self.assertEqual(result["side"], "SELL")

    def test_rejects_order_from_wrong_signer(self):
        """POLY_1271: signer must match the buyer EOA."""
        wrong_eoa = "0x" + "ff" * 20
        clob = _Clob(address=wrong_eoa, deposit_wallet=_DEFAULT_DEPOSIT_WALLET)
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=lambda *_: {"state": "OPEN"},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            with self.assertRaises(bc.ExecutionError):
                submitter.submit({
                    "token_id": "123",
                    "price": "0.045",
                    "quantity": "5",
                    "client_execution": {
                        "submit_signed": {"url": "http://asp/submit-signed"}
                    },
                })

    def test_rejects_invalid_side(self):
        clob = _Clob()
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=lambda *_: {"state": "OPEN"},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            with self.assertRaises(bc.ExecutionError):
                submitter.submit({
                    "token_id": "123",
                    "price": "0.045",
                    "quantity": "5",
                    "client_execution": {
                        "submit_signed": {"url": "http://asp/submit-signed"}
                    },
                }, side="HOLD")

    def test_rejects_missing_submit_url(self):
        clob = _Clob()
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=lambda *_: {"state": "OPEN"},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            with self.assertRaises(bc.ExecutionError):
                submitter.submit({
                    "token_id": "123",
                    "price": "0.045",
                    "quantity": "5",
                })

    def test_uses_tick_and_neg_risk_from_prepared_intent(self):
        clob = _Clob()
        clob_tick_called = []
        clob_neg_called = []
        original_tick = clob.get_tick_size
        original_neg = clob.get_neg_risk
        clob.get_tick_size = lambda t: (clob_tick_called.append(t), original_tick(t))[1]
        clob.get_neg_risk = lambda t: (clob_neg_called.append(t), original_neg(t))[1]

        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=lambda *_: {"state": "OPEN"},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            submitter.submit({
                "intent": {
                    "token_id": "123",
                    "price": "0.045",
                    "quantity": "5",
                    "tick_size": "0.001",
                    "neg_risk": False,
                },
                "pre_trade": {"validated_against_tick": "0.001"},
                "client_execution": {
                    "submit_signed": {"url": "http://asp/submit-signed"}
                },
            })
        self.assertEqual(clob_tick_called, [])
        self.assertEqual(clob_neg_called, [])

    def test_rejects_missing_deposit_wallet(self):
        """Without a deposit wallet, submit must fail with a clear error."""
        clob = _Clob()
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                client_factory=lambda **_: clob,
                asp_post=lambda *_: {"state": "OPEN"},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            with self.assertRaises(bc.ExecutionError):
                submitter.submit({
                    "token_id": "123",
                    "price": "0.045",
                    "quantity": "5",
                    "client_execution": {
                        "submit_signed": {"url": "http://asp/submit-signed"}
                    },
                })

    def test_emergency_control_authorization(self):
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: _Clob(),
                asp_post=lambda *_: {},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            auth = submitter.buyer_control_authorization(
                "buyer-1",
                action="cancel_only",
                reason="emergency test",
                timestamp=1000,
                nonce="test-nonce",
            )
        self.assertEqual(auth["action"], "cancel_only")
        self.assertEqual(auth["buyer_address"], _DEFAULT_EOA)
        self.assertEqual(auth["timestamp"], 1000)
        self.assertEqual(auth["nonce"], "test-nonce")
        self.assertTrue(auth["signature"].startswith("0x"))
        self.assertNotIn("private_key", json.dumps(auth).lower())

    def test_emergency_control_rejects_invalid_action(self):
        with patch.dict(sys.modules, _fake_sdk_modules()):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: _Clob(),
                asp_post=lambda *_: {},
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            with self.assertRaises(bc.ExecutionError):
                submitter.buyer_control_authorization(
                    "buyer-1", action="delete_all", reason="bad"
                )

    def test_emergency_cancellation_serializes_and_redacts(self):
        clob = _Clob()
        seen = {}

        def post(url, payload):
            seen["url"] = url
            seen["payload"] = payload
            return {
                "buyer_id": "buyer-1",
                "mode": "cancel_only",
                "cancelled_intents": ["intent-1"],
                "remaining_intents": [],
                "body_sha256": "abc",
                "secret_hmac": "must-not-escape",
            }

        cancel_modules = _fake_sdk_modules()
        cancel_modules["py_clob_client_v2.endpoints"].CANCEL_ORDERS = "/cancel-orders"

        with patch.dict(sys.modules, cancel_modules):
            submitter = bc.EoaOrderSubmitter(
                "0x" + "01".rjust(64, "0"),
                deposit_wallet=_DEFAULT_DEPOSIT_WALLET,
                client_factory=lambda **_: clob,
                asp_post=post,
                address_deriver=lambda _: _DEFAULT_EOA,
            )
            result = submitter.submit_emergency_cancellation(
                buyer_id="buyer-1",
                asp_url="http://asp/v1/executions/emergency-cancel",
                intents=[{"intent_id": "intent-1", "venue_order_id": "venue-1"}],
            )
        self.assertEqual(result["mode"], "cancel_only")
        self.assertNotIn("secret_hmac", result)
        raw = bc.base64.b64decode(seen["payload"]["body_base64"]).decode()
        self.assertIn("venue-1", raw)

    def test_buyer_config_references_existing_secret_without_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / ".existing"
            config = root / ".buyer"
            secret.write_text("EXISTING_KEY=0xabc\n", encoding="utf-8")
            config.write_text(
                "BUYER_SECRET_ENV_FILE=.existing\nBUYER_PRIVATE_KEY_NAME=EXISTING_KEY\n",
                encoding="utf-8",
            )
            secret.chmod(0o600)
            config.chmod(0o600)
            loaded = bc.load_buyer_config(config)
            config_text = config.read_text(encoding="utf-8")
        self.assertEqual(loaded["BUYER_PRIVATE_KEY"], "0xabc")
        self.assertNotIn("0xabc", config_text)


def _big():
    return (1 << 256) - 1


if __name__ == "__main__":
    unittest.main()
