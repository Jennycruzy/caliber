#!/usr/bin/env python3
"""POLY_1271 order signing through an OKX Agentic Wallet session.

The Polymarket v2 SDK builds the order and ERC-7739 envelope correctly, but its
POLY_1271 implementation signs the inner digest with a raw private key. This
adapter expresses that same digest as the nested ``TypedDataSign`` EIP-712
message understood by the deposit wallet, delegates only that message to
OnchainOS, and preserves the SDK's envelope byte-for-byte.
"""
from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable

from eth_abi import encode as abi_encode
from eth_utils import keccak
from py_clob_client_v2 import ClobClient
from py_clob_client_v2.clob_types import ApiCreds
from py_clob_client_v2.config import get_contract_config
from py_clob_client_v2.constants import BYTES32_ZERO
from py_clob_client_v2.order_builder.builder import OrderBuilder, ROUNDING_CONFIG
from py_clob_client_v2.order_utils.exchange_order_builder_v2 import (
    DEPOSIT_WALLET_DOMAIN_SALT,
    ORDER_TYPE_HASH,
    ORDER_TYPE_STRING,
    ExchangeOrderBuilderV2,
    _bytes32,
)
from py_clob_client_v2.order_utils.model.order_data_v2 import OrderDataV2
from py_clob_client_v2.order_utils.model.signature_type_v2 import SignatureTypeV2
from py_clob_client_v2.order_utils.model.ctf_exchange_v2_typed_data import (
    EIP712_DOMAIN,
)


TYPED_DATA_SIGN = [
    {"name": "contents", "type": "Order"},
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
    {"name": "salt", "type": "bytes32"},
]


def _json_value(value):
    return "0x" + value.hex() if isinstance(value, bytes) else value


def poly_1271_signing_message(typed_data: dict) -> dict:
    """Return the nested EIP-712 message whose digest the SDK signs directly."""
    order = {key: _json_value(value) for key, value in typed_data["message"].items()}
    # Preserve uint256 precision across the CLI/backend JSON boundary. Token IDs
    # exceed JavaScript's safe-integer range; EIP-712 encoders accept decimal
    # strings and hash them as the same uint values.
    uint_fields = {
        field["name"]
        for field in typed_data["types"]["Order"]
        if field["type"].startswith("uint")
    }
    for key in uint_fields:
        order[key] = str(order[key])
    return {
        "primaryType": "TypedDataSign",
        "types": {
            "EIP712Domain": EIP712_DOMAIN,
            "Order": typed_data["types"]["Order"],
            "TypedDataSign": TYPED_DATA_SIGN,
        },
        "domain": dict(typed_data["domain"]),
        "message": {
            "contents": order,
            "name": "DepositWallet",
            "version": "1",
            "chainId": int(typed_data["domain"]["chainId"]),
            "verifyingContract": order["signer"],
            "salt": "0x" + DEPOSIT_WALLET_DOMAIN_SALT.hex(),
        },
    }


class OnchainOSOrderSigner:
    """Signer surface needed by the v2 client; contains no private key."""

    def __init__(
        self,
        owner: str,
        chain_id: int = 137,
        sign_typed_data: Callable[[dict], str] | None = None,
    ):
        self._owner = owner
        self._chain_id = chain_id
        self._sign_typed_data = sign_typed_data or self._sign_with_onchainos

    def address(self) -> str:
        return self._owner

    def get_chain_id(self) -> int:
        return self._chain_id

    def sign_typed_data(self, message: dict) -> str:
        signature = self._sign_typed_data(message)
        return signature if signature.startswith("0x") else f"0x{signature}"

    def _sign_with_onchainos(self, message: dict) -> str:
        result = subprocess.run(
            [
                "onchainos",
                "wallet",
                "sign-message",
                "--type",
                "eip712",
                "--message",
                json.dumps(message, separators=(",", ":")),
                "--chain",
                "polygon",
                "--from",
                self._owner,
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "no diagnostic").strip()
            raise RuntimeError(
                f"Agentic Wallet order signing failed with exit code "
                f"{result.returncode}: {detail[:500]}"
            )
        payload = json.loads(result.stdout)
        signature = (
            (payload.get("data") or {}).get("signature") if payload.get("ok") else None
        )
        if not isinstance(signature, str) or not signature:
            raise RuntimeError("Agentic Wallet returned no EIP-712 order signature")
        return signature


class AgenticExchangeOrderBuilderV2(ExchangeOrderBuilderV2):
    """Official v2 order builder with an external POLY_1271 inner signer."""

    def _build_poly_1271_order_signature(self, typed_data: dict) -> str:
        nested = poly_1271_signing_message(typed_data)
        inner_signature = self.signer.sign_typed_data(nested).removeprefix("0x")

        # The ERC-7739 envelope is the official SDK format. Only the source of
        # the 65-byte inner signature differs from the upstream implementation.
        contents_hash = self._contents_hash(typed_data)
        contents_type = ORDER_TYPE_STRING.encode("utf-8").hex()
        contents_type_len = len(ORDER_TYPE_STRING).to_bytes(2, "big").hex()
        return (
            "0x"
            + inner_signature
            + self.app_domain_separator.hex()
            + contents_hash.hex()
            + contents_type
            + contents_type_len
        )

    @staticmethod
    def _contents_hash(typed_data: dict) -> bytes:
        message = typed_data["message"]
        return keccak(
            primitive=abi_encode(
                [
                    "bytes32",
                    "uint256",
                    "address",
                    "address",
                    "uint256",
                    "uint256",
                    "uint256",
                    "uint8",
                    "uint8",
                    "uint256",
                    "bytes32",
                    "bytes32",
                ],
                [
                    ORDER_TYPE_HASH,
                    int(message["salt"]),
                    message["maker"],
                    message["signer"],
                    int(message["tokenId"]),
                    int(message["makerAmount"]),
                    int(message["takerAmount"]),
                    int(message["side"]),
                    int(message["signatureType"]),
                    int(message["timestamp"]),
                    _bytes32(message["metadata"]),
                    _bytes32(message["builder"]),
                ],
            )
        )


class AgenticOrderBuilder(OrderBuilder):
    """v2-only SDK order builder wired to the external Agentic Wallet signer."""

    def build_order(self, order_args, options, version=2, fee_rate_bps=None):
        if version != 2:
            raise ValueError("Agentic Wallet adapter supports Polymarket v2 orders only")
        round_config = ROUNDING_CONFIG[options.tick_size]
        side, maker_amount, taker_amount = self.get_order_amounts(
            order_args.side, order_args.size, order_args.price, round_config
        )
        contracts = get_contract_config(self.signer.get_chain_id())
        exchange = (
            contracts.neg_risk_exchange_v2 if options.neg_risk else contracts.exchange_v2
        )
        order_data = OrderDataV2(
            maker=self.funder,
            tokenId=order_args.token_id,
            makerAmount=str(maker_amount),
            takerAmount=str(taker_amount),
            side=side,
            signer=self.funder,
            signatureType=SignatureTypeV2.POLY_1271,
            timestamp=str(time.time_ns() // 1_000_000),
            metadata=getattr(order_args, "metadata", BYTES32_ZERO),
            builder=order_args.builder_code,
            expiration=str(getattr(order_args, "expiration", 0)),
        )
        return AgenticExchangeOrderBuilderV2(
            exchange, self.signer.get_chain_id(), self.signer
        ).build_signed_order(order_data)


def agentic_clob_client(
    *,
    host: str,
    owner: str,
    deposit_wallet: str,
    creds: ApiCreds,
    chain_id: int = 137,
) -> ClobClient:
    """Create a normal v2 CLOB client with only its signing seam replaced."""
    client = ClobClient(host=host, chain_id=chain_id)
    signer = OnchainOSOrderSigner(owner, chain_id)
    client.signer = signer
    client.creds = creds
    client.mode = client._get_client_mode()
    client.builder = AgenticOrderBuilder(
        signer=signer,
        signature_type=SignatureTypeV2.POLY_1271,
        funder=deposit_wallet,
    )
    return client
